"""Explicit multi-account legacy component mappings; no configured database access."""
import copy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app import accounts
from app import database as db
from app import legacy_ownership as ownership
from app.auth_foundation import Role
from app.config import settings
from tests.test_account_api import signed_in
from tests.test_durable_postgres import legacy_history


def seed_mapping_data():
    legacy_history()
    owner_a = accounts.create_user("mapped-admin", "synthetic-member-password", role=Role.ADMIN)
    owner_b = accounts.create_user("mapped-member", "synthetic-member-password")
    accounts.create_user("other-member", "synthetic-member-password")
    with db.SessionLocal.begin() as session:
        task = db.Task(prompt="map selected task", status="completed")
        quarantine = db.Task(prompt="leave this quarantined", status="completed")
        session.add_all([task, quarantine]); session.flush()
        now = datetime.now(UTC)
        journal = db.DurableExecution(id=str(uuid4()), scope="legacy-unassigned", operation="fixed_execute",
            key_digest="1" * 64, request_digest="2" * 64, state="completed", lease_token=str(uuid4()),
            lease_expires_at=now, heartbeat_at=now, created_at=now, provider_started=False, task_id=task.id)
        session.add(journal)
        task_id, quarantine_id, journal_id = task.id, quarantine.id, journal.id
    engine = db.SessionLocal.kw["bind"]
    with engine.connect() as connection:
        inventory = ownership.inventory(connection)
        mappings = []
        for component in inventory["components"]:
            names = component["tables"]
            if task_id in names.get("tasks", {}).get("ids", []):
                mappings.append({"component_id": component["component_id"], "owner_id": str(owner_a), "confirm_login": "mapped-admin"})
            elif "custom_agents" in names:
                mappings.append({"component_id": component["component_id"], "owner_id": str(owner_b), "confirm_login": "mapped-member"})
        selection = {"inventory_digest": inventory["inventory_digest"], "unmapped": "quarantine", "mappings": mappings}
        manifest = ownership.plan_mapping(connection, selection)
    return engine, inventory, selection, manifest, task_id, quarantine_id, journal_id


def normalized_snapshot(engine):
    with engine.connect() as connection:
        rows = ownership._rows(connection, ownership._tables(connection))
        return {name: [ownership._normalized_row(name, row) for row in rows[name]] for name in ownership.TABLES}


def exercise_mapping(monkeypatch):
    engine, inventory, _, manifest, task_id, quarantine_id, journal_id = seed_mapping_data()
    before = normalized_snapshot(engine)
    assert "map selected task" not in str(inventory) and "password_hash" not in str(inventory)
    assert len(manifest["mappings"]) == 2
    with engine.begin() as connection:
        assert ownership.apply_mapping(connection, manifest, confirm_digest=manifest["manifest_digest"], approved_by="synthetic-mapping-approval") == 6
    with engine.begin() as connection:
        assert ownership.apply_mapping(connection, manifest, confirm_digest=manifest["manifest_digest"], approved_by="synthetic-mapping-approval") == 0
        assert ownership.verify_mapping(connection, manifest)["assigned_roots"] == 6
        assert connection.scalar(select(text("count(*)")).select_from(accounts.OwnershipAssignment)) == 2
    assert normalized_snapshot(engine) == before
    monkeypatch.setattr(settings, "auth_mode", "accounts")
    monkeypatch.setattr(settings, "durable_execution_enabled", True)
    monkeypatch.setattr(settings, "api_access_token", None)
    a, b, other = signed_in("mapped-admin"), signed_in("mapped-member"), signed_in("other-member")
    assert a.get(f"/api/tasks/{task_id}").status_code == 200
    assert b.get(f"/api/tasks/{task_id}").status_code == 404
    assert other.get(f"/api/tasks/{task_id}").status_code == 404
    for client in (a, b, other):
        assert client.get(f"/api/tasks/{quarantine_id}").status_code == 404
    assert a.get(f"/api/executions/{journal_id}").status_code == 200
    assert b.get(f"/api/executions/{journal_id}").status_code == 404
    assert other.get("/api/agents").json() == []
    assert a.get("/api/agents").json() == []
    assert len(b.get("/api/agents").json()) == 1


def test_explicit_mapping_preserves_content_quarantine_and_owner_boundaries(monkeypatch):
    exercise_mapping(monkeypatch)


@pytest.mark.parametrize("failure", ["duplicate", "wrong-login", "disabled", "stale", "wrong-digest", "rollback", "tampered"])
def test_mapping_failures_never_partially_assign(failure):
    engine, _, selection, manifest, _, _, _ = seed_mapping_data()
    if failure in {"duplicate", "wrong-login", "disabled"}:
        if failure == "duplicate":
            selection["mappings"].append(copy.deepcopy(selection["mappings"][0]))
        elif failure == "wrong-login":
            selection["mappings"][0]["confirm_login"] = "other-member"
        else:
            with engine.begin() as connection:
                connection.execute(text("UPDATE users SET enabled=false WHERE login='mapped-member'"))
        with engine.connect() as connection, pytest.raises(ValueError):
            ownership.plan_mapping(connection, selection)
    else:
        if failure == "stale":
            with engine.begin() as connection:
                connection.execute(text("UPDATE tasks SET prompt='changed after review'"))
        if failure == "tampered":
            manifest["mappings"][0]["owner_id"] = str(uuid4())
        with pytest.raises((ValueError, RuntimeError)), engine.begin() as connection:
            ownership.apply_mapping(connection, manifest, confirm_digest="wrong" if failure == "wrong-digest" else manifest["manifest_digest"], approved_by="synthetic-approval")
            if failure == "rollback":
                raise RuntimeError("rollback injected after updates")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM tasks WHERE owner_id IS NOT NULL")) == 0
        assert connection.scalar(text("SELECT count(*) FROM ownership_assignments")) == 0


def test_replay_detects_content_or_scope_tampering():
    engine, _, _, manifest, _, _, journal_id = seed_mapping_data()
    with engine.begin() as connection:
        ownership.apply_mapping(connection, manifest, confirm_digest=manifest["manifest_digest"], approved_by="synthetic-approval")
        connection.execute(text("UPDATE durable_executions SET scope='wrong-owner' WHERE id=:identifier"), {"identifier": journal_id})
    with engine.connect() as connection, pytest.raises(ValueError, match="scope"):
        ownership.verify_mapping(connection, manifest)


def test_operator_mapping_cli_requires_identity_digest_and_approval():
    from app.account_operator import parser
    with pytest.raises(SystemExit):
        parser().parse_args(["apply-mapping", "--manifest", "synthetic.json"])
    with pytest.raises(SystemExit):
        parser().parse_args(["--expect-database", "synthetic", "apply-mapping", "--manifest", "synthetic.json", "--approval", "approval"])


@pytest.mark.parametrize("failure", ["unfinished", "mixed-owner", "journal-collision", "partial-component"])
def test_component_boundaries_and_key_collisions_are_not_bypassed(failure):
    engine, _, selection, manifest, task_id, quarantine_id, _ = seed_mapping_data()
    if failure == "partial-component":
        item = next(item for item in manifest["mappings"] if "custom_agents" in item["tables"])
        del item["tables"]["custom_agents"]
        manifest["manifest_digest"] = ownership._digest({k: v for k, v in manifest.items() if k != "manifest_digest"})
        with engine.begin() as connection, pytest.raises(ValueError):
            ownership.apply_mapping(connection, manifest, confirm_digest=manifest["manifest_digest"], approved_by="synthetic-approval")
        return
    with db.SessionLocal.begin() as session:
        if failure == "unfinished":
            session.get(db.Task, task_id).status = "running"
        elif failure == "mixed-owner":
            owner = session.scalar(select(accounts.User.id).where(accounts.User.login == "mapped-member"))
            session.execute(db.CustomAgent.__table__.update().values(owner_id=owner))
        else:
            now = datetime.now(UTC)
            session.add(db.DurableExecution(id=str(uuid4()), scope="different-legacy-scope", operation="fixed_execute",
                key_digest="1" * 64, request_digest="2" * 64, state="completed", lease_token=str(uuid4()),
                lease_expires_at=now, heartbeat_at=now, created_at=now, provider_started=False, task_id=quarantine_id))
    with engine.connect() as connection:
        updated = ownership.inventory(connection)
        selection["inventory_digest"] = updated["inventory_digest"]
        if failure == "journal-collision":
            selected = next(item for item in selection["mappings"] if item["confirm_login"] == "mapped-admin")
            selection["mappings"].append({**selected, "component_id": next(item["component_id"] for item in updated["components"]
                if quarantine_id in item["tables"].get("tasks", {}).get("ids", []))})
        with pytest.raises(ValueError):
            ownership.plan_mapping(connection, selection)


def test_verify_rejects_empty_self_checksummed_manifest():
    engine, _, _, manifest, _, _, _ = seed_mapping_data()
    manifest["mappings"] = []
    manifest["manifest_digest"] = ownership._digest({k: v for k, v in manifest.items() if k != "manifest_digest"})
    with engine.connect() as connection, pytest.raises(ValueError):
        ownership.verify_mapping(connection, manifest)
