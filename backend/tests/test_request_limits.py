import asyncio

import pytest
from fastapi.testclient import TestClient

from app import database, main
from app.config import settings
from app.request_limits import RequestBodyLimit


def _exchange(chunks, headers=(), limit=8, path="/api/test"):
    dispatched = []
    responses = []
    incoming = iter(chunks)

    async def receive():
        return next(incoming)

    async def send(message):
        responses.append(message)

    async def endpoint(scope, receive, send):
        dispatched.append(await receive())

    asyncio.run(RequestBodyLimit(endpoint, lambda: limit)(
        {"type": "http", "path": path, "headers": headers}, receive, send))
    return dispatched, responses


@pytest.mark.parametrize("headers", [[], [(b"content-length", b"1")]])
def test_chunked_or_underreported_body_cannot_reach_endpoint(headers):
    dispatched, responses = _exchange([
        {"type": "http.request", "body": b"12345", "more_body": True},
        {"type": "http.request", "body": b"6789", "more_body": True},
    ], headers)
    assert not dispatched
    assert responses[0]["status"] == 413


@pytest.mark.parametrize("length", [b"9", b"9" * 5000])
def test_oversize_declared_length_rejected_without_reading_body(length):
    dispatched, responses = _exchange([], [(b"content-length", length)])
    assert not dispatched
    assert responses[0]["status"] == 413


@pytest.mark.parametrize("headers", [
    [(b"content-length", b"-1")], [(b"content-length", b"+1")],
    [(b"content-length", b"abc")], [(b"content-length", b"")],
    [(b"content-length", b"1"), (b"Content-Length", b"2")],
])
def test_invalid_framing_rejected(headers):
    dispatched, responses = _exchange([], headers)
    assert not dispatched
    assert responses[0]["status"] == 400


def test_exact_limit_replays_complete_body_once():
    dispatched, responses = _exchange([
        {"type": "http.request", "body": b"1234", "more_body": True},
        {"type": "http.request", "body": b"5678", "more_body": False},
    ], [(b"content-length", b"0008")])
    assert dispatched == [{"type": "http.request", "body": b"12345678", "more_body": False}]
    assert not responses


def test_disconnect_before_complete_body_does_not_dispatch():
    dispatched, responses = _exchange([
        {"type": "http.request", "body": b"1234", "more_body": True},
        {"type": "http.disconnect"},
    ])
    assert not dispatched and not responses


def test_oversize_api_body_has_cors_telemetry_and_no_database_side_effect(monkeypatch):
    monkeypatch.setattr(settings, "max_request_body_bytes", 1024)
    response = TestClient(main.app).post("/api/workflows/execute", content=b"x" * 1025, headers={
        "Authorization": "Bearer " + "t" * 32,
        "Origin": settings.allowed_frontend_origins[0],
        "Content-Type": "application/json",
    })
    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == settings.allowed_frontend_origins[0]
    assert response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"
    assert database.dashboard_data()["history"] == []


def test_non_ascii_bearer_is_rejected_without_server_error():
    response = TestClient(main.app).get("/api/dashboard", headers={"Authorization": b"Bearer \xff"})
    assert response.status_code == 401
