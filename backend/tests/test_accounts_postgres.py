"""Account transactions and integrated ownership on the disposable PostgreSQL fixture."""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select, text

from app import accounts, legacy_ownership
from app import database as db
from app import durable_execution as durable
from app.auth_foundation import Role
from app.config import settings
from tests.test_account_api import account_mode as account_mode_fixture
from tests.test_account_api import signed_in
from tests.test_account_api import (
    test_two_users_durable_workflow_and_all_resource_boundaries as exercise_two_users,
)
from tests.test_durable_postgres import (
    content_snapshot,
    legacy_history,
    migration_config,
)
from tests.test_durable_postgres import (
    postgres as postgres_fixture,
)

postgres = postgres_fixture
account_mode = account_mode_fixture


@pytest.mark.parametrize("postgres", ["head"], indirect=True)
def test_postgres_accounts_durable_api(postgres, account_mode, monkeypatch):
    exercise_two_users(account_mode, monkeypatch)


@pytest.mark.parametrize("postgres", ["0005_custom_workflows"], indirect=True)
def test_postgres_legacy_upgrade_and_reviewed_assignment(postgres):
    legacy_history()
    before = content_snapshot(postgres)
    command.upgrade(migration_config(), "head")
    command.upgrade(migration_config(), "head")
    assert content_snapshot(postgres) == before
    owner = accounts.create_user("selected-admin", "synthetic-admin-password", role=Role.ADMIN, bootstrap=True)
    with postgres.connect() as connection:
        manifest = legacy_ownership.plan(connection, owner)
    with postgres.begin() as connection:
        assert legacy_ownership.apply(connection, manifest, confirm_login="selected-admin",
                                      approved_by="offline-test") == 5
    with postgres.begin() as connection:
        assert legacy_ownership.apply(connection, manifest, confirm_login="selected-admin",
                                      approved_by="offline-test") == 0
    assert content_snapshot(postgres) == before
    from app.verify_durable_schema import verify_schema
    assert verify_schema(postgres)["revision"] == "0007_accounts_ownership"


@pytest.mark.parametrize("postgres", ["head"], indirect=True)
def test_postgres_throttling_is_atomic_across_workers(postgres):
    barrier = Barrier(8)
    def attempt(_):
        barrier.wait(timeout=10)
        try:
            accounts.admit_login("concurrent-user")
            return 200
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count(200) == 5 and results.count(429) == 3


@pytest.mark.parametrize("postgres", ["0006_durable_executions"], indirect=True)
def test_account_ddl_failure_rolls_back_entire_revision(postgres, monkeypatch):
    from alembic import op
    original = op.create_index
    def injected(name, *args, **kwargs):
        if name == "uq_custom_agents_owner_name_ci":
            raise RuntimeError("Injected account DDL failure")
        return original(name, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(op, "create_index", injected)
        with pytest.raises(RuntimeError, match="Injected"):
            command.upgrade(migration_config(), "head")
    from sqlalchemy import inspect
    assert "users" not in inspect(postgres).get_table_names()
    assert "owner_id" not in {c["name"] for c in inspect(postgres).get_columns("tasks")}
    with db.SessionLocal() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0006_durable_executions"
    command.upgrade(migration_config(), "head")
    with db.SessionLocal() as session:
        assert session.scalar(select(accounts.User.id)) is None


@pytest.mark.parametrize("postgres", ["head"], indirect=True)
@pytest.mark.parametrize("crash_point", ["before_provider", "after_stage", "before_finish"])
def test_account_process_crash_recovery_preserves_owner_and_blocks_replay(postgres, account_mode, crash_point):
    """An abruptly exiting worker commits to real PostgreSQL, never a provider."""
    a, b = signed_in("member-a"), signed_in("member-b")
    principal = accounts.authenticate(a.cookies.get("agentflow_session_dev"))
    key = str(uuid4())
    script = '''
import os
from uuid import UUID
from app import database as db, durable_execution as d
from app.auth_foundation import Principal, Role
from app.ownership import current_principal
current_principal.set(Principal(UUID(os.environ["FIXTURE_OWNER"]), Role.ADMIN))
lease, _ = d.reserve(os.environ["FIXTURE_KEY"], "fixed_execute", {"task": "offline"})
d.current_lease.set(lease)
tid = db.create_task("offline")
if os.environ["FIXTURE_CRASH"] == "before_provider":
    os._exit(23)
sid = db.start_stage(tid, "Research")
d.before_provider()
db.finish_stage(sid, output="private committed partial", input_tokens=3, output_tokens=2)
if os.environ["FIXTURE_CRASH"] == "before_finish":
    db.update_task(tid, status="completed", total_tokens=5, result={"research": "private committed partial"})
else:
    db.start_stage(tid, "Analysis")
os._exit(23)
'''
    env = {**os.environ, "DATABASE_URL": settings.database_url, "APP_ENV": "development",
           "AUTH_MODE": "accounts", "DURABLE_EXECUTION_ENABLED": "true",
           "GEMINI_API_KEY": "offline-placeholder", "FIXTURE_OWNER": str(principal.user_id),
           "FIXTURE_KEY": key, "FIXTURE_CRASH": crash_point}
    child = subprocess.run([sys.executable, "-c", script], env=env, check=False,
                           capture_output=True, timeout=15)
    assert child.returncode == 23, "Offline child did not reach the requested crash point"
    with db.SessionLocal.begin() as session:
        row = session.scalar(select(db.DurableExecution))
        execution_id, task_id = row.id, row.task_id
        assert session.scalar(select(db.DurableExecution.__table__.c.owner_id)) == principal.user_id
        assert session.scalar(select(db.Task.__table__.c.owner_id)) == principal.user_id
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    # Recovery is a service operation and must not require a surviving login.
    accounts.revoke(a.cookies.get("agentflow_session_dev"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(lambda _: durable.recover_expired(), range(4))) == 1
    assert durable.recover_expired() == 0
    assert a.get(f"/api/tasks/{task_id}").status_code == 401
    a = signed_in("member-a")
    task = a.get(f"/api/tasks/{task_id}").json()
    view = a.get(f"/api/executions/{execution_id}").json()
    assert view["state"] == ("completed" if crash_point == "before_finish" else "interrupted")
    assert view["automatic_replay"] is False
    assert view["provider_attempted"] == (crash_point != "before_provider")
    if crash_point != "before_provider":
        assert task["result"]["research"] == "private committed partial"
        assert task["total_tokens"] == 5
    if crash_point == "after_stage":
        assert [s["status"] for s in task["stages"]] == ["completed", "interrupted"]
    assert b.get(f"/api/tasks/{task_id}").status_code == 404
    assert b.get(f"/api/executions/{execution_id}").status_code == 404
    assert b.delete(f"/api/tasks/{task_id}").status_code == 404
    # Same-key retry returns the journal before entering the provider adapter.
    retry = a.post("/api/workflows/execute", json={"task": "offline"}, headers={"Idempotency-Key": key})
    assert retry.status_code == 202 and retry.json()["execution_id"] == execution_id
    from app.ownership import current_principal
    context = current_principal.set(accounts.authenticate(b.cookies.get("agentflow_session_dev")))
    try:
        other_lease, _ = durable.reserve(key, "fixed_execute", {"task": "offline"})
        assert other_lease is not None and other_lease.id != execution_id
    finally:
        current_principal.reset(context)
