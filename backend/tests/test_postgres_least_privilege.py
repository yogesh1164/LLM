"""Run ONLY in a fresh, no-network PostgreSQL16 container; no default DB fallback."""
import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker

from app import accounts
from app import database as db
from app import durable_execution as durable
from app.auth_foundation import Role
from app.config import settings
from app.ownership import current_principal
from tests.test_account_api import (
    test_two_users_durable_workflow_and_all_resource_boundaries as exercise_api,
)
from tests.test_durable_postgres import migration_config

spec = importlib.util.spec_from_file_location(
    "postgres_roles", Path(__file__).resolve().parents[2] / "deploy" / "postgres_roles.py")
roles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(roles)


def test_sql_generation_rejects_unreviewed_identifiers_and_tables():
    with pytest.raises(ValueError):
        roles.bootstrap_sql('db"; DROP DATABASE x; --')
    with pytest.raises(ValueError, match="Unreviewed"):
        roles.grants_sql(["unexpected_secret_table"])
    assert "NOLOGIN" in roles.bootstrap_sql("fixture")[0]


def test_cli_redacts_failures_and_rolls_back_real_transaction(monkeypatch, capsys, tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "roles.sqlite"))
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE evidence (value text)"))
    disposed = []

    class FaultingEngine:
        def begin(self):
            return engine.begin()

        def dispose(self):
            disposed.append(True)

    monkeypatch.setattr(roles, "create_engine", lambda _: FaultingEngine())
    monkeypatch.setenv("AGENTFLOW_OPERATOR_DATABASE_URL", "private-credential-canary")
    # Exercise SQLAlchemy's real transaction context before inventory validation fails.
    monkeypatch.setattr(roles, "INVENTORY", "INSERT INTO evidence VALUES ('synthetic') RETURNING value")
    assert roles.main(["bootstrap", "--expected-database", "fixture", "--apply"]) == 1
    output = capsys.readouterr()
    assert "private-credential-canary" not in output.out + output.err
    assert "Traceback" not in output.err and "success was not confirmed" in output.err
    assert disposed == [True]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM evidence")) == 0
    engine.dispose()


def test_cli_redacts_connection_exception(monkeypatch, capsys):
    def denied(_):
        raise RuntimeError("password=private-credential-canary database-url-secret")
    monkeypatch.setenv("AGENTFLOW_OPERATOR_DATABASE_URL", "private-credential-canary")
    monkeypatch.setattr(roles, "create_engine", denied)
    assert roles.main([]) == 1
    output = capsys.readouterr()
    assert "private-credential-canary" not in output.out + output.err
    assert "database-url-secret" not in output.out + output.err


@pytest.fixture
def separated(monkeypatch):
    raw = os.environ.get("LEAST_PRIVILEGE_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("Fresh isolated least-privilege PostgreSQL fixture URL not supplied")
    url = make_url(raw)
    assert url.host == "127.0.0.1" and url.database == "agentflow_privilege_fixture"
    assert url.username == "privilege_fixture"
    admin = create_engine(url)
    engines = {}
    with admin.begin() as connection:
        assert not inspect(connection).get_table_names(), "Fixture must be a new empty database"
        for statement in roles.bootstrap_sql(url.database):
            connection.execute(text(statement))
        # Synthetic credentials only, confined to a disposable network namespace.
        for role in ("agentflow_migrator", "agentflow_runtime", "agentflow_backup"):
            connection.execute(text(f"ALTER ROLE {role} LOGIN PASSWORD 'synthetic-fixture-only'"))
            engines[role] = create_engine(url.set(username=role, password="synthetic-fixture-only"))
    migrator = engines["agentflow_migrator"]
    monkeypatch.setattr(settings, "database_url", migrator.url.render_as_string(hide_password=False))
    command.upgrade(migration_config(), "0005_custom_workflows")
    command.upgrade(migration_config(), "0006_durable_executions")
    command.upgrade(migration_config(), "0007_accounts_ownership")
    command.upgrade(migration_config(), "head")
    with admin.begin() as connection:
        # Independent column privileges survive table-level REVOKE unless explicitly removed.
        connection.execute(text("GRANT UPDATE (role, enabled) ON public.users "
                                "TO PUBLIC, agentflow_runtime, agentflow_backup"))
        for statement in roles.grants_sql(inspect(connection).get_table_names()):
            connection.execute(text(statement))
    monkeypatch.setattr(settings, "auth_mode", "accounts")
    monkeypatch.setattr(settings, "durable_execution_enabled", True)
    monkeypatch.setattr(settings, "api_access_token", None)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(migrator, expire_on_commit=False))
    accounts.create_user("member-a", "synthetic-member-password", role=Role.ADMIN, bootstrap=True)
    accounts.create_user("member-b", "synthetic-member-password")
    runtime = engines["agentflow_runtime"]
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(runtime, expire_on_commit=False))
    try:
        yield admin, migrator, runtime, engines["agentflow_backup"]
    finally:
        for engine in engines.values():
            engine.dispose()
        admin.dispose()


def test_postgres_roles_api_journal_permissions_and_migrations(separated, monkeypatch):
    admin, migrator, runtime, backup = separated
    exercise_api(None, monkeypatch)
    token, _, principal = accounts.login("member-a", "synthetic-member-password")
    context = current_principal.set(principal)
    lease, _ = durable.reserve(str(uuid4()), "fixed_execute", {"task": "offline privilege test"})
    lease_context = durable.current_lease.set(lease)
    try:
        task = db.create_task("synthetic least privilege task")
        durable.renew()
        stage = db.start_stage(task, "Offline")
        db.finish_stage(stage, output="synthetic output", input_tokens=1, output_tokens=2)
        db.update_task(task, status="completed", result={"report": "synthetic"}, total_tokens=3)
        durable.finish()
        assert db.get_task(task)["total_tokens"] == 3
    finally:
        durable.current_lease.reset(lease_context)
        current_principal.reset(context)
    accounts.change_password(principal, "synthetic-member-password", "new-synthetic-member-password")
    with pytest.raises(HTTPException) as expired:
        accounts.authenticate(token)
    assert expired.value.status_code == 401
    # Each denied statement has its own transaction: no aborted transaction masks a failure.
    denied = [
        "CREATE TABLE public.forbidden (id integer)", "CREATE SCHEMA forbidden",
        "CREATE TEMP TABLE forbidden (id integer)", "DROP TABLE public.tasks",
        "ALTER TABLE public.tasks ADD COLUMN forbidden integer", "CREATE ROLE forbidden",
        "SET ROLE agentflow_migrator", "TRUNCATE public.tasks",
        "UPDATE public.users SET role='admin'", "UPDATE public.users SET enabled=false",
        "DELETE FROM public.account_audit", "DELETE FROM public.alembic_version",
        "INSERT INTO public.ownership_assignments VALUES ('x', NULL, 'x', now(), 0)",
        "ALTER TABLE public.tasks DISABLE TRIGGER ALL",
    ]
    for sql in denied:
        with pytest.raises(ProgrammingError), runtime.begin() as connection:
            connection.execute(text(sql))
    with runtime.connect() as connection:
        assert connection.scalar(text("SHOW search_path")) == "public, pg_temp"
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0007_accounts_ownership"
        assert not connection.scalar(text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')"))
        assert not connection.scalar(text("SELECT has_database_privilege(current_user, current_database(), 'TEMP')"))
    with backup.connect() as connection:
        for table in inspect(connection).get_table_names():
            connection.execute(text(f'SELECT * FROM public."{table}" LIMIT 1'))
    with pytest.raises(ProgrammingError), backup.begin() as connection:
        connection.execute(text("DELETE FROM public.tasks"))
    with pytest.raises(ProgrammingError), backup.begin() as connection:
        connection.execute(text("UPDATE public.users SET role='admin'"))
    with migrator.begin() as connection:
        connection.execute(text("CREATE TABLE public.future_review (id integer)"))
        connection.execute(text("CREATE SEQUENCE public.future_review_seq"))
    with backup.connect() as connection:
        connection.execute(text("SELECT * FROM public.future_review"))
        connection.execute(text("SELECT last_value FROM public.future_review_seq"))
    with pytest.raises(ProgrammingError), runtime.begin() as connection:
        connection.execute(text("SELECT * FROM public.future_review"))
    with migrator.begin() as connection:
        connection.execute(text("DROP TABLE public.future_review"))
        connection.execute(text("DROP SEQUENCE public.future_review_seq"))
    with admin.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM pg_roles WHERE rolname LIKE 'agentflow_%' "
                                      "AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)")) == 0
