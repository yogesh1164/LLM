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
from sqlalchemy.engine import make_url
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
        command.upgrade(migration_config(), getattr(request, "param", "head"))
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
