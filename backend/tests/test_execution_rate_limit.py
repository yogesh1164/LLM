"""Offline HTTP rate-limiting regression tests."""

import importlib

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr


@pytest.mark.parametrize("path", [
    "/api/agents/not-a-valid-id/execute",
    "/api/custom-workflows/not-a-valid-id/execute",
])
def test_custom_execution_rate_limit_and_auth(monkeypatch, path):
    main = importlib.import_module("app.main")

    monkeypatch.setattr(
        main.settings, "api_access_token", SecretStr("t" * 32)
    )
    monkeypatch.setattr(
        main.settings, "rate_limit_per_minute", 1
    )

    client = TestClient(main.app)

    # Unauthorized requests must not consume execution quota.
    unauthorized = client.post(
        path, json={"task": "offline test"}
    )
    assert unauthorized.status_code == 401

    headers = {"Authorization": "Bearer " + "t" * 32}

    # The first authorized request is allowed through the limiter.
    first = client.post(
        path, json={"task": "offline test"}, headers=headers
    )
    assert first.status_code != 429

    # The second authorized request must be rate-limited.
    second = client.post(
        path, json={"task": "offline test"}, headers=headers
    )
    assert second.status_code == 429
    assert "Too many" in second.json()["detail"]
