"""Offline regression tests for the working Gemini integration.

These tests NEVER make network calls. The known cancellation limitation is marked
xfail until an implementation can stop its underlying HTTP operation.
"""

import asyncio
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.research import generate_gemini_stage


def _stub_gemini(monkeypatch, create):
    """Replace the SDK with a controlled, synchronous fake."""
    entered = threading.Event()
    finished = threading.Event()

    class FakeClient:
        def __init__(self, **kwargs):
            self.interactions = SimpleNamespace(create=self.create)

        def create(self, **kwargs):
            entered.set()
            return create(**kwargs)

        def close(self):
            finished.set()

    google = ModuleType("google")
    genai = ModuleType("google.genai")
    genai.Client = FakeClient
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    return entered, finished


def _config():
    return Settings(_env_file=None, gemini_api_key=SecretStr("offline-fake"), provider_retry_attempts=0)


def test_busy_gemini_call_does_not_block_event_loop(monkeypatch):
    """A long SDK call must not block unrelated FastAPI event-loop work."""
    release = threading.Event()
    entered, finished = _stub_gemini(
        monkeypatch,
        lambda **kwargs: (release.wait(timeout=3), SimpleNamespace(output_text="ok", usage=None))[1],
    )

    async def check():
        task = asyncio.create_task(generate_gemini_stage("Report", "Write", "prompt", timeout_seconds=2, config=_config()))
        try:
            assert await asyncio.to_thread(entered.wait, 1), "Fake SDK call never started"
            # If synchronous network activity blocks the event loop, this timer cannot complete.
            await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.25)
        finally:
            release.set()
            await asyncio.wait_for(task, timeout=2)
        assert finished.is_set(), "Gemini client was not closed"

    asyncio.run(check())


@pytest.mark.xfail(strict=True, reason="Known issue: cancelling asyncio.to_thread does not stop the SDK worker thread")
def test_timeout_stops_underlying_sdk_request(monkeypatch):
    """Document desired behavior: the provider operation must stop when timed out.

    Expected to fail on the stable synchronous implementation. Do not change
    the working backend merely to turn this green without integration testing.
    """
    release = threading.Event()
    entered, finished = _stub_gemini(
        monkeypatch,
        lambda **kwargs: (release.wait(timeout=3), SimpleNamespace(output_text="late", usage=None))[1],
    )

    async def check():
        try:
            with pytest.raises(TimeoutError):
                await generate_gemini_stage("Report", "Write", "prompt", timeout_seconds=0.05, config=_config())
            assert entered.is_set(), "Fake SDK call never started"
            # Desired future invariant: timeout has stopped and cleaned up the provider request.
            assert finished.is_set(), "The SDK request kept running after timeout"
        finally:
            release.set()  # Always release the fake thread so the test process exits.
            await asyncio.sleep(0.02)

    asyncio.run(check())


@pytest.mark.xfail(
    strict=True,
    reason="Per-attempt SDK timeout cap not implemented in stable backend",
)
def test_long_stage_caps_single_sdk_attempt(monkeypatch):
    """Offline: a 180s stage must not grant one SDK call the whole budget."""
    observed = {}

    class FakeClient:
        def __init__(self, **kwargs):
            observed["http_timeout_ms"] = kwargs["http_options"]["timeout"]
            self.interactions = SimpleNamespace(create=lambda **kwargs: SimpleNamespace(
                output_text="ok", usage=None,
            ))

        def close(self):
            observed["closed"] = True

    google = ModuleType("google")
    genai = ModuleType("google.genai")
    genai.Client = FakeClient
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)

    result = asyncio.run(generate_gemini_stage(
        "Report", "Write", "prompt", timeout_seconds=180, config=_config(),
    ))
    assert result.final_output == "ok"
    assert 0 < observed["http_timeout_ms"] <= 45_000
    assert observed["closed"] is True
