import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import database
from app.config import settings


@pytest.fixture(autouse=True)
def sqlite_database(monkeypatch):
    monkeypatch.setattr(settings, "api_access_token", SecretStr("t" * 32))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    database.Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(engine, expire_on_commit=False))
    yield
    database.Base.metadata.drop_all(engine)
    engine.dispose()

# AgentFlow rate-limit test isolation
import importlib as _agentflow_importlib

import pytest as _agentflow_pytest


@_agentflow_pytest.fixture(autouse=True)
def _reset_agentflow_rate_limit():
    api_main = _agentflow_importlib.import_module("app.main")
    with api_main._rate_limit_lock:
        api_main._rate_events.clear()

    yield

    with api_main._rate_limit_lock:
        api_main._rate_events.clear()
