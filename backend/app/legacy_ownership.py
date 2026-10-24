"""Offline, explicit whole-workspace ownership assignment with a stale-plan guard.

The manifest contains IDs, counts and hashes, never prompts or password hashes.
This is not an HTTP endpoint and does not enable account authorization.
"""
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import MetaData, Uuid, inspect, select, text, update

from app import accounts
from app import database as db

ROOTS = ("tasks", "custom_agents", "custom_agent_executions", "custom_workflows",
         "custom_workflow_runs", "durable_executions")
CHILDREN = ("agent_executions", "custom_workflow_steps", "custom_workflow_step_runs")
TABLES = ROOTS + CHILDREN
LINKS = (("agent_executions", "task_id", "tasks"),
         ("custom_agent_executions", "agent_id", "custom_agents"),
         ("custom_workflow_steps", "workflow_id", "custom_workflows"),
         ("custom_workflow_steps", "agent_id", "custom_agents"),
         ("custom_workflow_runs", "workflow_id", "custom_workflows"),
         ("custom_workflow_step_runs", "run_id", "custom_workflow_runs"),
         ("durable_executions", "task_id", "tasks"),
         ("durable_executions", "agent_execution_id", "custom_agent_executions"),
         ("durable_executions", "workflow_run_id", "custom_workflow_runs"))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    default=str).encode()).hexdigest()


def _tables(connection, names=TABLES):
    metadata = MetaData()
    metadata.reflect(connection, only=names)
    # SQLite reflects Uuid as CHAR; retain portable UUID bind/result processing.
    for name in names:
        for column in metadata.tables[name].c:
            model_column = db.Base.metadata.tables[name].c.get(column.name)
            if model_column is not None and isinstance(model_column.type, Uuid):
                column.type = model_column.type
        if name in ROOTS and "owner_id" in metadata.tables[name].c:
            metadata.tables[name].c.owner_id.type = Uuid()
    return metadata.tables


def _identifiers(table, values):
    return [UUID(value) if isinstance(table.c.id.type, Uuid) else value for value in values]


def _rows(connection, tables):
    return {name: [dict(row) for row in connection.execute(
        select(tables[name]).order_by(tables[name].c.id)).mappings()] for name in TABLES if name in tables}


def _check_relations(rows):
    indexes = {name: {str(row["id"]): row for row in values} for name, values in rows.items()}
    for source, field, target in LINKS:
        for row in rows.get(source, []):
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


def _identity(connection):
    if connection.dialect.name == "postgresql":
        database, schema = connection.execute(text("SELECT current_database(), current_schema() ")).one()
        return {"database": database, "schema": schema}
    return {"database": "sqlite-test-only", "schema": "main"}


def _normalized_row(name, row):
    # These are the only intended changes; journal scope must follow its owner.
    return {key: value for key, value in row.items()
            if key != "owner_id" and not (name == "durable_executions" and key == "scope")}


def _components(rows):
    """An agent referenced by several workflows binds them into one ownership unit."""
    by_key = {(name, str(row["id"])): row for name in TABLES for row in rows.get(name, [])}
    parents = {key: key for key in by_key}

    def root(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    for source, field, target in LINKS:
        for row in rows.get(source, []):
            if row[field] is not None:
                left, right = root((source, str(row["id"]))), root((target, str(row[field])))
                parents[left] = right
    grouped = {}
    for key in by_key:
        grouped.setdefault(root(key), []).append(key)
    result = []
    for keys in grouped.values():
        keys = sorted(keys)
        roots = [by_key[key] for key in keys if key[0] in ROOTS]
        owners = {str(row["owner_id"]) for row in roots if row["owner_id"] is not None}
        unassigned = sum(row["owner_id"] is None for row in roots)
        unfinished = any(row.get("status") in {"pending", "running"} or row.get("state") == "running"
                         for row in roots)
        state = ("conflicting_ownership" if len(owners) > 1 or (owners and unassigned) else
                 "already_owned" if owners else "unfinished" if unfinished else "unassigned")
        tables = {}
        for name in TABLES:
            members = [by_key[key] for key in keys if key[0] == name]
            if members:
                tables[name] = {"ids": [str(row["id"]) for row in members], "count": len(members),
                                "content_digest": _digest([_normalized_row(name, row) for row in members])}
        result.append({"component_id": _digest(keys), "state": state,
                       "owner_ids": sorted(owners), "tables": tables})
    return sorted(result, key=lambda item: item["component_id"])


def inventory(connection):
    """Read-only inventory: IDs/counts/digests and account choices, no content/secrets."""
    rows = _rows(connection, _tables(connection))
    _check_relations(rows)
    users = connection.execute(select(accounts.User.id, accounts.User.login,
                                      accounts.User.role, accounts.User.enabled).order_by(accounts.User.id)).mappings()
    payload = {"version": 2, "identity": _identity(connection),
               "accounts": [{**dict(user), "id": str(user["id"])} for user in users],
               "tables": {name: {"count": len(rows[name]), "digest": _digest(rows[name])} for name in TABLES},
               "components": _components(rows)}
    return {**payload, "inventory_digest": _digest(payload)}


def inventory_before_accounts(connection):
    """Read-only 0005/0006 inventory; owner=null is virtual, never a schema change."""
    revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    if revision not in {"0005_custom_workflows", "0006_durable_executions"}:
        raise ValueError("Pre-account inventory requires revision 0005 or 0006")
    actual = set(inspect(connection).get_table_names())
    expected = set(TABLES) - ({"durable_executions"} if revision == "0005_custom_workflows" else set())
    if not expected.issubset(actual) or "users" in actual:
        raise ValueError("Unexpected pre-account schema; inspect before planning")
    rows = _rows(connection, _tables(connection, names=tuple(name for name in TABLES if name in expected)))
    _check_relations(rows)
    if any("owner_id" in row for values in rows.values() for row in values):
        raise ValueError("Pre-account schema unexpectedly contains ownership")
    content = {name: {"count": len(values), "digest": _digest(values),
                      "ids": [str(row["id"]) for row in values]} for name, values in rows.items()}
    content["alembic_version"] = {"count": 1, "digest": _digest([{"version_num": revision}])}
    virtual = {name: [{**row, "owner_id": None} if name in ROOTS else row for row in values]
               for name, values in rows.items()}
    payload = {"version": 2, "phase": "before_accounts", "revision": revision,
               "identity": _identity(connection), "tables": content, "accounts": [],
               "components": _components(virtual), "mappings_available": False,
               "virtual_null_owners": True,
               "next_step": "After approved0007 upgrade and offline account provisioning, export a fresh inventory and obtain explicit mapping approval"}
    return {**payload, "inventory_digest": _digest(payload)}


def plan_mapping(connection, selection):
    """Map complete unowned components to explicitly confirmed enabled accounts."""
    current = inventory(connection)
    if set(selection) != {"inventory_digest", "mappings", "unmapped"} or selection["unmapped"] != "quarantine":
        raise ValueError("An explicit mapping and unmapped=quarantine decision are required")
    if selection["inventory_digest"] != current["inventory_digest"]:
        raise ValueError("Inventory changed; export and review a fresh inventory")
    if not isinstance(selection["mappings"], list) or not selection["mappings"]:
        raise ValueError("Select at least one component explicitly")
    components = {item["component_id"]: item for item in current["components"]}
    users = {item["id"]: item for item in current["accounts"]}
    planned, seen, journal_owners = [], set(), {}
    for mapping in selection["mappings"]:
        if set(mapping) != {"component_id", "owner_id", "confirm_login"}:
            raise ValueError("Mapping fields must be explicit and complete")
        component_id = mapping["component_id"]
        if component_id in seen:
            raise ValueError("Duplicate component mapping")
        seen.add(component_id)
        component = components.get(component_id)
        user = users.get(mapping["owner_id"])
        if not component or component["state"] != "unassigned":
            raise ValueError("Select only complete, finished, unassigned components")
        if not user or not user["enabled"] or mapping["confirm_login"] != user["login"]:
            raise ValueError("Confirm an existing enabled account by ID and exact login")
        UUID(user["id"])
        planned.append({**mapping, "tables": component["tables"]})
        journal_owners.update({identifier: user["id"] for identifier in component["tables"].get(
            "durable_executions", {}).get("ids", [])})
    # Re-scoping old keys must never collide with an existing key for the chosen user.
    keys = set()
    for row in _rows(connection, _tables(connection))["durable_executions"]:
        pair = (journal_owners.get(str(row["id"]), row["scope"]), row["key_digest"])
        if pair in keys:
            raise ValueError("Mapped execution keys collide; reconcile without replay before assignment")
        keys.add(pair)
    payload = {"version": 2, "identity": current["identity"],
               "inventory_digest": current["inventory_digest"], "unmapped": "quarantine",
               "mappings": sorted(planned, key=lambda item: item["component_id"])}
    return {**payload, "manifest_digest": _digest(payload)}


def _mapping_audit_digest(manifest, mapping):
    return _digest({"manifest_digest": manifest["manifest_digest"],
                    "component_id": mapping["component_id"], "owner_id": mapping["owner_id"]})


def verify_mapping(connection, manifest):
    """Read-only post-apply/replay check of every approved row, owner and journal scope."""
    payload = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    if (manifest.get("version") != 2 or not manifest.get("mappings")
            or _digest(payload) != manifest["manifest_digest"]):
        raise ValueError("Manifest checksum/version mismatch")
    if _identity(connection) != manifest["identity"]:
        raise ValueError("Manifest database/schema identity mismatch")
    tables, count = _tables(connection), 0
    audit = accounts.OwnershipAssignment.__table__
    for mapping in manifest["mappings"]:
        owner = UUID(mapping["owner_id"])
        event = connection.execute(select(audit).where(audit.c.manifest_digest ==
            _mapping_audit_digest(manifest, mapping))).mappings().first()
        expected_count = sum(value["count"] for name, value in mapping["tables"].items() if name in ROOTS)
        if not event or event["owner_id"] != owner or event["row_count"] != expected_count:
            raise ValueError("Mapping approval audit missing or inconsistent")
        for name, expected in mapping["tables"].items():
            rows = [dict(row) for row in connection.execute(select(tables[name]).where(
                tables[name].c.id.in_(_identifiers(tables[name], expected["ids"]))).order_by(tables[name].c.id)).mappings()]
            if len(rows) != expected["count"] or _digest([_normalized_row(name, row) for row in rows]) != expected["content_digest"]:
                raise ValueError("Previously assigned record content changed or disappeared")
            if name in ROOTS and any(row["owner_id"] != owner for row in rows):
                raise ValueError("Previously assigned ownership changed")
            if name == "durable_executions" and any(row["scope"] != str(owner) for row in rows):
                raise ValueError("Journal ownership scope disagrees with approved mapping")
        count += expected_count
    return {"verified": True, "mapped_components": len(manifest["mappings"]), "assigned_roots": count}


def apply_mapping(connection, manifest, *, confirm_digest, approved_by):
    """Explicit caller transaction; row locks, stale snapshot, repeat and content guards."""
    if not connection.in_transaction():
        raise ValueError("Ownership assignment requires an explicit transaction")
    if not approved_by.strip() or len(approved_by) > 254:
        raise ValueError("An operator approval reference is required")
    payload = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    if manifest.get("version") != 2 or _digest(payload) != manifest.get("manifest_digest"):
        raise ValueError("Manifest checksum/version mismatch")
    if confirm_digest != manifest["manifest_digest"] or _identity(connection) != manifest["identity"]:
        raise ValueError("Confirm the exact approved manifest digest and database/schema identity")
    if connection.dialect.name == "postgresql":
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(text("LOCK TABLE users, ownership_assignments, " +
                                ", ".join(TABLES) + " IN SHARE ROW EXCLUSIVE MODE"))
    audit = accounts.OwnershipAssignment.__table__
    existing = [connection.execute(select(audit.c.manifest_digest).where(
        audit.c.manifest_digest == _mapping_audit_digest(manifest, mapping))).scalar_one_or_none()
        for mapping in manifest["mappings"]]
    if any(existing):
        if not all(existing):
            raise ValueError("Incomplete prior mapping audit; investigate before any further assignment")
        verify_mapping(connection, manifest)
        return 0
    selection = {"inventory_digest": manifest["inventory_digest"], "unmapped": "quarantine",
                 "mappings": [{key: item[key] for key in ("component_id", "owner_id", "confirm_login")}
                              for item in manifest["mappings"]]}
    if plan_mapping(connection, selection) != manifest:
        raise ValueError("Mapping changed after approval; export a fresh plan")
    tables, count = _tables(connection), 0
    for mapping in manifest["mappings"]:
        owner, assigned = UUID(mapping["owner_id"]), 0
        for name, expected in mapping["tables"].items():
            if name not in ROOTS:
                continue
            values = {"owner_id": owner}
            if name == "durable_executions":
                values["scope"] = str(owner)
            changed = connection.execute(update(tables[name]).where(tables[name].c.id.in_(
                _identifiers(tables[name], expected["ids"])), tables[name].c.owner_id.is_(None)).values(**values)).rowcount
            if changed != expected["count"]:
                raise ValueError("Ownership row count mismatch; roll back")
            assigned += changed
        connection.execute(audit.insert().values(manifest_digest=_mapping_audit_digest(manifest, mapping),
            owner_id=owner, approved_by=approved_by.strip(), assigned_at=datetime.now(UTC), row_count=assigned))
        count += assigned
    verify_mapping(connection, manifest)
    return count
