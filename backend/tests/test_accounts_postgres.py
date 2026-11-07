"""Account transactions and integrated ownership on the disposable PostgreSQL fixture."""
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text

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


@pytest.mark.parametrize("postgres", ["0005_custom_workflows"], indirect=True)
def test_0005_backup_failed_0007_restore_and_quarantine(postgres, monkeypatch, tmp_path, capsys):
    """Real PG16 rehearsal: backup at 0005, fail 0007, restore elsewhere, then migrate."""
    container = os.environ.get("MIGRATION_REHEARSAL_CONTAINER")
    if not container:
        pytest.skip("Disposable migration rehearsal container was not selected")
    import importlib.util

    from alembic import op
    from sqlalchemy import inspect

    from app import legacy_ownership
    from app.verify_durable_schema import verify_schema
    backup_spec = importlib.util.spec_from_file_location(
        "migration_rehearsal_backup", Path(__file__).resolve().parents[2] / "ops/backup/backup.py")
    backup_tool = importlib.util.module_from_spec(backup_spec)
    backup_spec.loader.exec_module(backup_tool)
    from tests.test_durable_postgres import legacy_history

    legacy_history()
    before = content_snapshot(postgres)
    table_names = sorted(before)
    with postgres.connect() as connection:
        before_counts = {name: connection.scalar(text(f'SELECT count(*) FROM "{name}"'))
                         for name in table_names}
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0005_custom_workflows"

    age_binary = os.environ.get("AGENTFLOW_TEST_AGE_BINARY")
    age_keygen = os.environ.get("AGENTFLOW_TEST_AGE_KEYGEN")
    if not age_binary or not age_keygen:
        pytest.skip("Explicit local age/age-keygen test binaries are required")
    backup_directory = Path(__file__).resolve().parents[2] / "ops/backup"
    sys.path.insert(0, str(backup_directory))
    key_spec = importlib.util.spec_from_file_location("migration_rehearsal_key",
                                                       backup_directory / "make_key.py")
    key_tool = importlib.util.module_from_spec(key_spec)
    key_spec.loader.exec_module(key_tool)
    key = tmp_path / "synthetic-rehearsal.age-identity"
    key_tool.create(key, format="age", age_keygen=age_keygen)
    source = backup_tool.Postgres("agentflow_durable_fixture", "durable_fixture",
                                  "/var/run/postgresql", container=container)
    with tempfile.TemporaryDirectory(prefix="agentflow-migration-backup-") as work:
        work = Path(work)
        result = backup_tool.backup(source, key_file=key, spool=work / "spool",
                                    destination=work / "destination", encryption="age",
                                    age_binary=age_binary)
        encrypted = work / "destination" / result["artifact"]
        assert backup_tool.sha256(encrypted) == result["ciphertext_sha256"]
        archive = work / "pre-0006.dump"
        backup_tool.decrypt_archive(encrypted, archive, key, age_binary=age_binary)
        source.verify(archive)
        assert backup_tool.sha256(archive) == result["archive_sha256"]
        backup_integrity = True

        command.upgrade(migration_config(), "0006_durable_executions")
        original_create_index = op.create_index

        def inject_failure(name, *args, **kwargs):
            if name == "uq_custom_agents_owner_name_ci":
                raise RuntimeError("synthetic migration failure")
            return original_create_index(name, *args, **kwargs)
        with monkeypatch.context() as patcher:
            patcher.setattr(op, "create_index", inject_failure)
            with pytest.raises(RuntimeError, match="synthetic migration failure"):
                command.upgrade(migration_config(), "0007_accounts_ownership")
        with postgres.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0006_durable_executions"
        assert "users" not in inspect(postgres).get_table_names()
        assert "owner_id" not in {column["name"] for column in inspect(postgres).get_columns("tasks")}

        # The independently restored DB starts at the exact pre-migration 0005 archive.
        from tests.verify_durable_runtime import DOCKER
        restore_name = "agentflow_restore_rehearsal_" + os.urandom(6).hex()
        subprocess.run([DOCKER, "--context", "desktop-linux", "exec", container,
                        "createdb", "-U", "durable_fixture", restore_name],
                       check=True, capture_output=True, timeout=30)
        restored = backup_tool.Postgres(restore_name, "durable_fixture",
                                        "/var/run/postgresql", container=container)
        try:
            restored.restore(archive)
            restored_url = postgres.url.set(database=restore_name)
            restored_engine = create_engine(restored_url)
            try:
                assert content_snapshot(restored_engine) == before
                with restored_engine.connect() as connection:
                    restored_revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
                    restore_counts = {name: connection.scalar(text(f'SELECT count(*) FROM "{name}"'))
                                      for name in table_names}
                    assert restored_revision == "0005_custom_workflows"
                    assert restore_counts == before_counts
            finally:
                restored_engine.dispose()
        finally:
            subprocess.run([DOCKER, "--context", "desktop-linux", "exec", container,
                            "dropdb", "-U", "durable_fixture", restore_name],
                           check=True, capture_output=True, timeout=30)

        command.upgrade(migration_config(), "0007_accounts_ownership")
        assert content_snapshot(postgres) == before
        schema = inspect(postgres)
        assert {"users", "account_sessions", "account_audit", "login_buckets",
                "ownership_assignments", "durable_executions"}.issubset(
                    set(schema.get_table_names()))
        session_columns = {column["name"] for column in schema.get_columns("account_sessions")}
        assert {"digest", "user_id", "csrf_digest", "expires_at", "idle_expires_at",
                "revoked_at"}.issubset(session_columns)
        for table in legacy_ownership.ROOTS:
            owner = next(column for column in schema.get_columns(table)
                         if column["name"] == "owner_id")
            assert owner["nullable"] is True
            assert any(fk["referred_table"] == "users"
                       and fk["options"].get("ondelete") == "RESTRICT"
                       for fk in schema.get_foreign_keys(table))
        with postgres.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0007_accounts_ownership"
            assert connection.scalar(text("SELECT count(*) FROM users")) == 0
            assert connection.scalar(text("SELECT count(*) FROM account_sessions")) == 0
            assert connection.scalar(text("SELECT count(*) FROM durable_executions")) == 0
            after_counts = {name: connection.scalar(text(f'SELECT count(*) FROM "{name}"'))
                            for name in table_names}
            assert after_counts == before_counts
            for name in legacy_ownership.TABLES:
                if name in legacy_ownership.ROOTS:
                    assert connection.scalar(text(f'SELECT count(*) FROM "{name}" WHERE owner_id IS NOT NULL')) == 0
        assert verify_schema(postgres)["revision"] == "0007_accounts_ownership"

        from app import account_operator
        monkeypatch.setattr(account_operator.db, "engine", postgres)
        monkeypatch.setattr(account_operator, "password", lambda: "synthetic-operator-password")
        monkeypatch.setattr(sys, "argv", ["account_operator", "--expect-database",
            "agentflow_durable_fixture", "bootstrap", "--login", "rehearsal-admin",
            "--approval", "synthetic-operator-approval"])
        account_operator.main()
        captured = capsys.readouterr()
        assert "rehearsal-admin" not in captured.out  # only non-secret identifier is returned
        assert "synthetic-operator-password" not in captured.out + captured.err
        with postgres.connect() as connection:
            user = connection.execute(text("SELECT role, enabled, password_hash FROM users WHERE login='rehearsal-admin'")).one()
            assert user.role == "admin" and user.enabled is True
            assert "synthetic-operator-password" not in user.password_hash
            final_counts = {name: connection.scalar(text(f'SELECT count(*) FROM "{name}"'))
                            for name in table_names}
            final_users = connection.scalar(text("SELECT count(*) FROM users"))
            final_sessions = connection.scalar(text("SELECT count(*) FROM account_sessions"))
            final_journals = connection.scalar(text("SELECT count(*) FROM durable_executions"))

        evidence_path = os.environ.get("MIGRATION_REHEARSAL_EVIDENCE")
        if evidence_path:
            evidence = {
                "scope": "disposable-synthetic-postgresql-only",
                "postgres_major": 16,
                "source_revision": "0005_custom_workflows",
                "migration_sequence": ["0006_durable_executions", "0007_accounts_ownership"],
                "failed_0007_rolled_back_to": "0006_durable_executions",
                "restore_revision": restored_revision,
                "pre_migration_backup_integrity": backup_integrity,
                "pre_migration_archive_sha256": result["archive_sha256"],
                "encrypted_backup_ciphertext_sha256": result["ciphertext_sha256"],
                "pre_migration_record_counts": before_counts,
                "post_migration_record_counts": after_counts,
                "restored_record_counts": restore_counts,
                "legacy_records_unchanged": before == content_snapshot(postgres),
                "legacy_owner_ids_null_after_migration": True,
                "users_after_migration_before_provisioning": 0,
                "sessions_after_migration_before_login": 0,
                "durable_executions_after_migration": final_journals,
                "users_after_synthetic_admin_provisioning": final_users,
                "sessions_after_synthetic_admin_provisioning": final_sessions,
                "secure_bootstrap_password_logged": False,
                "production_accessed": False,
            }
            target = Path(evidence_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8") as stream:
                json.dump(evidence, stream, indent=2)


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
