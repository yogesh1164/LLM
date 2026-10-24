r"""Create/run/stop ONLY new offline fixtures. No existing application DB access.

From repository root: backend\.venv\Scripts\python.exe backend/tests/verify_durable_runtime.py
Evidence stays in a newly created ignored backups directory. No volumes are removed.
"""

import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
DOCKER = shutil.which("docker") or r"C:\Users\dhanu\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe"
TOKEN = "offline-runtime-auth-placeholder-1234567890"
IMAGE = "agentflow-backend:v2-review-hardening-tests"


def docker(*args, check=True):
    result = subprocess.run([DOCKER, "--context", "desktop-linux", *args], check=False,
                            capture_output=True, text=True, timeout=90)
    if check and result.returncode:
        raise RuntimeError("Isolated Docker command failed: " + result.stderr[-1500:])
    return result.stdout.strip()


def request(base, path, *, body=None, key=None, authorized=True, timeout=30):
    headers = {"Authorization": "Bearer " + TOKEN} if authorized else {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if key:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers=headers)
    try:
        response = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        content = response.read().decode()
        return response.status, dict(response.headers), json.loads(content) if content else None


def main():
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    prefix = "agentflow-v2-durable-e2e-" + stamp
    network, ingress, db_name, api_name = prefix + "-net", prefix + "-ingress", prefix + "-db", prefix + "-api"
    evidence = ROOT / "backups" / prefix
    evidence.mkdir(parents=True, exist_ok=False)
    envfile = evidence / "fixture.env"
    envfile.write_text("\n".join([
        "APP_ENV=development", "DURABLE_EXECUTION_ENABLED=true", "AGENTFLOW_OFFLINE_TEST=1",
        "DATABASE_URL=postgresql+psycopg://durable_fixture:offline-fixture-only@" + db_name + ":5432/agentflow_durable_fixture",
        "API_ACCESS_TOKEN=" + TOKEN, "GEMINI_API_KEY=offline-test-placeholder", "AI_PROVIDER=gemini",
        "GEMINI_MODEL=gemini-3.5-flash-lite", "GEMINI_SEARCH_GROUNDING_ENABLED=false", "PROVIDER_RETRY_ATTEMPTS=0",
        "EXECUTION_LEASE_SECONDS=10", "EXECUTION_HEARTBEAT_SECONDS=1", "EXECUTION_RECOVERY_SECONDS=1",
        "AGENT_TIMEOUT_SECONDS=5", "REVIEW_TIMEOUT_SECONDS=5", "WORKFLOW_TIMEOUT_SECONDS=10",
        "RATE_LIMIT_PER_MINUTE=600", "FRONTEND_ORIGIN=", "PYTHONPATH=/app/backend", "DATABASE_UNUSED=fixture-only",
    ]), encoding="utf-8")
    owned: dict[str, str] = {}
    checks = []

    def passed(name):
        checks.append(name)
        print("PASS " + name, flush=True)

    def sql(query):
        return docker("exec", db_name, "psql", "-U", "durable_fixture", "-d", "agentflow_durable_fixture", "-At", "-v", "ON_ERROR_STOP=1", "-c", query)

    def common():
        args = ["--network", network, "--env-file", str(envfile), "--read-only", "--tmpfs", "/tmp",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
        for source, target in [("backend/app", "app"), ("backend/tests", "tests"), ("backend/migrations", "migrations")]:
            args += ["-v", f"{ROOT / source}:/app/backend/{target}:ro"]
        for name in ("alembic.ini", "pyproject.toml"):
            args += ["-v", f"{ROOT / 'backend' / name}:/app/backend/{name}:ro"]
        return args + ["-v", f"{evidence}:/evidence"]

    def start_api(name):
        # Docker Desktop discards published ports on an internal-only network.
        # Only fixture APIs join this separate loopback ingress bridge; the DB does not.
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        owned[name] = docker("run", "-d", "--name", name, "--publish", f"127.0.0.1:{port}:8000", *common(), "--network", ingress, IMAGE,
                             "python", "-m", "uvicorn", "tests.durable_runtime_app:app", "--host", "0.0.0.0",
                             "--port", "8000", "--no-proxy-headers", "--no-access-log")
        return "http://" + docker("port", name, "8000/tcp")

    def ready(base):
        for _ in range(100):
            try:
                code, headers, _ = request(base, "/api/ready", timeout=1)
                if code == 200 and headers.get("x-agentflow-offline-fixture") == "1":
                    return
            except (OSError, ValueError):
                pass
            time.sleep(0.1)
        raise RuntimeError("Offline fixture did not become ready")

    def calls(execution_id):
        path = evidence / "provider-calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines() if json.loads(line)["execution_id"] == execution_id] if path.exists() else []

    try:
        docker("network", "create", "--internal", network)
        docker("network", "create", ingress)
        owned[db_name] = docker("run", "-d", "--name", db_name, "--network", network, "--tmpfs", "/var/lib/postgresql/data",
                                "-e", "POSTGRES_DB=agentflow_durable_fixture", "-e", "POSTGRES_USER=durable_fixture",
                                "-e", "POSTGRES_PASSWORD=offline-fixture-only", "postgres:16-bookworm")
        for _ in range(100):
            if docker("exec", db_name, "pg_isready", "-U", "durable_fixture", "-d", "agentflow_durable_fixture", check=False).endswith("accepting connections"):
                break
            time.sleep(0.1)
        mounts = json.loads(docker("inspect", db_name))[0]["Mounts"]
        assert not any(mount["Type"] == "volume" for mount in mounts)
        docker("run", "--rm", *common(), IMAGE, "python", "-m", "alembic", "upgrade", "head")
        schema = docker("run", "--rm", *common(), IMAGE, "python", "-m", "app.verify_durable_schema")
        assert json.loads(schema)["schema_verified"]
        passed("isolated migration, exact schema and no existing volume mounts")
        base = start_api(api_name); ready(base)
        assert request(base, "/api/dashboard", authorized=False)[0] == 401
        passed("enabled startup, health and bearer authentication")

        for scenario, expected_calls, tokens in [("crash-before-start", 0, None), ("crash-first", 1, None),
                                                 ("crash-after-one", 2, 5), ("crash-before-final", 5, 25)]:
            key = str(uuid4())
            try:
                request(base, "/api/workflows/execute", body={"task": "OFFLINE-RUNTIME " + scenario}, key=key)
                raise AssertionError("Expected an abrupt fixture process crash")
            except OSError:
                pass
            for _ in range(100):
                if docker("inspect", api_name, "--format", "{{.State.Running}}") == "false":
                    break
                time.sleep(0.05)
            digest = hashlib.sha256(key.encode()).hexdigest()
            row = json.loads(sql("SELECT row_to_json(d) FROM (SELECT id, task_id FROM durable_executions WHERE key_digest='" + digest + "') d"))
            execution_id = row["id"]
            assert len(calls(execution_id)) == expected_calls
            sql("UPDATE durable_executions SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id='" + execution_id + "'")
            docker("start", api_name); ready(base)
            state = request(base, "/api/executions/" + execution_id)[2]
            assert state["state"] == "interrupted" and state["safe_to_resubmit"] == (expected_calls == 0)
            duplicate = request(base, "/api/workflows/execute", body={"task": "OFFLINE-RUNTIME " + scenario}, key=key)
            assert duplicate[0] == 202 and len(calls(execution_id)) == expected_calls
            if row["task_id"]:
                task = request(base, "/api/tasks/" + row["task_id"])[2]
                assert task["status"] == "interrupted" and task["total_tokens"] == tokens
            passed(scenario + ": restart recovery preserves committed usage and never replays")

        key = str(uuid4())
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(request, base, "/api/workflows/execute", body={"task": "OFFLINE-RUNTIME hold"}, key=key)
            execution_id = None
            for _ in range(100):
                matches = sql("SELECT id FROM durable_executions WHERE key_digest='" + hashlib.sha256(key.encode()).hexdigest() + "'")
                if matches and calls(matches):
                    execution_id = matches; break
                time.sleep(0.05)
            assert execution_id
            heartbeat = sql("SELECT heartbeat_at FROM durable_executions WHERE id='" + execution_id + "'")
            time.sleep(1.3)
            assert sql("SELECT heartbeat_at FROM durable_executions WHERE id='" + execution_id + "'") != heartbeat
            sql("UPDATE durable_executions SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id='" + execution_id + "'")
            for _ in range(100):
                if request(base, "/api/executions/" + execution_id)[2]["state"] != "running":
                    break
                time.sleep(0.05)
            (evidence / f"release-{execution_id}").write_text("release offline SDK", encoding="utf-8")
            assert pending.result(timeout=10)[0] == 503
            assert request(base, "/api/executions/" + execution_id)[2]["state"] == "interrupted"
            assert len(calls(execution_id)) == 1
        passed("heartbeat renewal, forced expiry, stale in-flight result fencing")

        second_name = prefix + "-api2"
        second = start_api(second_name); ready(second)
        key = str(uuid4())
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda index: request(base if index % 2 else second, "/api/workflows/execute",
                         body={"task": "OFFLINE-RUNTIME concurrent"}, key=key), range(8)))
        assert sum(result[0] == 200 for result in results) == 1
        assert sum(result[0] == 202 for result in results) == 7
        execution_id = sql("SELECT id FROM durable_executions WHERE key_digest='" + hashlib.sha256(key.encode()).hexdigest() + "'")
        assert len(calls(execution_id)) == 5
        original = request(base, "/api/executions/" + execution_id)[2]
        task_before = request(base, "/api/tasks/" + original["task_id"])[2]
        docker("restart", api_name); ready(base)
        assert request(base, "/api/tasks/" + original["task_id"])[2] == task_before
        assert len(calls(execution_id)) == 5
        passed("eight requests across two processes admit one workflow; restart preserves completed history")

        previous_calls = len((evidence / "provider-calls.jsonl").read_text().splitlines())
        browser_env = {**os.environ, "DURABLE_RUNTIME_BASE_URL": base, "DURABLE_RUNTIME_TOKEN": TOKEN}
        browser = subprocess.run(["npm.cmd" if os.name == "nt" else "npm", "test"], cwd=ROOT / "frontend",
                                 env=browser_env, check=False, timeout=180, capture_output=True, text=True)
        (evidence / "frontend-tests.log").write_text((browser.stdout + browser.stderr).replace(TOKEN, "[offline credential omitted]"), encoding="utf-8")
        assert browser.returncode == 0, "Frontend integration failed; inspect ignored fixture test log"
        all_calls = [json.loads(line) for line in (evidence / "provider-calls.jsonl").read_text().splitlines()]
        assert len(all_calls) - previous_calls == 7  # five fixed stages + one agent + one saved-workflow step
        assert all(event["model"] == "gemini-3.5-flash-lite" for event in all_calls)
        passed("mocked frontend suite plus real browser-to-enabled-backend integration")
        # Binary-safe backup/restore rehearsal of synthetic fixture data ONLY.
        tables = ["tasks", "agent_executions", "custom_agents", "custom_agent_executions", "custom_workflows",
                  "custom_workflow_steps", "custom_workflow_runs", "custom_workflow_step_runs", "durable_executions"]
        digest_queries = ["SELECT count(*)::text || ':' || coalesce(md5(string_agg(md5(row_to_json(t)::text),'' ORDER BY id)), '') FROM " + table + " t" for table in tables]
        before = [sql(query) for query in digest_queries]
        docker("exec", db_name, "pg_dump", "-U", "durable_fixture", "-d", "agentflow_durable_fixture", "--format=custom",
               "--no-owner", "--no-acl", "--file", "/tmp/fixture.dump")
        source_hash = docker("exec", db_name, "sha256sum", "/tmp/fixture.dump").split()[0]
        archive = evidence / "fixture.dump"
        docker("cp", db_name + ":/tmp/fixture.dump", str(archive))
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == source_hash
        restore_name = prefix + "-restore"
        owned[restore_name] = docker("run", "-d", "--name", restore_name, "--network", "none", "--tmpfs", "/var/lib/postgresql/data",
                                    "-e", "POSTGRES_DB=restore_fixture", "-e", "POSTGRES_USER=restore_fixture",
                                    "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:16-bookworm")
        for _ in range(100):
            if docker("exec", restore_name, "pg_isready", "-U", "restore_fixture", "-d", "restore_fixture", check=False).endswith("accepting connections"):
                break
            time.sleep(0.1)
        docker("cp", str(archive), restore_name + ":/tmp/fixture.dump")
        assert docker("exec", restore_name, "sha256sum", "/tmp/fixture.dump").split()[0] == source_hash
        assert docker("exec", restore_name, "pg_restore", "--list", "/tmp/fixture.dump")
        docker("exec", restore_name, "pg_restore", "-U", "restore_fixture", "-d", "restore_fixture", "--single-transaction",
               "--exit-on-error", "--no-owner", "--no-acl", "/tmp/fixture.dump")
        after = [docker("exec", restore_name, "psql", "-U", "restore_fixture", "-d", "restore_fixture", "-At", "-v", "ON_ERROR_STOP=1", "-c", query) for query in digest_queries]
        assert before == after
        assert docker("exec", restore_name, "psql", "-U", "restore_fixture", "-d", "restore_fixture", "-At", "-c", "SELECT version_num FROM alembic_version") == "0006_durable_executions"
        passed("binary-safe synthetic backup, three-way SHA-256 match, fresh restore and all table digests preserved")
        report = {"checks": checks, "failures": 0, "fixture_containers": owned, "schema": json.loads(schema),
                  "provider": "offline synchronous SDK double", "public_deployment": False}
        (evidence / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"runtime_checks_passed": len(checks), "evidence": str(evidence)}), flush=True)
    finally:
        for name, identifier in reversed(list(owned.items())):
            current = docker("inspect", name, "--format", "{{.Id}}", check=False)
            if name.startswith(prefix) and current == identifier:
                docker("stop", "--time", "5", name, check=False)


if __name__ == "__main__":
    main()
