"""Rehearse account + durable browser execution on NEW tmpfs fixtures only.

No real dotenv file, existing database or provider call is involved.
From backend: .venv/Scripts/python.exe -m tests.verify_accounts_runtime.
"""
import argparse
import http.cookiejar
import importlib.util
import json
import os
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

from tests.verify_durable_runtime import ROOT, docker

IMAGE = "agentflow-backend:v2-accounts-resume-review"


def https_smoke(prefix, ingress, api_name, evidence, owned, production_accounts=False):
    """Private synthetic CA trust is scoped to one SSLContext, never OS trust."""
    frontend, proxy = prefix + "-frontend", prefix + "-proxy"
    config = evidence / "Caddyfile"
    config.write_text((ROOT / "deploy/Caddyfile").read_text().replace("admin off", "admin off\n    skip_install_trust").replace(
        "backend:8000", api_name + ":8000").replace("frontend:3000", frontend + ":3000"), encoding="utf-8")
    owned[frontend] = docker("run", "-d", "--name", frontend, "--network", ingress,
        "--read-only", "--tmpfs", "/tmp", "--cap-drop", "ALL", "--security-opt",
        "no-new-privileges", "agentflow-frontend:v2-accounts-resume-review")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    owned[proxy] = docker("run", "-d", "--name", proxy, "--network", ingress,
        "--publish", f"127.0.0.1:{port}:443", "--read-only", "--tmpfs", "/tmp",
        "--tmpfs", "/data", "--tmpfs", "/config", "--cap-drop", "ALL",
        "--cap-add", "NET_BIND_SERVICE",
        "--security-opt", "no-new-privileges", "-e", "SITE_HOST=localhost",
        "-v", f"{config}:/etc/caddy/Caddyfile:ro", "caddy:2-alpine")
    certificate = evidence / "synthetic-root.crt"
    for _ in range(100):
        # Docker cp cannot reliably read tmpfs mounts on Docker Desktop.
        public_root = docker("exec", proxy, "cat", "/data/caddy/pki/authorities/local/root.crt", check=False)
        if "BEGIN CERTIFICATE" in public_root:
            certificate.write_text(public_root + "\n", encoding="ascii")
            break
        time.sleep(0.1)
    context = ssl.create_default_context(cafile=str(certificate))
    checks = []
    for path, expected in (("/", 200), ("/api/ready", 200), ("/api/dashboard", 401), ("/docs", 404)):
        for attempt in range(30):
            try:
                response = urllib.request.urlopen(f"https://localhost:{port}" + path, context=context, timeout=3)
            except urllib.error.HTTPError as error:
                response = error
            except OSError:
                if attempt == 29:
                    raise
                time.sleep(0.2)
                continue
            with response:
                if response.status == 502 and attempt != 29:
                    time.sleep(0.2)
                    continue
                assert response.status == expected
                assert response.headers.get("X-Content-Type-Options") == "nosniff"
                checks.append({"path": path, "status": response.status})
                break
    if production_accounts:
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context),
                                             urllib.request.HTTPCookieProcessor(jar))
        base = f"https://localhost:{port}"
        login = urllib.request.Request(base + "/api/auth/login", data=json.dumps({
            "login": "browser-admin", "password": "offline-browser-password"}).encode(),
            headers={"Content-Type": "application/json", "Origin": "https://localhost:8443",
                     "X-AgentFlow-Login": "1"})
        with opener.open(login, timeout=10) as response:
            assert response.status == 200
            cookie = response.headers.get("Set-Cookie", "")
            assert cookie.startswith("__Host-agentflow_session=")
            assert all(flag in cookie.lower() for flag in ("secure", "httponly", "samesite=strict", "path=/"))
            assert "domain=" not in cookie.lower()
        original_cookie = "; ".join(item.name + "=" + item.value for item in jar)
        with opener.open(base + "/api/auth/me", timeout=10) as response:
            me = json.load(response)
            assert me["login"] == "browser-admin"
        with opener.open(base + "/api/dashboard", timeout=10) as response:
            assert response.status == 200
        logout = urllib.request.Request(base + "/api/auth/logout", data=b"", headers={
            "Origin": "https://localhost:8443", "X-CSRF-Token": me["csrf_token"]})
        with opener.open(logout, timeout=10) as response:
            assert response.status == 204
        replay = urllib.request.Request(base + "/api/auth/me", headers={"Cookie": original_cookie})
        try:
            urllib.request.urlopen(replay, context=context, timeout=10)
        except urllib.error.HTTPError as response:
            assert response.code == 401
        else:
            raise AssertionError("Revoked synthetic session was accepted")
    return {"trusted_https": True, "loopback_only": True, "production_frontend_image": True,
            "checks": checks, "production_cookie_headers_verified": production_accounts,
            "https_login_authenticated_read_logout_revocation": production_accounts,
            "actual_browser_acceptance": False,
            "limitation": "HTTPS cookie client is urllib; actual browser session acceptance still required"}


def seed_legacy():
    """Synthetic V1 task + stage; production runtime images do not include pytest."""
    from app import database as db
    with db.SessionLocal.begin() as session:
        task = db.Task(prompt="Offline legacy task", status="completed", total_tokens=5,
                       result={"research": "legacy research"})
        task.stages = [db.AgentExecution(agent="Research", status="completed", output="legacy research",
                                         input_tokens=3, output_tokens=2)]
        session.add(task)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--least-privilege", action="store_true")
    parser.add_argument("--backup-restore", action="store_true")
    parser.add_argument("--https-smoke", action="store_true")
    parser.add_argument("--rollback-only", action="store_true", help="New fixture: account-aware same-image runtime with durable off, no browser/provider calls")
    parser.add_argument("--image", default=IMAGE)
    options = parser.parse_args()
    if (options.backup_restore or options.rollback_only) and not options.least_privilege:
        parser.error("--backup-restore/--rollback-only require --least-privilege")
    prefix = "agentflow-v2-durable-e2e-accounts-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    network, ingress = prefix + "-net", prefix + "-ingress"
    db_name, api_name = prefix + "-db", prefix + "-api"
    evidence = ROOT / "backups" / prefix
    evidence.mkdir(exist_ok=False)
    owned = {}
    created_networks = []
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
        if options.rollback_only and source == "app":
            continue  # Rollback verifies actual immutable image application code.
        common += ["-v", f"{ROOT / 'backend' / source}:/app/backend/{source}:ro"]
    common += ["-v", f"{evidence}:/evidence"]
    common += ["-v", f"{ROOT / 'deploy'}:/app/deploy:ro"]
    migrator_url = f"postgresql+psycopg://agentflow_migrator:offline-fixture-only@{db_name}:5432/agentflow_durable_fixture"
    runtime_url = migrator_url.replace("agentflow_migrator:", "agentflow_runtime:")
    migration_common = common + ["-e", "DATABASE_URL=" + migrator_url] if options.least_privilege else common

    def sql(statement, database="agentflow_durable_fixture"):
        return docker("exec", db_name, "psql", "-XAt", "-v", "ON_ERROR_STOP=1", "-U",
                      "durable_fixture", "-d", database, "-c", statement)

    def snapshot(database="agentflow_durable_fixture", legacy=False):
        tables = sql("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename", database).splitlines()
        if legacy:
            tables = [name for name in tables if name != "alembic_version"]
        return {name: sql("SELECT coalesce(jsonb_agg(r ORDER BY r::text), '[]'::jsonb) FROM "
                f"(SELECT to_jsonb(t) - 'owner_id' AS r FROM public.\"{name}\" t) q" if legacy else
                "SELECT coalesce(jsonb_agg(r ORDER BY r::text), '[]'::jsonb) FROM "
                f"(SELECT to_jsonb(t) AS r FROM public.\"{name}\" t) q", database) for name in tables}

    def backup_restore(label):
        spec = importlib.util.spec_from_file_location("backup_tool", ROOT / "ops/backup/backup.py")
        backup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backup)
        from cryptography.fernet import Fernet
        restore_name = "agentflow_restore_" + label
        sql("CREATE DATABASE " + restore_name + " OWNER agentflow_migrator")
        source = backup.Postgres("agentflow_durable_fixture", "agentflow_backup",
                                 "/var/run/postgresql", container=db_name)
        target = backup.Postgres(restore_name, "durable_fixture", "/var/run/postgresql", container=db_name)
        with tempfile.TemporaryDirectory(prefix="agentflow-combined-backup-") as work:
            from pathlib import Path
            work = Path(work)
            key = work / "separate-test-key"
            key.write_bytes(Fernet.generate_key())
            result = backup.backup(source, key_file=key, spool=work / "spool", destination=work / "destination")
            archive = work / "restore.dump"
            backup.decrypt(work / "destination" / result["artifact"], archive, key.read_bytes())
            target.restore(archive, "agentflow_migrator")
            assert snapshot() == snapshot(restore_name)
            assert sql("SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname='public'", restore_name) == "agentflow_migrator"
            return {"encryption_verified": True, "local_delivery_verified": True,
                    "restored_snapshot_matches": True, "tables": len(snapshot()),
                    "archive_sha256": result["archive_sha256"], "off_host_verified": False}
    try:
        docker("network", "create", "--internal", network)
        created_networks.append(network)
        docker("network", "create", ingress)
        created_networks.append(ingress)
        owned[db_name] = docker("run", "-d", "--name", db_name, "--network", network,
            "--tmpfs", "/var/lib/postgresql/data", "-e", "POSTGRES_DB=agentflow_durable_fixture",
            "-e", "POSTGRES_USER=durable_fixture", "-e", "POSTGRES_PASSWORD=offline-fixture-only",
            "postgres:16-bookworm")
        for _ in range(100):
            if docker("exec", db_name, "pg_isready", "-U", "durable_fixture", check=False).endswith("accepting connections"):
                break
            time.sleep(0.1)
        assert not any(m["Type"] == "volume" for m in json.loads(docker("inspect", db_name))[0]["Mounts"])
        if options.least_privilege:
            docker("run", "--rm", *common, options.image, "python", "-c",
                "import sys; sys.path.insert(0,'/app/deploy'); import postgres_roles as r; "
                "from sqlalchemy import text; from app.database import engine; "
                "conn=engine.connect(); tx=conn.begin(); "
                "[conn.execute(text(s)) for s in r.bootstrap_sql('agentflow_durable_fixture')]; "
                "[conn.execute(text(f\"ALTER ROLE {role} LOGIN PASSWORD 'offline-fixture-only'\")) "
                "for role in ('agentflow_migrator','agentflow_runtime','agentflow_backup')]; tx.commit()")
            docker("run", "--rm", *migration_common, options.image, "python", "-m", "alembic", "upgrade", "0005_custom_workflows")
            docker("run", "--rm", *migration_common, options.image, "python", "-c",
                   "from tests.verify_accounts_runtime import seed_legacy; seed_legacy()")
            before = snapshot(legacy=True)
            pre_backup = backup_restore("before") if options.backup_restore else None
            for revision in ("0006_durable_executions", "0007_accounts_ownership"):
                docker("run", "--rm", *migration_common, options.image, "python", "-m", "alembic", "upgrade", revision)
            after = snapshot(legacy=True)
            assert all(after[name] == rows for name, rows in before.items())
        else:
            docker("run", "--rm", *common, options.image, "python", "-m", "alembic", "upgrade", "head")
        docker("run", "--rm", *migration_common, options.image, "python", "-c",
               "from app import accounts; from app.auth_foundation import Role; "
               "accounts.create_user('browser-admin','offline-browser-password',role=Role.ADMIN,bootstrap=True); "
               "accounts.create_user('browser-member','offline-browser-password')")
        if options.least_privilege:
            docker("run", "--rm", *migration_common, options.image, "python", "-c",
                   "from app import legacy_ownership, database; from sqlalchemy import text; "
                   "conn=database.engine.connect(); tx=conn.begin(); "
                   "owner=conn.execute(text(\"SELECT id FROM users WHERE login='browser-admin'\")).scalar_one(); "
                   "plan=legacy_ownership.plan(conn, owner); "
                   "assert legacy_ownership.apply(conn, plan, confirm_login='browser-admin',approved_by='synthetic-rehearsal')==1; tx.commit()")
            docker("run", "--rm", *migration_common, options.image, "python", "-c",
                   "import sys; sys.path.insert(0,'/app/deploy'); import postgres_roles as r; "
                   "from sqlalchemy import inspect,text; from app.database import engine; "
                   "conn=engine.connect(); tx=conn.begin(); "
                   "[conn.execute(text(s)) for s in r.grants_sql(inspect(conn).get_table_names())]; tx.commit()")
            common += ["-e", "DATABASE_URL=" + runtime_url, "-e", "AGENTFLOW_OFFLINE_LEAST_PRIVILEGE=1"]
        if options.rollback_only:
            sql("""INSERT INTO durable_executions
                (id,scope,operation,key_digest,request_digest,state,lease_token,
                 lease_expires_at,heartbeat_at,created_at,provider_started,task_id,owner_id)
                SELECT gen_random_uuid(),owner_id::text,'workflow',repeat('c',64),repeat('d',64),
                 'completed',gen_random_uuid(),now(),now(),now(),false,id,owner_id
                 FROM tasks LIMIT 1""")
        preserved = snapshot() if options.rollback_only else None
        if options.rollback_only:
            common += ["-e", "DURABLE_EXECUTION_ENABLED=false", "-e", "APP_ENV=production",
                       "-e", "FRONTEND_ORIGINS=https://localhost:8443"]
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        owned[api_name] = docker("run", "-d", "--name", api_name, "--publish", f"127.0.0.1:{port}:8000",
            *common, "--network", ingress, options.image, "python", "-m", "uvicorn",
            "app.main:app" if options.rollback_only else "tests.durable_runtime_app:app",
            "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log")
        if options.rollback_only:
            mounts = json.loads(docker("inspect", api_name))[0]["Mounts"]
            assert not any(m["Destination"].rstrip("/") in {"/app", "/app/backend", "/app/backend/app"}
                           for m in mounts), "Rollback must use the image's own application code"
        from tests.verify_durable_runtime import request
        base = "http://" + docker("port", api_name, "8000/tcp")
        for _ in range(100):
            try:
                status, headers, _ = request(base, "/api/ready", authorized=False, timeout=1)
                if status == 200 and (options.rollback_only or headers.get("x-agentflow-offline-fixture") == "1"):
                    break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Offline account fixture failed readiness")
        if options.rollback_only:
            assert request(base, "/api/dashboard", authorized=False)[0] == 401
            assert snapshot() == preserved
            tls_result = https_smoke(prefix, ingress, api_name, evidence, owned, production_accounts=True) if options.https_smoke else None
            after_tls = snapshot()
            assert all(after_tls[name] == preserved[name] for name in ("tasks", "agent_executions", "durable_executions"))
            report = {"safe_account_aware_rollback": True, "production_accounts": True,
                      "durable_enabled": False, "all_table_snapshots_preserved": True,
                      "snapshot_comparison_point": "before TLS authentication smoke",
                      "owned_records_preserved_after_tls_auth_smoke": True,
                      "preserved_owned_tasks": int(sql("SELECT count(*) FROM tasks WHERE owner_id IS NOT NULL")),
                      "preserved_committed_journals": int(sql("SELECT count(*) FROM durable_executions WHERE state='completed' AND owner_id IS NOT NULL")),
                      "https_smoke": tls_result,
                      "paid_requests": 0, "selected_image_acceptance_verified": True,
                      "rollback_image": options.image,
                      "rollback_image_id": docker("image", "inspect", options.image, "--format", "{{.Id}}"),
                      "image_app_source_used": True,
                      "fixture_containers": owned}
            (evidence / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({"passed": True, "evidence": str(evidence)}), flush=True)
            return
        browser_env = {**os.environ, "DURABLE_RUNTIME_BASE_URL": base, "DURABLE_RUNTIME_ACCOUNTS": "1"}
        browser_env.pop("DURABLE_RUNTIME_TOKEN", None)
        browser = subprocess.run(["npm.cmd" if os.name == "nt" else "npm", "test"], cwd=ROOT / "frontend",
            env=browser_env, timeout=180, capture_output=True, text=True, check=False)
        (evidence / "frontend-tests.log").write_text(browser.stdout + browser.stderr, encoding="utf-8")
        assert browser.returncode == 0, "Inspect the ignored frontend-tests.log"
        calls = [json.loads(line) for line in (evidence / "provider-calls.jsonl").read_text().splitlines()]
        assert len(calls) == 7 and all(c["model"] == "gemini-3.5-flash-lite" for c in calls)
        backup_result = backup_restore("after") if options.backup_restore else None
        tls_result = https_smoke(prefix, ingress, api_name, evidence, owned) if options.https_smoke else None
        report = {"browser_exit": 0, "offline_provider_calls": len(calls), "fixture_containers": owned,
                  "accounts_and_durable": True, "existing_database_access": False}
        report.update({"least_privilege": options.least_privilege, "backup_restore": backup_result,
                       "https_smoke": tls_result,
                       "pre_migration_backup_restore": pre_backup if options.least_privilege else None,
                       "legacy_records_preserved_and_explicitly_assigned": options.least_privilege})
        (evidence / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"passed": True, "evidence": str(evidence)}), flush=True)
    finally:
        for name, identifier in reversed(list(owned.items())):
            if name.startswith(prefix) and docker("inspect", name, "--format", "{{.Id}}", check=False) == identifier:
                docker("stop", "--time", "5", name, check=False)
                for created_network in created_networks:
                    docker("network", "disconnect", "--force", created_network, name, check=False)
        for created_network in reversed(created_networks):
            docker("network", "rm", created_network, check=False)


if __name__ == "__main__":
    main()
