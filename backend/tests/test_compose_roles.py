"""Inspect resolved synthetic Compose configuration; never contact a service."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_role_overlay_does_not_leak_shared_environment_credentials(tmp_path):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose CLI is needed for configuration-only verification")
    version = subprocess.run(["docker", "compose", "version"], capture_output=True,
                             timeout=15, check=False)
    if version.returncode:
        pytest.skip("Docker Compose CLI is needed for configuration-only verification")
    base = tmp_path / "compose.production.yml"
    shutil.copyfile(ROOT / "compose.production.yml", base)
    # Deliberately seed secrets in the shared env file: none may reach runtime.
    (tmp_path / ".env.production").write_text(
        "V2_MIGRATION_DATABASE_URL=synthetic-migration-secret\n"
        "OPERATOR_SECRET=synthetic-operator-secret\n", encoding="utf-8")
    interpolation = tmp_path / "interpolation.env"
    interpolation.write_text("", encoding="utf-8")
    env = os.environ | {
        "API_ACCESS_TOKEN": "synthetic-offline-token-with-at-least-32-characters",
        "GEMINI_API_KEY": "synthetic-provider-only", "POSTGRES_PASSWORD": "synthetic-db-only",
        "FRONTEND_ORIGINS": "https://localhost:8443", "SITE_HOST": "localhost",
        "V2_BACKEND_IMAGE": "agentflow-backend:synthetic-review",
        "V2_FRONTEND_IMAGE": "agentflow-frontend:synthetic-review",
        "V2_RUNTIME_DATABASE_URL": "postgresql+psycopg://agentflow_runtime:synthetic@postgres/agentflow",
        "V2_MIGRATION_DATABASE_URL": "postgresql+psycopg://agentflow_migrator:synthetic@postgres/agentflow",
    }
    result = subprocess.run([
        "docker", "compose", "--profile", "tools", "--env-file", str(interpolation), "-f", str(base),
        "-f", str(ROOT / "deploy/compose.accounts.yml"),
        "-f", str(ROOT / "deploy/compose.roles.yml"), "config", "--format", "json",
    ], env=env, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, "Synthetic Compose role overlay failed to resolve"
    services = json.loads(result.stdout)["services"]
    runtime = services["backend"]["environment"]
    migrator = services["migrate"]["environment"]
    assert runtime["DATABASE_URL"] == env["V2_RUNTIME_DATABASE_URL"]
    assert migrator["DATABASE_URL"] == env["V2_MIGRATION_DATABASE_URL"]
    for values in (runtime, migrator):
        assert "V2_MIGRATION_DATABASE_URL" not in values
        assert "OPERATOR_SECRET" not in values
        assert "synthetic-operator-secret" not in values.values()
    assert runtime["AUTH_MODE"] == "accounts"
    assert migrator["AUTH_MODE"] == "legacy_bearer"
