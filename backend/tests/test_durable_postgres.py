"""Real PostgreSQL locking/migration tests, only against the named disposable DB.

Run in the network namespace of a no-network, tmpfs-backed fixture container.
No fallback to settings.database_url, development or production databases.
"""

import asyncio
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy import inspect as inspect_db
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import database as db
from app import durable_execution as durable
from app.config import settings


def migration_config():
    # In-process fixtures must not run fileConfig and disable the app loggers.
    # Real CLI configuration is covered in the subprocess migration test.
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    return config


@pytest.fixture
def postgres(monkeypatch, request):
    raw_url = os.environ.get("DURABLE_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("Isolated PostgreSQL fixture URL not supplied")
    url = make_url(raw_url)
    assert url.database == "agentflow_durable_fixture" and url.host == "127.0.0.1"
    assert url.username == "durable_fixture"
    schema = "durable_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated_url = url.update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(isolated_url, pool_size=10, max_overflow=0)
    monkeypatch.setattr(settings, "database_url", isolated_url.render_as_string(hide_password=False))
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(engine, expire_on_commit=False))
    try:
        command.upgrade(migration_config(), getattr(request, "param", "0006_durable_executions"))
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            # Identifier is locally generated hex, never user input.
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def reserve(key=None):
    return durable.reserve(key or str(uuid4()), "fixed_execute", {"task": "offline"})


def seed_expired():
    lease, _ = reserve()
    token = durable.current_lease.set(lease)
    try:
        task_id = db.create_task("Offline PostgreSQL fixture")
        stage_id = db.start_stage(task_id, "Research")
        durable.before_provider()
        db.finish_stage(stage_id, output="saved output", input_tokens=3, output_tokens=2)
        db.start_stage(task_id, "Analysis")
    finally:
        durable.current_lease.reset(token)
    with db.SessionLocal.begin() as session:
        session.get(db.DurableExecution, lease.id).lease_expires_at = (
            datetime.now(UTC) - timedelta(seconds=1))
    return lease, task_id


def test_concurrent_submissions_admit_exactly_one_worker(postgres):
    key, barrier, calls = str(uuid4()), Barrier(8), []

    def worker():
        barrier.wait(timeout=5)
        lease, view = reserve(key)
        if lease:
            token = durable.current_lease.set(lease)
            try:
                task_id = db.create_task("Offline concurrent fixture")
                durable.before_provider()
                calls.append("fake-provider")
                db.update_task(task_id, status="completed", result={"review": "saved"})
                durable.finish()
            finally:
                durable.current_lease.reset(token)
        return lease, view

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: worker(), range(8)))
    assert sum(lease is not None for lease, _ in results) == 1
    assert len({view["execution_id"] for _, view in results}) == 1
    assert calls == ["fake-provider"]
    assert len(db.dashboard_data()["history"]) == 1


def test_concurrent_recovery_workers_each_finalize_a_job_once(postgres):
    seeded = [seed_expired() for _ in range(12)]
    barrier = Barrier(4)

    def recover():
        barrier.wait(timeout=5)
        return durable.recover_expired()

    with ThreadPoolExecutor(max_workers=4) as pool:
        counts = list(pool.map(lambda _: recover(), range(4)))
    assert sum(counts) == 12
    assert durable.recover_expired() == 0
    for _, task_id in seeded:
        task = db.get_task(task_id)
        assert task["status"] == "interrupted" and task["total_tokens"] == 5
        assert task["result"]["research"] == "saved output"
        assert sorted(s["status"] for s in task["stages"]) == ["completed", "interrupted"]


def test_recovery_skips_locked_job_then_recovers_after_release(postgres):
    lease, _ = seed_expired()
    with db.SessionLocal.begin() as session:
        session.execute(select(db.DurableExecution).where(
            db.DurableExecution.id == lease.id).with_for_update())
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(durable.recover_expired).result(timeout=3) == 0
    assert durable.recover_expired() == 1


def test_database_clock_and_expiry_fence_reject_a_stale_worker(postgres, monkeypatch):
    lease, task_id = seed_expired()
    token = durable.current_lease.set(lease)
    try:
        with pytest.raises(durable.LeaseLost):
            durable.renew()
        durable.recover_expired()
        with pytest.raises(durable.LeaseLost):
            db.update_task(task_id, status="completed", total_tokens=999)
        with pytest.raises(durable.LeaseLost):
            durable.before_provider()
    finally:
        durable.current_lease.reset(token)
    assert db.get_task(task_id)["status"] == "interrupted"


def test_tombstone_survives_postgres_result_deletion(postgres):
    key = str(uuid4())
    lease, _ = reserve(key)
    token = durable.current_lease.set(lease)
    try:
        task_id = db.create_task("Offline deleted result")
        durable.before_provider()
        db.update_task(task_id, status="completed", result={"review": "saved"})
        durable.finish()
    finally:
        durable.current_lease.reset(token)
    assert db.delete_task_record(task_id)
    again, view = reserve(key)
    assert again is None and view["task_id"] is None and view["state"] == "completed"


@pytest.mark.parametrize("postgres", ["0005_custom_workflows"], indirect=True)
def test_additive_migration_leaves_legacy_rows_untouched(postgres):
    task_id = db.create_task("Unleased legacy PostgreSQL fixture")
    stage_id = db.start_stage(task_id, "Research")
    db.finish_stage(stage_id, output="legacy output", input_tokens=3, output_tokens=2)
    before = db.get_task(task_id)
    command.upgrade(migration_config(), "head")
    assert durable.recover_expired() == 0
    after = db.get_task(task_id)
    for field in ("status", "result", "total_tokens", "stages", "completed_at"):
        assert after[field] == before[field]


def test_postgres_child_crash_is_recovered_without_replay(postgres):
    script = '''
import os
from app import database as db, durable_execution as d
lease, _ = d.reserve("postgres-crash-key-1234", "fixed_execute", {"task": "offline"})
d.current_lease.set(lease)
task_id = db.create_task("Offline PostgreSQL crash")
stage_id = db.start_stage(task_id, "Research")
d.before_provider()
db.finish_stage(stage_id, output="committed output", input_tokens=3, output_tokens=2)
db.start_stage(task_id, "Analysis")
os._exit(23)
'''
    env = {**os.environ, "DATABASE_URL": settings.database_url, "APP_ENV": "development",
           "GEMINI_API_KEY": "offline-placeholder"}
    child = subprocess.run([sys.executable, "-c", script], env=env, check=False,
                           capture_output=True, timeout=15)
    assert child.returncode == 23, child.stderr.decode(errors="replace")
    with db.SessionLocal.begin() as session:
        row = session.scalar(select(db.DurableExecution))
        task_id = row.task_id
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert durable.recover_expired() == 1
    task = db.get_task(task_id)
    assert task["status"] == "interrupted" and task["total_tokens"] == 5
    assert task["result"]["research"] == "committed output"
    lease, view = durable.reserve("postgres-crash-key-1234", "fixed_execute", {"task": "offline"})
    assert lease is None and view["retry_safety"] == "do_not_replay"


def test_live_postgres_heartbeat_preserves_ownership(postgres, monkeypatch):
    monkeypatch.setattr(settings, "execution_heartbeat_seconds", 0.01)
    lease, _ = reserve()

    async def exercise():
        async with durable.owned(lease):
            task_id = db.create_task("Offline PostgreSQL heartbeat")
            with db.SessionLocal() as session:
                initial = session.get(db.DurableExecution, lease.id).heartbeat_at
            await asyncio.sleep(0.05)
            with db.SessionLocal() as session:
                assert session.get(db.DurableExecution, lease.id).heartbeat_at > initial
            assert durable.recover_expired() == 0
            db.update_task(task_id, status="completed", result={"review": "done"})

    asyncio.run(asyncio.wait_for(exercise(), 3))


def legacy_history():
    """All original content tables, seeded only in the fixture schema."""
    with db.SessionLocal.begin() as session:
        task = db.Task(prompt="Offline legacy task", status="completed", total_tokens=5,
                       result={"research": "legacy research"})
        task.stages = [db.AgentExecution(agent="Research", status="completed", output="legacy research",
                                         input_tokens=3, output_tokens=2)]
        agent = db.CustomAgent(name="Offline legacy specialist", role="Offline",
                              system_instructions="Offline", provider="gemini", model=settings.gemini_model)
        session.add_all([task, agent]); session.flush()
        execution = db.CustomAgentExecution(agent_id=agent.id, task="Offline history", status="completed",
                                             provider="gemini", model=agent.model, result="legacy agent output",
                                             input_tokens=3, output_tokens=2)
        workflow = db.CustomWorkflow(name="Offline legacy workflow")
        workflow.steps = [db.CustomWorkflowStep(agent_id=agent.id, position=0)]
        session.add_all([execution, workflow]); session.flush()
        run = db.CustomWorkflowRun(workflow_id=workflow.id, workflow_name=workflow.name, task="Offline run",
                                   status="failed", result="legacy partial output")
        run.steps = [db.CustomWorkflowStepRun(position=0, agent_name=agent.name, provider="gemini",
                       model=agent.model, status="completed", output="legacy partial output",
                       input_tokens=3, output_tokens=2)]
        session.add(run)


def content_snapshot(engine):
    legacy_tables = {"tasks", "agent_executions", "custom_agents", "custom_agent_executions",
                     "custom_workflows", "custom_workflow_steps", "custom_workflow_runs",
                     "custom_workflow_step_runs"}
    tables = [table for name, table in db.Base.metadata.tables.items() if name in legacy_tables]
    with engine.connect() as connection:
        return {table.name: sorted([tuple(row) for row in connection.execute(
                    select(*[c for c in table.c if c.name != "owner_id"]))], key=repr)
                for table in tables}


@pytest.mark.parametrize("postgres", ["0005_custom_workflows"], indirect=True)
def test_0006_preserves_all_legacy_history_tracks_revision_and_reapplies_safely(postgres):
    legacy_history()
    before = content_snapshot(postgres)
    command.upgrade(migration_config(), "0006_durable_executions")
    command.upgrade(migration_config(), "0006_durable_executions")
    assert content_snapshot(postgres) == before
    inspector = inspect_db(postgres)
    assert {c["name"] for c in inspector.get_columns("durable_executions")} == set(
        db.DurableExecution.__table__.columns.keys()) - {"owner_id"}
    assert [(i["name"], i["column_names"]) for i in inspector.get_indexes("durable_executions")
            if not i.get("duplicates_constraint")] == [("ix_durable_expiry", ["state", "lease_expires_at"])]
    uniques = {tuple(c["column_names"]) for c in inspector.get_unique_constraints("durable_executions")}
    assert uniques == {("scope", "key_digest"), ("task_id",), ("agent_execution_id",), ("workflow_run_id",)}
    fks = inspector.get_foreign_keys("durable_executions")
    assert {fk["referred_table"] for fk in fks} == {"tasks", "custom_agent_executions", "custom_workflow_runs"}
    assert all(fk["options"]["ondelete"] == "SET NULL" for fk in fks)
    from app.verify_durable_schema import verify_schema
    assert verify_schema(postgres)["schema_verified"] is True
    assert {c["name"] for c in inspector.get_check_constraints("durable_executions")} == {
        "ck_durable_state", "ck_durable_one_target"}
    with postgres.connect() as connection:
        assert connection.scalars(text("SELECT version_num FROM alembic_version")).all() == ["0006_durable_executions"]
        assert connection.scalar(text("SELECT count(*) FROM durable_executions")) == 0


@pytest.mark.parametrize("violation", ["duplicate_key", "orphan_target", "multiple_targets", "invalid_state"])
def test_0006_database_constraints_reject_invalid_journals_atomically(postgres, violation):
    legacy_history()
    lease, _ = reserve()
    with db.SessionLocal() as session:
        original = session.get(db.DurableExecution, lease.id)
        values = {column.name: getattr(original, column.name) for column in db.DurableExecution.__table__.columns
                  if column.name != "owner_id"}
        values["id"] = str(uuid4())
        if violation != "duplicate_key":
            values["key_digest"] = uuid4().hex * 2
        if violation == "orphan_target":
            values["task_id"] = str(uuid4())
        elif violation == "multiple_targets":
            values["task_id"] = session.scalar(select(db.Task.id))
            values["workflow_run_id"] = session.scalar(select(db.CustomWorkflowRun.id))
        elif violation == "invalid_state":
            values["state"] = "replay"
    with pytest.raises(IntegrityError), postgres.begin() as connection:
        connection.execute(db.DurableExecution.__table__.insert().values(**values))
    with postgres.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM durable_executions")) == 1


@pytest.mark.parametrize("postgres", ["0005_custom_workflows"], indirect=True)
def test_0006_failed_ddl_rolls_back_table_and_revision_without_stamp(postgres, monkeypatch):
    from alembic import op

    legacy_history()
    before = content_snapshot(postgres)
    with monkeypatch.context() as patch:
        def fail_index(*args, **kwargs):
            raise RuntimeError("Injected fixture DDL failure")

        patch.setattr(op, "create_index", fail_index)
        with pytest.raises(RuntimeError, match="Injected fixture DDL failure"):
            command.upgrade(migration_config(), "head")
    assert "durable_executions" not in inspect_db(postgres).get_table_names()
    with postgres.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0005_custom_workflows"
    assert content_snapshot(postgres) == before
    command.upgrade(migration_config(), "head")
    assert "durable_executions" in inspect_db(postgres).get_table_names()


def test_0006_unsupported_downgrade_preserves_journal_and_revision(postgres):
    lease, _ = reserve()
    with pytest.raises(RuntimeError, match="explicit retention/rollback decision"):
        command.downgrade(migration_config(), "0005_custom_workflows")
    with db.SessionLocal() as session:
        assert session.get(db.DurableExecution, lease.id) is not None
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0006_durable_executions"


def test_schema_verifier_detects_missing_index_even_with_correct_revision(postgres):
    from app.verify_durable_schema import verify_schema

    with postgres.begin() as connection:
        connection.execute(text("DROP INDEX ix_durable_expiry"))
    with pytest.raises(ValueError, match="expiry index"):
        verify_schema(postgres)


@pytest.mark.parametrize("surface", ["execute", "collaborate", "stream", "custom_agent", "custom_workflow"])
def test_enabled_api_on_migrated_postgres_preserves_all_execution_contracts(postgres, monkeypatch, surface):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    from app import custom_agents, custom_workflows, main
    from app.providers import StageResult
    from tests.test_custom_workflows import add_agent, add_workflow
    from tests.test_durable_execution import mock_fixed

    monkeypatch.setattr(settings, "durable_execution_enabled", True)
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("offline-only"))
    calls = mock_fixed(monkeypatch)

    async def custom_provider(**kwargs):
        calls.append(kwargs["name"])
        return StageResult("Offline saved result", input_tokens=3, output_tokens=2)

    monkeypatch.setattr(custom_agents, "run_custom_gemini_agent", custom_provider)
    monkeypatch.setattr(custom_workflows, "run_custom_gemini_agent", custom_provider)
    if surface == "custom_agent":
        path = f"/api/agents/{add_agent('Offline specialist')}/execute"
    elif surface == "custom_workflow":
        path = f"/api/custom-workflows/{add_workflow([add_agent('Offline specialist')])}/execute"
    else:
        path = f"/api/workflows/{surface}"
    with TestClient(main.app, headers={"Authorization": "Bearer " + "t" * 32}) as client:
        key = str(uuid4())
        first = client.post(path, json={"task": "Offline enabled integration"}, headers={"Idempotency-Key": key})
        assert first.status_code == 200, first.text
        again = client.post(path, json={"task": "Offline enabled integration"}, headers={"Idempotency-Key": key})
        assert again.status_code == 202 and again.json()["state"] == "completed"
        assert client.get(first.headers["location"]).json()["state"] == "completed"
        assert len(calls) == (1 if surface.startswith("custom_") else 5)
    with db.SessionLocal() as session:
        assert len(session.scalars(select(db.DurableExecution)).all()) == 1
