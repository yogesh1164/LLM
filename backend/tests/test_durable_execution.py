"""Offline journal contracts; PostgreSQL concurrency is tested separately."""

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import custom_agents, custom_workflows, main, workflow
from app import database as db
from app import durable_execution as durable
from app.config import settings
from app.providers import StageResult
from tests.test_custom_workflows import add_agent, add_workflow

client = TestClient(main.app, headers={"Authorization": "Bearer " + "t" * 32})


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "durable_execution_enabled", True)
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("offline-placeholder"))
    monkeypatch.setattr(settings, "ai_provider", "gemini")


def reserve(key=None, operation="fixed_execute", task="Offline task"):
    return durable.reserve(key or str(uuid4()), operation, {"task": task})


def expire(lease):
    with db.SessionLocal.begin() as session:
        session.get(db.DurableExecution, lease.id).lease_expires_at = (
            datetime.now(UTC) - timedelta(seconds=1))


def bind(lease):
    return durable.current_lease.set(lease)


def mock_fixed(monkeypatch, callback=None):
    names = ("orchestrator", "research", "analysis", "report", "review")
    monkeypatch.setattr(workflow, "build_agents", lambda: dict(zip(names, names)))
    calls = []

    async def provider(agent, prompt, **kwargs):
        calls.append(agent)
        if callback:
            callback()
        return StageResult(f"output-{agent}", input_tokens=3, output_tokens=2)

    monkeypatch.setattr(workflow, "run_agent_stage", provider)
    return calls


@pytest.mark.parametrize("key", [None, "short", "x" * 129, "contains spaces padded"])
def test_invalid_or_missing_key_never_creates_a_task(monkeypatch, key):
    calls = mock_fixed(monkeypatch)
    response = client.post("/api/workflows/execute", json={"task": "Offline task"},
                           headers={"Idempotency-Key": key} if key else {})
    assert response.status_code == 428
    assert not db.dashboard_data()["history"] and not calls


@pytest.mark.parametrize("path", ["execute", "collaborate", "stream"])
def test_matching_submission_never_replays_and_conflicting_payload_is_rejected(monkeypatch, path):
    calls = mock_fixed(monkeypatch)
    key = str(uuid4())
    url = f"/api/workflows/{path}"
    first = client.post(url, json={"task": "Offline task"}, headers={"Idempotency-Key": key})
    assert first.status_code == 200, first.text
    repeated = client.post(url, json={"task": "Offline task"}, headers={"Idempotency-Key": key})
    assert repeated.status_code == 202
    assert repeated.json()["state"] == "completed"
    assert repeated.json()["execution_id"] == first.headers["x-execution-id"]
    assert client.get(first.headers["location"]).json() == repeated.json()
    conflict = client.post(url, json={"task": "Different task"}, headers={"Idempotency-Key": key})
    assert conflict.status_code == 409
    assert len(calls) == 5 and len(db.dashboard_data()["history"]) == 1
    assert key not in repeated.text


@pytest.mark.parametrize("kind", ["custom_agent", "custom_workflow"])
def test_custom_execution_is_idempotent(monkeypatch, kind):
    agent = add_agent("Offline agent")
    calls = []

    async def provider(**kwargs):
        calls.append(kwargs["name"])
        return StageResult("saved output", input_tokens=3, output_tokens=2)

    if kind == "custom_agent":
        monkeypatch.setattr(custom_agents, "run_custom_gemini_agent", provider)
        url = f"/api/agents/{agent}/execute"
    else:
        monkeypatch.setattr(custom_workflows, "run_custom_gemini_agent", provider)
        url = f"/api/custom-workflows/{add_workflow([agent])}/execute"
    headers = {"Idempotency-Key": str(uuid4())}
    first = client.post(url, json={"task": "Offline task"}, headers=headers)
    assert first.status_code == 200, first.text
    second = client.post(url, json={"task": "Offline task"}, headers=headers)
    assert second.status_code == 202 and second.json()["state"] == "completed"
    assert len(calls) == 1


@pytest.mark.parametrize("attempted", [False, True])
def test_expired_work_is_classified_without_reexecution(attempted):
    lease, _ = reserve()
    token = bind(lease)
    try:
        task_id = db.create_task("Offline task")
        if attempted:
            durable.before_provider()
        expire(lease)
        with pytest.raises(durable.LeaseLost):
            durable.renew()
    finally:
        durable.current_lease.reset(token)
    assert durable.recover_expired() == 1
    assert durable.recover_expired() == 0
    state = client.get(f"/api/executions/{lease.id}").json()
    assert state["state"] == "interrupted"
    assert state["safe_to_resubmit"] is not attempted
    assert state["retry_safety"] == ("do_not_replay" if attempted else "not_started")
    assert not state["automatic_replay"]
    assert db.get_task(task_id)["status"] == "interrupted"


def test_live_lease_heartbeat_and_stale_token_cannot_be_stolen():
    lease, _ = reserve()
    token = bind(lease)
    try:
        db.create_task("Offline heartbeat")
        durable.renew()
        assert durable.recover_expired() == 0
    finally:
        durable.current_lease.reset(token)
    token = bind(durable.Lease(lease.id, str(uuid4())))
    try:
        with pytest.raises(durable.LeaseLost):
            durable.before_provider()
    finally:
        durable.current_lease.reset(token)


def test_recovery_rebuilds_partial_aggregates_and_fences_all_late_writes():
    lease, _ = reserve()
    token = bind(lease)
    try:
        task_id = db.create_task("Offline partial")
        first = db.start_stage(task_id, "Orchestrator")
        durable.before_provider()
        db.finish_stage(first, output="committed output", input_tokens=3, output_tokens=2)
        second = db.start_stage(task_id, "Research")
        # Crash window: no save_partial() parent update has happened.
        expire(lease)
        assert durable.recover_expired() == 1
        for mutation in [
            lambda: db.update_task(task_id, status="completed", total_tokens=999),
            lambda: db.finish_stage(second, output="late", input_tokens=50, output_tokens=50),
            lambda: db.fail_stage(first, "late failure"),
            lambda: db.start_stage(task_id, "Analysis"),
            lambda: db.finish_running_stages(task_id, status="failed", error="late"),
            durable.before_provider,
        ]:
            with pytest.raises(durable.LeaseLost):
                mutation()
    finally:
        durable.current_lease.reset(token)
    stored = db.get_task(task_id)
    assert stored["status"] == "interrupted" and stored["total_tokens"] == 5
    assert stored["result"]["plan"] == "committed output"
    assert sorted(s["status"] for s in stored["stages"]) == ["completed", "interrupted"]


def test_crash_after_target_completion_preserves_completion():
    lease, _ = reserve()
    token = bind(lease)
    try:
        task_id = db.create_task("Offline complete")
        db.update_task(task_id, status="completed", result={"review": "final"}, total_tokens=25)
    finally:
        durable.current_lease.reset(token)
    expire(lease)
    durable.recover_expired()
    assert client.get(f"/api/executions/{lease.id}").json()["state"] == "completed"
    assert db.get_task(task_id)["result"] == {"review": "final"}


def test_idempotency_tombstone_survives_result_deletion(monkeypatch):
    calls = mock_fixed(monkeypatch)
    key = str(uuid4())
    response = client.post("/api/workflows/execute", json={"task": "Offline task"},
                           headers={"Idempotency-Key": key})
    task_id = response.json()["task_id"]
    # SQLite fixture must enforce the migration's ON DELETE SET NULL contract.
    with db.SessionLocal().bind.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    assert client.delete(f"/api/tasks/{task_id}").status_code == 204
    repeat = client.post("/api/workflows/execute", json={"task": "Offline task"},
                         headers={"Idempotency-Key": key})
    assert repeat.status_code == 202 and repeat.json()["task_id"] is None
    assert len(calls) == 5


@pytest.mark.parametrize("path", ["execute", "stream"])
def test_unknown_worker_result_does_not_resurrect_recovered_task(monkeypatch, path):
    def abandon():
        expire(durable.current_lease.get())
        durable.recover_expired()

    calls = mock_fixed(monkeypatch, abandon)
    response = client.post(f"/api/workflows/{path}", json={"task": "Offline task"},
                           headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == (503 if path == "execute" else 200)
    if path == "stream":
        assert "ownership lost" in response.text
    assert len(calls) == 1
    assert db.dashboard_data()["history"][0]["status"] == "interrupted"


def test_heartbeat_runs_until_work_ends_and_stops_afterward(monkeypatch):
    monkeypatch.setattr(settings, "execution_heartbeat_seconds", 0.005)
    renewals = []
    original = durable.renew

    def renew():
        original()
        renewals.append(True)

    monkeypatch.setattr(durable, "renew", renew)
    lease, _ = reserve()

    async def exercise():
        async with durable.owned(lease):
            db.create_task("Offline heartbeat")
            while len(renewals) < 2:
                await asyncio.sleep(0.001)
        count = len(renewals)
        await asyncio.sleep(0.02)
        assert len(renewals) == count

    asyncio.run(asyncio.wait_for(exercise(), 2))


def test_startup_and_periodic_recovery_do_not_touch_unleased_legacy_rows(monkeypatch):
    legacy = db.create_task("Unleased legacy fixture")
    lease, _ = reserve()
    token = bind(lease)
    try:
        task_id = db.create_task("Offline startup")
    finally:
        durable.current_lease.reset(token)
    expire(lease)
    with TestClient(main.app, headers={"Authorization": "Bearer " + "t" * 32}):
        assert db.get_task(task_id)["status"] == "interrupted"
        assert db.get_task(legacy)["status"] == "running"


def test_child_process_crash_is_recovered_on_fresh_startup(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "durable-crash.sqlite").as_posix()
    script = '''
import os
from app import database as db, durable_execution as d
db.Base.metadata.create_all(db.engine)
lease, _ = d.reserve("offline-crash-key-1234", "fixed_execute", {"task": "offline"})
d.current_lease.set(lease)
task_id = db.create_task("Offline crash")
stage_id = db.start_stage(task_id, "Research")
d.before_provider()
db.finish_stage(stage_id, output="committed output", input_tokens=3, output_tokens=2)
db.start_stage(task_id, "Analysis")
os._exit(23)
'''
    env = {**os.environ, "DATABASE_URL": url, "APP_ENV": "development",
           "GEMINI_API_KEY": "offline-placeholder", "DURABLE_EXECUTION_ENABLED": "true"}
    child = subprocess.run([sys.executable, "-c", script], env=env, check=False,
                           capture_output=True, timeout=15)
    assert child.returncode == 23, child.stderr.decode(errors="replace")
    engine = create_engine(url)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(engine, expire_on_commit=False))
    try:
        with db.SessionLocal() as session:
            row = session.scalar(select(db.DurableExecution))
            lease = durable.Lease(row.id, row.lease_token)
            task_id = row.task_id
        expire(lease)
        with TestClient(main.app):
            stored = db.get_task(task_id)
            assert stored["status"] == "interrupted"
            assert stored["total_tokens"] == 5
            assert stored["result"]["research"] == "committed output"
            again, state = durable.reserve("offline-crash-key-1234", "fixed_execute", {"task": "offline"})
            assert again is None and state["retry_safety"] == "do_not_replay"
    finally:
        engine.dispose()


def test_same_key_conflicts_across_execution_surfaces():
    key = str(uuid4())
    reserve(key, "fixed_execute")
    with pytest.raises(HTTPException) as error:
        reserve(key, "fixed_stream")
    assert error.value.status_code == 409


def test_periodic_recovery_detects_a_lease_that_expires_after_startup(monkeypatch):
    monkeypatch.setattr(settings, "execution_recovery_seconds", 0.005)
    lease, _ = reserve()
    token = bind(lease)
    try:
        task_id = db.create_task("Offline periodic recovery")
    finally:
        durable.current_lease.reset(token)

    async def exercise():
        async with durable.lifespan(None):
            assert db.get_task(task_id)["status"] == "running"
            expire(lease)
            while db.get_task(task_id)["status"] == "running":
                await asyncio.sleep(0.001)
        assert db.get_task(task_id)["status"] == "interrupted"

    asyncio.run(asyncio.wait_for(exercise(), 2))


def test_heartbeat_failure_stops_work_without_allowing_another_provider_dispatch(monkeypatch):
    monkeypatch.setattr(settings, "execution_heartbeat_seconds", 0.005)
    lease, _ = reserve()

    def unavailable():
        raise ConnectionError("offline database outage")

    monkeypatch.setattr(durable, "renew", unavailable)

    async def exercise():
        with pytest.raises(durable.LeaseLost):
            async with durable.owned(lease):
                db.create_task("Offline failed heartbeat")
                await asyncio.Event().wait()

    asyncio.run(asyncio.wait_for(exercise(), 2))
    assert client.get(f"/api/executions/{lease.id}").json()["provider_attempted"] is False


def test_missing_journal_schema_fails_startup_without_creating_tables():
    engine = db.SessionLocal().bind
    db.DurableExecution.__table__.drop(engine)
    try:
        with pytest.raises(Exception, match="durable_executions"), TestClient(main.app):
            pytest.fail("Startup must fail closed with missing durable schema")
        from sqlalchemy import inspect
        assert "durable_executions" not in inspect(engine).get_table_names()
    finally:
        db.DurableExecution.__table__.create(engine)


def test_additive_migration_on_empty_sqlite_fixture(tmp_path):
    url = "sqlite:///" + (tmp_path / "migrated.sqlite").as_posix()
    env = {**os.environ, "DATABASE_URL": url, "APP_ENV": "development",
           "GEMINI_API_KEY": "offline-placeholder", "DURABLE_EXECUTION_ENABLED": "false"}
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                            cwd=Path(__file__).resolve().parents[1], env=env,
                            check=False, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    from sqlalchemy import inspect
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        columns = {column["name"] for column in inspector.get_columns("durable_executions")}
        assert columns == set(db.DurableExecution.__table__.columns.keys())
        assert {c["name"] for c in inspector.get_unique_constraints("durable_executions")} >= {
            "uq_durable_scope_key"}
    finally:
        engine.dispose()


def test_custom_workflow_recovery_preserves_completed_steps_and_fences_late_result(monkeypatch):
    wid = add_workflow([add_agent("First"), add_agent("Second"), add_agent("Third")])
    calls = []

    async def provider(**kwargs):
        calls.append(kwargs["name"])
        if len(calls) == 2:
            expire(durable.current_lease.get())
            durable.recover_expired()
        return StageResult("saved " + kwargs["name"], input_tokens=3, output_tokens=2)

    monkeypatch.setattr(custom_workflows, "run_custom_gemini_agent", provider)
    response = client.post(f"/api/custom-workflows/{wid}/execute", json={"task": "Offline task"},
                           headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 503
    state = client.get(response.headers["location"]).json()
    run = client.get(state["result_url"]).json()
    assert run["status"] == "interrupted" and run["result"] == "saved First"
    assert [s["status"] for s in run["steps"]] == ["completed", "interrupted", "interrupted"]
    assert run["steps"][0]["input_tokens"] == 3 and run["steps"][0]["output_tokens"] == 2
    assert calls == ["First", "Second"]


@pytest.mark.parametrize("expired", [False, True])
def test_durable_sdk_disables_automatic_retries_and_rechecks_dispatch_lease(monkeypatch, expired):
    from app.config import Settings
    from app.providers import ProviderRequestError
    from app.research import generate_gemini_stage
    from tests.test_gemini_responsiveness import _stub_gemini

    calls = []

    def provider(**kwargs):
        calls.append(True)
        error = RuntimeError("offline temporary unavailability")
        error.status_code = 503
        raise error

    _stub_gemini(monkeypatch, provider)
    lease, _ = reserve()
    token = bind(lease)
    try:
        db.create_task("Offline SDK fixture")
        if expired:
            expire(lease)
        config = Settings(_env_file=None, gemini_api_key=SecretStr("offline-placeholder"),
                          provider_retry_attempts=3)
        with pytest.raises(ProviderRequestError):
            asyncio.run(generate_gemini_stage("Research", "Offline", "Offline", config=config))
        assert len(calls) == (0 if expired else 1)
    finally:
        durable.current_lease.reset(token)


def test_stream_consumer_disconnect_closes_request_worker_before_finishing_lease(monkeypatch):
    from app.schemas import WorkflowRequest

    entered, exited = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(workflow, "build_agents", lambda: {"orchestrator": "orchestrator"})

    async def provider(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()

    monkeypatch.setattr(workflow, "run_agent_stage", provider)

    async def exercise():
        request = Request({"type": "http", "headers": [
            (b"idempotency-key", str(uuid4()).encode())], "client": ("offline", 1)})
        response = await main.stream_workflow(WorkflowRequest(task="Offline disconnect"), request)
        iterator = response.body_iterator
        assert "started" in await anext(iterator)
        await asyncio.wait_for(entered.wait(), 1)
        await iterator.aclose()
        assert exited.is_set()
        stored = db.dashboard_data()["history"][0]
        assert stored["status"] != "running"
        assert stored["stages"][0]["status"] == "cancelled"

    asyncio.run(asyncio.wait_for(exercise(), 2))
