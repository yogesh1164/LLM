"""OFFLINE ONLY: controlled process/SDK failures for the isolated runtime drill.

This module is excluded from production images. It refuses non-fixture databases
and never imports or invokes the real Gemini SDK.
"""

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

from sqlalchemy.engine import make_url

from app.config import settings

url = make_url(settings.database_url)
if (os.environ.get("AGENTFLOW_OFFLINE_TEST") != "1" or settings.app_env != "development"
        or not settings.durable_execution_enabled or url.database != "agentflow_durable_fixture"
        or url.username != "durable_fixture" or not (url.host or "").startswith("agentflow-v2-durable-e2e-")
        or not (url.host or "").endswith("-db")):
    raise RuntimeError("Offline runtime harness requires its dedicated disposable database")

from app import database as db
from app import durable_execution as durable
from app import main
from app.observability import configure_production_logging

configure_production_logging()
database_ip = socket.gethostbyname(url.host)
original_connect = socket.socket.connect


def offline_connect(connection, address):
    if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", database_ip}:
        raise ConnectionRefusedError("Offline fixture blocks external Python network connections")
    return original_connect(connection, address)


socket.socket.connect = offline_connect
evidence = Path("/evidence")
counts: dict[str, int] = {}
lock = threading.Lock()


class FakeClient:
    def __init__(self, **kwargs):
        self.interactions = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        lease = durable.current_lease.get()
        if lease is None:
            raise RuntimeError("Offline provider requires an owned durable execution")
        with lock:
            ordinal = counts[lease.id] = counts.get(lease.id, 0) + 1
        event = {"execution_id": lease.id, "ordinal": ordinal, "model": kwargs["model"]}
        descriptor = os.open(evidence / "provider-calls.jsonl", os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, (json.dumps(event) + "\n").encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        task = kwargs["input"]
        if "OFFLINE-RUNTIME crash-first" in task or ("OFFLINE-RUNTIME crash-after-one" in task and ordinal == 2):
            os._exit(23)
        if "OFFLINE-RUNTIME hold" in task and ordinal == 1:
            deadline = time.monotonic() + 20
            while not (evidence / f"release-{lease.id}").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
        time.sleep(0.03)
        return SimpleNamespace(output_text=f"Offline stage {ordinal} output", usage=SimpleNamespace(
            total_input_tokens=3, total_output_tokens=2))

    def close(self):
        pass


google, genai = ModuleType("google"), ModuleType("google.genai")
genai.Client = FakeClient
google.genai = genai
sys.modules["google"] = google
sys.modules["google.genai"] = genai
original_create_task, original_update_task = main.create_task, main.update_task


def create_task(task):
    if "OFFLINE-RUNTIME crash-before-start" in task:
        os._exit(23)
    return original_create_task(task)


def update_task(task_id, **fields):
    if fields.get("status") == "completed" and "OFFLINE-RUNTIME crash-before-final" in db.get_task(task_id)["task"]:
        os._exit(23)
    return original_update_task(task_id, **fields)


main.create_task, main.update_task = create_task, update_task


class OfflineFixture:
    async def __call__(self, scope, receive, send):
        async def marked_send(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []),
                           (b"x-agentflow-offline-fixture", b"1")]}
            await send(message)
        await main.app(scope, receive, marked_send)


app = OfflineFixture()
