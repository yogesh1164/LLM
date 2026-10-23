"""Inventory every registered API route: future routes cannot silently skip auth."""
import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import custom_agents, database, main
from app.config import settings
from app.provider_capacity import ProviderBusyError


def _routes():
    app = main.app
    while not hasattr(app, "routes"):
        app = app.app
    # Use FastAPI's expanded schema, including lazily included routers.
    return [(method.upper(), path) for path, operations in app.openapi()["paths"].items()
            if path not in {"/api/health", "/api/ready"}
            for method in operations if method in {"get", "post", "put", "patch", "delete"}]


@pytest.mark.parametrize("method,path", _routes())
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_all_sensitive_routes_require_authentication(method, path, headers):
    response = TestClient(main.app).request(method, path, headers=headers)
    assert response.status_code == 401


def _saved_agent():
    client = TestClient(main.app, headers={"Authorization": "Bearer " + "t" * 32})
    result = client.post("/api/agents", json={
        "name": "Offline cancellation test", "role": "test",
        "system_instructions": "Offline only", "provider": "gemini",
        "model": settings.gemini_model,
    })
    assert result.status_code == 201
    with database.SessionLocal() as session:
        return session.get(database.CustomAgent, UUID(result.json()["id"]))


def test_cancelled_custom_execution_is_persisted(monkeypatch):
    agent = _saved_agent()

    async def cancelled(**kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(custom_agents, "run_custom_gemini_agent", cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(custom_agents._execute_saved_agent(agent, "offline test task"))
    with database.SessionLocal() as session:
        execution = session.scalar(select(database.CustomAgentExecution))
        assert execution.status == "cancelled"
        assert execution.completed_at is not None
        assert execution.error == "Execution cancelled"


def test_saturated_custom_execution_returns_retryable_safe_error(monkeypatch):
    agent = _saved_agent()

    async def busy(**kwargs):
        raise ProviderBusyError("internal details should not escape")

    monkeypatch.setattr(custom_agents, "run_custom_gemini_agent", busy)
    response = TestClient(main.app, headers={"Authorization": "Bearer " + "t" * 32}).post(
        f"/api/agents/{agent.id}/execute", json={"task": "offline task"})
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert "internal details" not in response.text
    with database.SessionLocal() as session:
        assert session.scalar(select(database.CustomAgentExecution)).status == "failed"
