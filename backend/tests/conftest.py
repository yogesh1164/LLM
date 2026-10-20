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
