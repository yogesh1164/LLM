"""Synthetic migration and reviewed manifest checks; never use the configured DB."""
import copy
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from app import accounts, legacy_ownership
from app import database as db
from app.auth_foundation import Role
from app.config import settings
from tests.test_durable_postgres import legacy_history, migration_config


@pytest.fixture
def migrated(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "account-migration.sqlite").as_posix()
    monkeypatch.setattr(settings, "database_url", url)
    engine = create_engine(url)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(engine, expire_on_commit=False))
    command.upgrade(migration_config(), "0005_custom_workflows")
    legacy_history()
    with engine.connect() as connection:
        before = {name: connection.execute(text(f'SELECT * FROM "{name}"')).all()
                  for name in legacy_ownership.TABLES if name != "durable_executions"}
    command.upgrade(migration_config(), "head")
    command.upgrade(migration_config(), "head")
    with engine.connect() as connection:
        for name, original in before.items():
            columns = [c["name"] for c in inspect(engine).get_columns(name) if c["name"] != "owner_id"]
            actual = connection.execute(text(f'SELECT {", ".join(columns)} FROM "{name}"')).all()
            assert actual == original
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0007_accounts_ownership"
    yield engine
    engine.dispose()


def admin():
    return accounts.create_user("chosen-admin", "synthetic-admin-password", role=Role.ADMIN, bootstrap=True)


def test_schema_and_legacy_data_remain_unassigned(migrated):
    inspector = inspect(migrated)
    for name in legacy_ownership.ROOTS:
        assert any(c["name"] == "owner_id" and c["nullable"] for c in inspector.get_columns(name))
        assert any(f["referred_table"] == "users" and f["options"]["ondelete"] == "RESTRICT"
                   for f in inspector.get_foreign_keys(name))
        with migrated.connect() as connection:
            assert connection.scalar(text(f'SELECT count(*) FROM "{name}" WHERE owner_id IS NOT NULL')) == 0
    with migrated.connect() as connection:
        assert connection.scalar(select(accounts.User.id)) is None


def test_manifest_assignment_is_explicit_repeatable_and_audited(migrated):
    owner = admin()
    with migrated.connect() as connection:
        manifest = legacy_ownership.plan(connection, owner)
    assert "Offline legacy task" not in str(manifest)
    with migrated.begin() as connection:
        assert legacy_ownership.apply(connection, manifest, confirm_login="chosen-admin",
                                      approved_by="synthetic-approval-001") == 5
    with migrated.begin() as connection:
        assert legacy_ownership.apply(connection, manifest, confirm_login="chosen-admin",
                                      approved_by="synthetic-approval-001") == 0
        assert connection.scalar(select(accounts.OwnershipAssignment.row_count)) == 5


@pytest.mark.parametrize("failure", ["wrong-login", "tampered", "stale", "rollback"])
def test_failed_assignment_never_partially_claims_data(migrated, failure):
    owner = admin()
    with migrated.connect() as connection:
        manifest = legacy_ownership.plan(connection, owner)
    if failure == "tampered":
        manifest = copy.deepcopy(manifest)
        manifest["owner_id"] = str(uuid4())
    if failure == "stale":
        with migrated.begin() as connection:
            connection.execute(text("UPDATE tasks SET prompt = 'changed after review'"))
    with pytest.raises((ValueError, RuntimeError)), migrated.begin() as connection:
        legacy_ownership.apply(connection, manifest,
            confirm_login="wrong" if failure == "wrong-login" else "chosen-admin",
            approved_by="synthetic-approval")
        if failure == "rollback":
            raise RuntimeError("Injected failure before commit")
    with migrated.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM tasks WHERE owner_id IS NOT NULL")) == 0
        assert connection.scalar(select(accounts.OwnershipAssignment.manifest_digest)) is None


def test_member_cannot_be_selected_for_legacy_assignment(migrated):
    identifier = accounts.create_user("ordinary-member", "synthetic-member-password")
    with migrated.connect() as connection, pytest.raises(ValueError, match="administrator"):
        legacy_ownership.plan(connection, identifier)


def test_account_downgrade_refuses_data_loss(migrated):
    admin()
    with pytest.raises(RuntimeError, match="retention"):
        command.downgrade(migration_config(), "0006_durable_executions")
    with migrated.connect() as connection:
        assert connection.scalar(select(accounts.User.login)) == "chosen-admin"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0007_accounts_ownership"
