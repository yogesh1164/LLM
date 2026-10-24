"""Explicit query scoping and creation attribution for account-mode requests."""
from contextvars import ContextVar

from fastapi import HTTPException
from sqlalchemy import Column, ForeignKey, Index, Uuid, inspect, select, text, update

from app import accounts  # noqa: F401 - register FK target metadata before adding columns
from app import database as db
from app.auth_foundation import Principal
from app.config import settings

current_principal: ContextVar[Principal | None] = ContextVar("account_principal", default=None)
ROOT_MODELS = (db.Task, db.CustomAgent, db.CustomAgentExecution, db.CustomWorkflow,
               db.CustomWorkflowRun, db.DurableExecution)

# Unmapped columns keep legacy ORM reads/inserts compatible with 0005/0006.
# Account-mode operations reference these only after an explicit schema migration.
for model in ROOT_MODELS:
    if "owner_id" not in model.__table__.c:
        model.__table__.append_column(Column("owner_id", Uuid(),
            ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True))

agent_table = db.CustomAgent.__table__
for index in list(agent_table.indexes):
    if index.name == "uq_custom_agents_name_ci":
        agent_table.indexes.remove(index)
Index("uq_custom_agents_owner_name_ci", agent_table.c.owner_id, text("lower(name)"), unique=True)
Index("uq_custom_agents_legacy_name_ci", text("lower(name)"), unique=True,
      postgresql_where=agent_table.c.owner_id.is_(None), sqlite_where=agent_table.c.owner_id.is_(None),
      _table=agent_table)


def owner_id():
    principal = current_principal.get()
    if not principal or not principal.enabled:
        raise HTTPException(401, "Authentication required")
    return principal.user_id


def scoped(query, model):
    if settings.auth_mode == "accounts":
        return query.where(model.__table__.c.owner_id == owner_id())
    return query


def get_owned(session, model, identifier):
    return session.scalar(scoped(select(model).where(model.id == identifier), model))


def claim(session, model, identifier):
    if settings.auth_mode == "accounts":
        result = session.execute(update(model.__table__).where(model.id == identifier,
            model.__table__.c.owner_id.is_(None)).values(owner_id=owner_id()))
        if result.rowcount != 1:
            raise RuntimeError("New resource ownership could not be recorded")


def verify_account_readiness():
    from app.accounts import AccountSession, User
    with db.SessionLocal() as session:
        if settings.app_env == "production" and session.bind.dialect.name != "postgresql":
            raise RuntimeError("Production account mode requires PostgreSQL")
        if session.scalar(text("SELECT version_num FROM alembic_version")) != "0007_accounts_ownership":
            raise RuntimeError("Account schema has not been migrated")
        session.execute(select(AccountSession).limit(0))
        if session.scalar(select(User.id).where(User.role == "admin", User.enabled.is_(True)).limit(1)) is None:
            raise RuntimeError("Bootstrap an administrator before enabling account mode")
        for model in ROOT_MODELS:
            session.execute(select(model.__table__.c.owner_id).limit(0))
        relationships = (
            ("custom_agent_executions", "agent_id", "custom_agents"),
            ("custom_workflow_runs", "workflow_id", "custom_workflows"),
            ("durable_executions", "task_id", "tasks"),
            ("durable_executions", "agent_execution_id", "custom_agent_executions"),
            ("durable_executions", "workflow_run_id", "custom_workflow_runs"),
        )
        for child, foreign_key, parent in relationships:
            # Only these static identifiers are used; no request input reaches SQL.
            mismatch = session.scalar(text(f"SELECT count(*) FROM {child} c JOIN {parent} p "
                f"ON c.{foreign_key} = p.id WHERE c.owner_id IS NOT NULL "
                "AND (p.owner_id IS NULL OR c.owner_id <> p.owner_id)"))
            if mismatch:
                raise RuntimeError("Resource ownership relationships are inconsistent")
        mismatch = session.scalar(text("SELECT count(*) FROM custom_workflow_steps s "
            "JOIN custom_workflows w ON w.id=s.workflow_id JOIN custom_agents a ON a.id=s.agent_id "
            "WHERE w.owner_id IS NOT NULL AND (a.owner_id IS NULL OR a.owner_id <> w.owner_id)"))
        if mismatch:
            raise RuntimeError("Workflow references cross ownership boundaries")
        for owner, scope in session.execute(select(db.DurableExecution.__table__.c.owner_id,
                db.DurableExecution.scope).where(db.DurableExecution.__table__.c.owner_id.is_not(None))):
            if str(owner) != scope:
                raise RuntimeError("Journal owner and idempotency scope disagree")
        # Null legacy ownership is deliberately quarantined by scoped queries.


def reject_unsafe_legacy_mode():
    with db.SessionLocal() as session:
        inspector = inspect(session.connection())
        if "users" not in inspector.get_table_names():
            return
        for model in ROOT_MODELS:
            if session.scalar(select(model.id).where(model.__table__.c.owner_id.is_not(None)).limit(1)):
                raise RuntimeError("Owned content exists; legacy bearer mode would bypass account isolation")
