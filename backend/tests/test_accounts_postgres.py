"""Account transactions and integrated ownership on the disposable PostgreSQL fixture."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select, text

from app import accounts, legacy_ownership
from app import database as db
from app.auth_foundation import Role
from tests.test_account_api import account_mode as account_mode_fixture
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
