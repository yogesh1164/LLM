"""Offline, explicit whole-workspace ownership assignment with a stale-plan guard.

The manifest contains IDs, counts and hashes, never prompts or password hashes.
This is not an HTTP endpoint and does not enable account authorization.
"""
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import MetaData, Uuid, select, text, update

from app import accounts

ROOTS = ("tasks", "custom_agents", "custom_agent_executions", "custom_workflows",
         "custom_workflow_runs", "durable_executions")
CHILDREN = ("agent_executions", "custom_workflow_steps", "custom_workflow_step_runs")
TABLES = ROOTS + CHILDREN


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    default=str).encode()).hexdigest()


def _tables(connection):
    metadata = MetaData()
    metadata.reflect(connection, only=TABLES)
    # SQLite reflects Uuid as CHAR; retain portable UUID bind/result processing.
    for name in ROOTS:
        metadata.tables[name].c.owner_id.type = Uuid()
    return metadata.tables


def _rows(connection, tables):
    return {name: [dict(row) for row in connection.execute(
        select(tables[name]).order_by(tables[name].c.id)).mappings()] for name in TABLES}


def _check_relations(rows):
    indexes = {name: {str(row["id"]): row for row in values} for name, values in rows.items()}
    links = (("agent_executions", "task_id", "tasks"),
             ("custom_agent_executions", "agent_id", "custom_agents"),
             ("custom_workflow_steps", "workflow_id", "custom_workflows"),
             ("custom_workflow_steps", "agent_id", "custom_agents"),
             ("custom_workflow_runs", "workflow_id", "custom_workflows"),
             ("custom_workflow_step_runs", "run_id", "custom_workflow_runs"),
             ("durable_executions", "task_id", "tasks"),
             ("durable_executions", "agent_execution_id", "custom_agent_executions"),
             ("durable_executions", "workflow_run_id", "custom_workflow_runs"))
    for source, field, target in links:
        for row in rows[source]:
            identifier = row[field]
            if identifier is not None and str(identifier) not in indexes[target]:
                raise ValueError("Legacy data contains an orphan relationship")


def plan(connection, owner_id: UUID) -> dict:
    user = connection.execute(select(accounts.User.__table__).where(
        accounts.User.id == owner_id)).mappings().first()
    if not user or not user["enabled"] or user["role"] != "admin":
        raise ValueError("Select an existing enabled administrator explicitly")
    tables = _tables(connection)
    rows = _rows(connection, tables)
    _check_relations(rows)
    if any(row["owner_id"] is not None for name in ROOTS for row in rows[name]):
        raise ValueError("Whole-workspace assignment requires all legacy ownership to be null")
    if any(row["state"] == "running" for row in rows["durable_executions"]):
        raise ValueError("Drain and reconcile running journals before ownership assignment")
    if any(row.get("status") in {"running", "pending"} for name in ROOTS for row in rows[name]):
        raise ValueError("Reconcile unfinished legacy executions before ownership assignment")
    content = {name: {"count": len(rows[name]), "digest": _digest(rows[name]),
                     "ids": [str(row["id"]) for row in rows[name]]} for name in TABLES}
    payload = {"version": 1, "owner_id": str(owner_id), "owner_login": user["login"],
               "tables": content}
    return {**payload, "manifest_digest": _digest(payload)}


def apply(connection, manifest: dict, *, confirm_login: str, approved_by: str) -> int:
    """Caller owns one transaction. PostgreSQL locks prevent writes during validation.

    The caller must commit only on success. Repeat of an identical applied manifest
    verifies ownership before returning zero; a changed manifest never reassigns data.
    """
    if not connection.in_transaction():
        raise ValueError("Ownership assignment requires an explicit transaction")
    if not approved_by.strip() or len(approved_by) > 254:
        raise ValueError("An operator approval reference is required")
    owner = UUID(manifest["owner_id"])
    payload = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    if _digest(payload) != manifest["manifest_digest"]:
        raise ValueError("Manifest checksum mismatch")
    if confirm_login != manifest["owner_login"]:
        raise ValueError("Owner login confirmation does not match")
    if connection.dialect.name == "postgresql":
        # Static identifiers only. These locks end with the transaction.
        connection.execute(text("LOCK TABLE users, ownership_assignments, " +
                                ", ".join(TABLES) + " IN SHARE ROW EXCLUSIVE MODE"))
    tables = _tables(connection)
    audit = accounts.OwnershipAssignment.__table__
    existing = connection.execute(select(audit).where(
        audit.c.manifest_digest == manifest["manifest_digest"])).mappings().first()
    if existing:
        if existing["owner_id"] != owner:
            raise ValueError("Ownership audit disagrees with manifest")
        rows = _rows(connection, tables)
        for name in ROOTS:
            assigned = {str(row["id"]): row["owner_id"] for row in rows[name]}
            if any(assigned.get(identifier) != owner for identifier in manifest["tables"][name]["ids"]):
                raise ValueError("Previously assigned ownership has changed")
        return 0
    if plan(connection, owner) != manifest:
        raise ValueError("Legacy data changed after manifest review; create a new plan")
    count = 0
    for name in ROOTS:
        values = {"owner_id": owner}
        if name == "durable_executions":
            values["scope"] = str(owner)
        result = connection.execute(update(tables[name]).where(tables[name].c.owner_id.is_(None))
                                    .values(**values))
        if result.rowcount != manifest["tables"][name]["count"]:
            raise ValueError("Ownership row count mismatch; roll back transaction")
        count += result.rowcount
    connection.execute(audit.insert().values(manifest_digest=manifest["manifest_digest"],
        owner_id=owner, approved_by=approved_by.strip(), assigned_at=datetime.now(UTC), row_count=count))
    return count
