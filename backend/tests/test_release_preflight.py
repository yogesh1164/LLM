"""Preflight must fail closed and keep target configuration private."""
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("release_preflight", Path(__file__).resolve().parents[2] / "deploy/release_preflight.py")
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


def test_default_preflight_never_connects(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "database", lambda *_: pytest.fail("implicit database access"))
    assert preflight.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "offline_plan"
    assert result["release_approved"] is False


@pytest.mark.parametrize("origin", ["https://*", "http://localhost:3000", "https://user:secret@host", "https://host/path", "https://host:bad", ""])
def test_reject_unsafe_origins_without_echoing_values(origin):
    result = preflight.configuration({"APP_ENV": "production", "AUTH_MODE": "accounts", "FRONTEND_ORIGINS": origin})
    assert not result["configuration_valid"]
    assert "secret" not in json.dumps(result)


def test_accounts_configuration_and_flag_inspection():
    result = preflight.configuration({"APP_ENV": "production", "AUTH_MODE": "accounts", "DURABLE_EXECUTION_ENABLED": "true", "FRONTEND_ORIGINS": "https://localhost:8443", "GEMINI_API_KEY": "synthetic", "DATABASE_URL": "postgresql+psycopg://agentflow_runtime:synthetic@fixture/fixture"})
    assert result["configuration_valid"] and result["durable_enabled"] and result["accounts_enabled"]


def test_database_identity_required_and_errors_redacted(monkeypatch, capsys):
    monkeypatch.setenv("PREFLIGHT_TEST_URL", "postgresql://private:secret@private-host/private-db")
    assert preflight.main(["--database-env-var", "PREFLIGHT_TEST_URL"]) == 1
    output = capsys.readouterr().out
    assert "secret" not in output and "private-host" not in output


def test_configuration_failure_propagates_exit_status(tmp_path, capsys):
    path = tmp_path / "fixture.env"
    path.write_text("APP_ENV=development\nAUTH_MODE=accounts\nFRONTEND_ORIGINS=https://localhost:8443\n")
    assert preflight.main(["--env-file", str(path)]) == 1
    assert not json.loads(capsys.readouterr().out)["inspection_passed"]


def test_image_runtime_security_failure_blocks_inspection(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "image", lambda _: {
        "id": "sha256:synthetic", "repository_digests": [],
        "nonroot_user": False, "healthcheck_present": True,
    })
    assert preflight.main(["--image", "synthetic-only"]) == 1
    assert not json.loads(capsys.readouterr().out)["inspection_passed"]


def test_disabled_flags_are_inspected_without_being_activated(tmp_path, capsys):
    path = tmp_path / "fixture.env"
    path.write_text("APP_ENV=production\nAUTH_MODE=legacy_bearer\n"
                    "DURABLE_EXECUTION_ENABLED=false\nFRONTEND_ORIGINS=https://localhost:8443\n"
                    "GEMINI_API_KEY=synthetic\nDATABASE_URL=postgresql+psycopg://agentflow_runtime:synthetic@fixture/fixture\n"
                    "API_ACCESS_TOKEN=synthetic-offline-token-of-at-least-32-characters\n")
    assert preflight.main(["--env-file", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result["checks"]["configuration"]["accounts_enabled"]
    assert not result["checks"]["configuration"]["durable_enabled"]


@pytest.mark.parametrize("changes", [
    {"GEMINI_API_KEY": ""}, {"AI_PROVIDER": "unknown"},
    {"GEMINI_API_KEY": "${GEMINI_API_KEY}"},
    {"DATABASE_URL": "sqlite://"},
    {"DATABASE_URL": "postgresql://agentflow_migrator:secret@fixture/db"},
])
def test_configuration_rejects_missing_runtime_inputs(changes):
    values = {"APP_ENV": "production", "AUTH_MODE": "accounts", "FRONTEND_ORIGINS": "https://localhost:8443", "GEMINI_API_KEY": "synthetic", "DATABASE_URL": "postgresql+psycopg://agentflow_runtime:synthetic@fixture/fixture"}
    result = preflight.configuration({**values, **changes})
    assert not result["configuration_valid"]
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("user", ["0:0", "root:root", "0", "root", ""])
def test_image_rejects_root_user_forms(monkeypatch, user):
    from types import SimpleNamespace
    monkeypatch.setattr(preflight.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=json.dumps([
        {"Id": "synthetic", "Config": {"User": user, "Healthcheck": {"Test": ["CMD", "true"]}}}])))
    assert not preflight.image("synthetic")["nonroot_user"]
