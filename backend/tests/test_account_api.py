"""Real API authentication/ownership with synthetic users and mocked providers."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import accounts, custom_workflows, durable_execution, main
from app import database as db
from app.auth_foundation import Role, token_digest
from app.config import settings
from app.providers import StageResult

PASSWORD = "synthetic-member-password"
ORIGIN = "http://localhost:3000"


@pytest.fixture
def account_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "accounts")
    monkeypatch.setattr(settings, "durable_execution_enabled", True)
    monkeypatch.setattr(settings, "api_access_token", None)
    accounts.create_user("member-a", PASSWORD, role=Role.ADMIN)
    accounts.create_user("member-b", PASSWORD)


def signed_in(name):
    client = TestClient(main.app, headers={"Origin": ORIGIN, "X-AgentFlow-Login": "1"})
    response = client.post("/api/auth/login", json={"login": name, "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


def agent(client, name="Private specialist"):
    response = client.post("/api/agents", json={"name": name, "role": "test",
        "system_instructions": "Offline only", "provider": "gemini", "model": settings.gemini_model})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_two_users_durable_workflow_and_all_resource_boundaries(account_mode, monkeypatch):
    calls = []
    async def provider(**kwargs):
        calls.append(kwargs["name"])
        return StageResult("private result", input_tokens=3, output_tokens=2)
    monkeypatch.setattr(custom_workflows, "run_custom_gemini_agent", provider)
    a, b = signed_in("member-a"), signed_in("member-b")
    aid = agent(a)
    assert agent(b) != aid  # Identical names are allowed for separate owners.
    response = a.post("/api/custom-workflows", json={"name": "Private workflow", "agent_ids": [aid]})
    assert response.status_code == 201, response.text
    wid = response.json()["id"]
    key = str(uuid4())
    first = a.post(f"/api/custom-workflows/{wid}/execute", json={"task": "Offline task"},
                   headers={"Idempotency-Key": key})
    assert first.status_code == 200, first.text
    rid = first.json()["id"]
    again = a.post(f"/api/custom-workflows/{wid}/execute", json={"task": "Offline task"},
                   headers={"Idempotency-Key": key})
    assert again.status_code == 202 and calls == ["Private specialist"]
    assert a.get(first.headers["location"]).json()["state"] == "completed"
    for path in (f"/api/agents/{aid}", f"/api/agents/{aid}/executions",
                 f"/api/custom-workflows/{wid}", f"/api/custom-workflows/{wid}/runs",
                 f"/api/custom-workflows/runs/{rid}", first.headers["location"]):
        assert b.get(path).status_code == 404, path
    assert b.delete(f"/api/agents/{aid}").status_code == 404
    assert b.patch(f"/api/agents/{aid}", json={"description": "stolen"}).status_code == 404
    assert b.post(f"/api/agents/{aid}/duplicate").status_code == 404
    assert b.delete(f"/api/custom-workflows/{wid}").status_code == 404
    assert b.get("/api/custom-workflows").json() == []
    assert b.post("/api/custom-workflows", json={"name": "spoof", "agent_ids": [aid]}).status_code == 422
    assert b.post(f"/api/custom-workflows/{wid}/execute", json={"task": "Offline task"},
                  headers={"Idempotency-Key": key}).status_code == 404
    # The same key in B's scope cannot return A's execution.
    assert calls == ["Private specialist"]
    # Administrator A is not a content superuser.
    bid = b.get("/api/agents").json()[0]["id"]
    assert a.get(f"/api/agents/{bid}").status_code == 404


def test_task_history_null_ownership_and_owner_spoofing(account_mode):
    a, b = signed_in("member-a"), signed_in("member-b")
    with db.SessionLocal.begin() as session:
        owner = session.scalar(select(accounts.User.id).where(accounts.User.login == "member-a"))
        task = db.Task(prompt="private report", result={"report": "private result"})
        orphan = db.Task(prompt="unassigned legacy")
        session.add_all([task, orphan]); session.flush()
        session.execute(db.Task.__table__.update().where(db.Task.id == task.id).values(owner_id=owner))
        tid, legacy_id = task.id, orphan.id
    assert a.get(f"/api/tasks/{tid}").status_code == 200
    assert b.get(f"/api/tasks/{tid}").status_code == 404
    assert b.delete(f"/api/tasks/{tid}").status_code == 404
    assert a.get(f"/api/tasks/{legacy_id}").status_code == 404
    assert b.get("/api/dashboard").json()["history"] == []
    assert len(a.get("/api/dashboard").json()["history"]) == 1
    response = b.post("/api/agents", json={"name": "spoof", "role": "test",
        "system_instructions": "offline", "provider": "gemini", "model": settings.gemini_model,
        "owner_id": str(owner)})
    assert response.status_code == 422


def test_session_endpoints_and_csrf(account_mode):
    a = signed_in("member-a")
    profile = a.get("/api/auth/me")
    assert profile.json()["login"] == "member-a"
    assert profile.json()["csrf_token"] == a.headers["X-CSRF-Token"]
    assert a.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert a.post("/api/auth/logout", headers={"Origin": "https://evil.invalid"}).status_code == 403
    assert a.post("/api/auth/logout").status_code == 204
    assert a.get("/api/auth/me").status_code == 401
    # A shared token cannot bypass account-mode authentication.
    assert TestClient(main.app).get("/api/agents", headers={"Authorization": "Bearer " + "t"*32}).status_code == 401


def test_password_change_ui_contract_and_expiration(account_mode):
    a, second = signed_in("member-a"), signed_in("member-a")
    response = a.post("/api/auth/password", json={"current_password": PASSWORD,
                                                  "new_password": "new-synthetic-password"})
    assert response.status_code == 204
    assert second.get("/api/auth/me").status_code == 401
    b = signed_in("member-b")
    with db.SessionLocal.begin() as session:
        token = b.cookies.get("agentflow_session_dev")
        session.get(accounts.AccountSession, token_digest(token)).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert b.get("/api/dashboard").status_code == 401


@pytest.mark.parametrize("production", [False, True])
def test_cookie_flags_and_no_credential_echo(account_mode, monkeypatch, production):
    monkeypatch.setattr(settings, "app_env", "production" if production else "development")
    client = TestClient(main.app, base_url="https://testserver" if production else "http://testserver")
    response = client.post("/api/auth/login", headers={"Origin": ORIGIN, "X-AgentFlow-Login": "1"},
                           json={"login": "member-a", "password": PASSWORD})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert ("secure" in cookie) == production
    assert "domain=" not in cookie
    response = client.post("/api/auth/login", json={"login": "member-a", "password": "secret" * 100})
    assert response.status_code == 422 and "secret" not in response.text


def test_recovery_preserves_owner_without_session(account_mode):
    a, b = signed_in("member-a"), signed_in("member-b")
    from app.ownership import current_principal
    principal = accounts.authenticate(a.cookies.get("agentflow_session_dev"))
    token = current_principal.set(principal)
    try:
        lease, _ = durable_execution.reserve(str(uuid4()), "fixed_execute", {"task": "offline"})
        lease_token = durable_execution.current_lease.set(lease)
        try:
            tid = db.create_task("offline recovery")
            sid = db.start_stage(tid, "Research")
            db.finish_stage(sid, output="private partial", input_tokens=3, output_tokens=2)
        finally:
            durable_execution.current_lease.reset(lease_token)
    finally:
        current_principal.reset(token)
    with db.SessionLocal.begin() as session:
        session.get(db.DurableExecution, lease.id).lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert durable_execution.recover_expired() == 1
    assert a.get(f"/api/tasks/{tid}").json()["result"]["research"] == "private partial"
    assert b.get(f"/api/tasks/{tid}").status_code == 404
    assert b.get(f"/api/executions/{lease.id}").status_code == 404


def test_legacy_startup_refuses_owned_database(account_mode):
    from app.ownership import reject_unsafe_legacy_mode
    agent(signed_in("member-a"))
    with pytest.raises(RuntimeError, match="bypass"):
        reject_unsafe_legacy_mode()


def test_readiness_requires_revision_and_admin(account_mode):
    from app.ownership import verify_account_readiness
    with db.SessionLocal.begin() as session:
        session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        session.execute(text("INSERT INTO alembic_version VALUES ('0006_durable_executions')"))
    with pytest.raises(RuntimeError, match="migrated"):
        verify_account_readiness()
    with db.SessionLocal.begin() as session:
        session.execute(text("UPDATE alembic_version SET version_num='0007_accounts_ownership'"))
    verify_account_readiness()
