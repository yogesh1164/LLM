"""Rehearse account + durable browser execution on NEW tmpfs fixtures only.

No restore, real dotenv file, existing database or provider call is involved.
Run from the repository root with backend/.venv/Scripts/python.exe.
"""
import json
import os
import socket
import subprocess
import time
from datetime import UTC, datetime

from tests.verify_durable_runtime import ROOT, docker

IMAGE = "agentflow-backend:v2-accounts-resume-review"


def main():
    prefix = "agentflow-v2-durable-e2e-accounts-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    network, ingress = prefix + "-net", prefix + "-ingress"
    db_name, api_name = prefix + "-db", prefix + "-api"
    evidence = ROOT / "backups" / prefix
    evidence.mkdir(exist_ok=False)
    owned = {}
    environment = {
        "APP_ENV": "development", "AUTH_MODE": "accounts", "DURABLE_EXECUTION_ENABLED": "true",
        "AGENTFLOW_OFFLINE_TEST": "1", "GEMINI_API_KEY": "offline-fixture-only",
        "DATABASE_URL": f"postgresql+psycopg://durable_fixture:offline-fixture-only@{db_name}:5432/agentflow_durable_fixture",
        "GEMINI_MODEL": "gemini-3.5-flash-lite", "PROVIDER_RETRY_ATTEMPTS": "0",
        "FRONTEND_ORIGINS": "http://127.0.0.1:3307", "FRONTEND_ORIGIN": "",
        "RATE_LIMIT_PER_MINUTE": "600", "PYTHONPATH": "/app/backend",
    }
    common = ["--network", network, "--read-only", "--tmpfs", "/tmp", "--cap-drop", "ALL",
              "--security-opt", "no-new-privileges"]
    for key, value in environment.items():
        common += ["-e", key + "=" + value]
    for source in ("app", "tests", "migrations"):
        common += ["-v", f"{ROOT / 'backend' / source}:/app/backend/{source}:ro"]
    common += ["-v", f"{evidence}:/evidence"]
    try:
        docker("network", "create", "--internal", network)
        docker("network", "create", ingress)
        owned[db_name] = docker("run", "-d", "--name", db_name, "--network", network,
            "--tmpfs", "/var/lib/postgresql/data", "-e", "POSTGRES_DB=agentflow_durable_fixture",
            "-e", "POSTGRES_USER=durable_fixture", "-e", "POSTGRES_PASSWORD=offline-fixture-only",
            "postgres:16-bookworm")
        for _ in range(100):
            if docker("exec", db_name, "pg_isready", "-U", "durable_fixture", check=False).endswith("accepting connections"):
                break
            time.sleep(0.1)
        assert not any(m["Type"] == "volume" for m in json.loads(docker("inspect", db_name))[0]["Mounts"])
        docker("run", "--rm", *common, IMAGE, "python", "-m", "alembic", "upgrade", "head")
        docker("run", "--rm", *common, IMAGE, "python", "-c",
               "from app import accounts; from app.auth_foundation import Role; "
               "accounts.create_user('browser-admin','offline-browser-password',role=Role.ADMIN,bootstrap=True); "
               "accounts.create_user('browser-member','offline-browser-password')")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        owned[api_name] = docker("run", "-d", "--name", api_name, "--publish", f"127.0.0.1:{port}:8000",
            *common, "--network", ingress, IMAGE, "python", "-m", "uvicorn", "tests.durable_runtime_app:app",
            "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log")
        from tests.verify_durable_runtime import request
        base = "http://" + docker("port", api_name, "8000/tcp")
        for _ in range(100):
            try:
                status, headers, _ = request(base, "/api/ready", authorized=False, timeout=1)
                if status == 200 and headers.get("x-agentflow-offline-fixture") == "1":
                    break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Offline account fixture failed readiness")
        browser_env = {**os.environ, "DURABLE_RUNTIME_BASE_URL": base, "DURABLE_RUNTIME_ACCOUNTS": "1"}
        browser_env.pop("DURABLE_RUNTIME_TOKEN", None)
        browser = subprocess.run(["npm.cmd" if os.name == "nt" else "npm", "test"], cwd=ROOT / "frontend",
            env=browser_env, timeout=180, capture_output=True, text=True, check=False)
        (evidence / "frontend-tests.log").write_text(browser.stdout + browser.stderr, encoding="utf-8")
        assert browser.returncode == 0, "Inspect the ignored frontend-tests.log"
        calls = [json.loads(line) for line in (evidence / "provider-calls.jsonl").read_text().splitlines()]
        assert len(calls) == 7 and all(c["model"] == "gemini-3.5-flash-lite" for c in calls)
        report = {"browser_exit": 0, "offline_provider_calls": len(calls), "fixture_containers": owned,
                  "accounts_and_durable": True, "existing_database_access": False}
        (evidence / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"passed": True, "evidence": str(evidence)}), flush=True)
    finally:
        for name, identifier in reversed(list(owned.items())):
            if name.startswith(prefix) and docker("inspect", name, "--format", "{{.Id}}", check=False) == identifier:
                docker("stop", "--time", "5", name, check=False)


if __name__ == "__main__":
    main()
