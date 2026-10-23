import json
import logging
from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app
from app.observability import SafeJSONFormatter, request_id


def test_raw_content_credentials_exceptions_and_extra_are_omitted():
    secret = "offline-sensitive-content"
    record = logging.LogRecord("sdk", logging.ERROR, "", 0, "Bearer %s", (secret,),
                               (ValueError, ValueError(secret), None))
    record.prompt = secret
    record.headers = {"Authorization": secret}
    record.request_id = secret
    record.execution_id = secret
    rendered = SafeJSONFormatter().format(record)
    assert secret not in rendered and "Bearer" not in rendered
    assert json.loads(rendered)["event"] == "application_log"


def test_request_ids_are_generated_cache_disabled_and_logs_omit_query(caplog):
    caplog.set_level(logging.INFO, logger="agentflow.telemetry")
    secret = "offline-sensitive-query"
    client = TestClient(app)
    response = client.get("/api/health?token=" + secret, headers={"X-Request-ID": secret})
    assert response.status_code == 200
    UUID(response.headers["x-request-id"])
    assert response.headers["cache-control"] == "no-store"
    records = [r for r in caplog.records if r.name == "agentflow.telemetry"]
    data = json.loads(SafeJSONFormatter().format(records[-1]))
    # Context is reset after the request; records should retain request correlation.
    assert data["request_id"] == response.headers["x-request-id"]
    assert data["route"] == "/api/health" and data["status"] == 200
    assert secret not in SafeJSONFormatter().format(records[-1])
    assert request_id.get() is None


def test_auth_rejection_has_correlation_without_logging_token(caplog):
    caplog.set_level(logging.INFO, logger="agentflow.telemetry")
    response = TestClient(app).get("/api/dashboard", headers={"Authorization": "Bearer fake"})
    assert response.status_code == 401 and response.headers["x-request-id"]
    record = next(r for r in caplog.records if r.name == "agentflow.telemetry")
    data = json.loads(SafeJSONFormatter().format(record))
    assert data["category"] == "authentication_or_authorization"
    assert "fake" not in SafeJSONFormatter().format(record)
