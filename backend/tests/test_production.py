"""Production boundary tests; database fixtures remain isolated SQLite."""

import asyncio
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import database, main, workflow
from app.config import Settings
from app.providers import ProviderRequestError


def production_settings(**overrides):
    values = {"app_env": "production", "api_access_token": "t" * 32,
              "gemini_api_key": "test-provider-key", "ai_provider": "gemini",
              "frontend_origins": "https://localhost:8443", "frontend_origin": None}
    return Settings(_env_file=None, **(values | overrides))


@pytest.mark.parametrize("origin", [
    "*", "https://*.example.com", "https://example.com/path", "https://example.com/",
    "https://user:password@example.com", "https://example.com?x=1", "not-an-origin",
    "http://localhost:3000", "https://example.com:bad", "",
])
def test_production_rejects_invalid_cors(origin):
    with pytest.raises(ValidationError):
        production_settings(frontend_origins=origin)


@pytest.mark.parametrize("overrides", [
    {"api_access_token": None}, {"api_access_token": "short"}, {"gemini_api_key": None},
])
def test_production_requires_credentials(overrides):
    with pytest.raises(ValidationError):
        production_settings(**overrides)


def test_production_accepts_explicit_https_and_hides_database_url():
    config = production_settings(database_url="postgresql://user:private-password@db/app")
    assert config.allowed_frontend_origins == ["https://localhost:8443"]
    assert "private-password" not in repr(config)


def test_production_disables_documentation_at_application_level():
    env = os.environ | {
        "APP_ENV": "production", "API_ACCESS_TOKEN": "t" * 32,
        "GEMINI_API_KEY": "test-key", "AI_PROVIDER": "gemini",
        "FRONTEND_ORIGINS": "https://localhost:8443", "FRONTEND_ORIGIN": "",
        "DATABASE_URL": "sqlite://",
    }
    code = (
        "from app.main import app; from fastapi.testclient import TestClient; "
        "c=TestClient(app); "
        "assert all(c.get(p).status_code == 404 for p in "
        "('/docs', '/redoc', '/openapi.json')); "
        "assert c.get('/api/health').status_code == 200; "
        "assert c.get('/api/dashboard').status_code == 401"
    )
    subprocess.run([sys.executable, "-c", code], env=env, check=True, capture_output=True)


def test_production_database_errors_do_not_reach_response_or_logs(monkeypatch, caplog):
    monkeypatch.setattr(main.settings, "app_env", "production")

    def fail():
        raise RuntimeError("postgresql://user:private-password@db/app")

    monkeypatch.setattr(main, "dashboard_data", fail)
    response = TestClient(main.app, headers={"Authorization": "Bearer " + "t" * 32}).get(
        "/api/dashboard")
    assert response.status_code == 500
    assert "private-password" not in response.text + caplog.text


def test_production_provider_diagnostics_are_not_public(monkeypatch):
    monkeypatch.setattr(main.settings, "app_env", "production")
    status, message = main._safe_provider_error(
        ProviderRequestError(503, "private-key database-password"))
    assert status == 503
    assert "private-key" not in message
    assert "database-password" not in message


def test_production_stage_failures_are_safe_in_storage_and_sse(monkeypatch):
    monkeypatch.setattr(workflow.settings, "app_env", "production")
    monkeypatch.setattr(workflow, "build_agents", lambda: {"orchestrator": "orchestrator"})
    secret = "provider-key-and-database-credentials"

    async def fail(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(workflow, "run_agent_stage", fail)
    task_id = database.create_task("production failure test")
    events = []

    async def progress(event):
        events.append(event)

    with pytest.raises(RuntimeError):
        asyncio.run(workflow.run_workflow("test", task_id, progress))
    assert secret not in str(events)
    assert secret not in str(database.get_task(task_id))
