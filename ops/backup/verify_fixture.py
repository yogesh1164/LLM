"""Synthetic backup drill; only creates a new network-less, tmpfs PG16 fixture.

Run from repository root. Existing databases and volumes are never accessed.
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import backup as tool
from cryptography.fernet import Fernet


def sql(container, database, statement):
    return tool.run(["docker", "exec", container, "psql", "-XAt", "-v", "ON_ERROR_STOP=1",
                     "-U", "fixture_admin", "-d", database, "-c", statement]).decode().strip()


def snapshot(container, database):
    tables = sql(container, database, "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                                    "ORDER BY tablename").splitlines()
    return {table: sql(container, database, f'SELECT coalesce(jsonb_agg(r ORDER BY r::text), '\
                       f"'[]'::jsonb) FROM (SELECT to_jsonb(t) AS r FROM public.\"{table}\" t) q")
            for table in tables}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-image", default="agentflow-backend:v2-accounts-final-tests")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    name = "agentflow-v2-backup-fixture-" + uuid4().hex[:12]
    root = Path(__file__).resolve().parents[2]
    created = False
    try:
        tool.run(["docker", "run", "--detach", "--name", name, "--network", "none",
                  "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=512m",
                  "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "POSTGRES_USER=fixture_admin",
                  "-e", "POSTGRES_DB=agentflow_backup_fixture", "postgres:16-bookworm"])
        created = True
        for _ in range(40):
            ready = subprocess.run(["docker", "exec", name, "pg_isready", "-U", "fixture_admin"],
                                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ready.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise tool.BackupError("Fixture startup failed")
        tool.run(["docker", "run", "--rm", "--network", "container:" + name,
                  "-v", str(root / "backend") + ":/app:ro", "-w", "/app",
                  "-e", ("DATABASE_URL=postgresql+psycopg://fixture_admin@127.0.0.1:5432/"
                  "agentflow_backup_fixture"), args.app_image, "python", "-m", "alembic",
                  "upgrade", "head"])
        sql(name, "agentflow_backup_fixture", """
          CREATE ROLE af_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
          CREATE ROLE af_restore_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
          GRANT CONNECT ON DATABASE agentflow_backup_fixture TO af_backup;
          GRANT USAGE ON SCHEMA public TO af_backup;
          GRANT SELECT ON ALL TABLES IN SCHEMA public TO af_backup;
          GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO af_backup;
          INSERT INTO users VALUES ('10000000-0000-0000-0000-000000000001',
            'synthetic-admin','not-a-valid-password-hash','admin',true,now(),now());
          INSERT INTO tasks(id,prompt,status,created_at,owner_id)
            VALUES ('20000000-0000-0000-0000-000000000001','synthetic Unicode नमस्ते',
            'completed',now(),'10000000-0000-0000-0000-000000000001');
          INSERT INTO account_sessions(digest,user_id,csrf_digest,created_at,expires_at,
             idle_expires_at) VALUES (repeat('a',64),'10000000-0000-0000-0000-000000000001',
             repeat('b',64),now(),now()+interval '1 hour',now()+interval '15 minutes');
          INSERT INTO durable_executions(id,scope,operation,key_digest,request_digest,state,
             lease_token,lease_expires_at,heartbeat_at,created_at,provider_started,task_id,owner_id)
             VALUES ('30000000-0000-0000-0000-000000000001',
             '10000000-0000-0000-0000-000000000001','workflow',repeat('c',64),
             repeat('d',64),'completed','40000000-0000-0000-0000-000000000001',now(),now(),now(),
             false,'20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001');
          """)
        sql(name, "agentflow_backup_fixture", "CREATE DATABASE agentflow_restore_fixture "
                                              "OWNER af_restore_owner")
        source = tool.Postgres("agentflow_backup_fixture", "af_backup", "/var/run/postgresql",
                               container=name)
        target = tool.Postgres("agentflow_restore_fixture", "fixture_admin",
                               "/var/run/postgresql", container=name)
        with tempfile.TemporaryDirectory(prefix="agentflow-encryption-drill-") as work:
            work = Path(work)
            key = work / "separate-key"
            key.write_bytes(Fernet.generate_key())
            report = tool.backup(source, key_file=key, spool=work / "spool",
                                 destination=work / "destination")
            archive = work / "restored.dump"
            tool.decrypt(work / "destination" / report["artifact"], archive, key.read_bytes())
            assert tool.sha256(archive) == report["archive_sha256"]
            target.restore(archive, "af_restore_owner")
            original = snapshot(name, source.database)
            recovered = snapshot(name, target.database)
            assert original == recovered
            assert json.loads(recovered["alembic_version"])[0]["version_num"] == \
                "0007_accounts_ownership"
            owners = sql(name, target.database, "SELECT distinct tableowner FROM pg_tables "
                                               "WHERE schemaname='public'")
            assert owners == "af_restore_owner"
            tool.run(["docker", "run", "--rm", "--network", "container:" + name,
                      "-v", str(root / "backend") + ":/app:ro", "-w", "/app",
                      "-e", ("DATABASE_URL=postgresql+psycopg://fixture_admin@127.0.0.1:5432/"
                      "agentflow_restore_fixture"), args.app_image, "python", "-c",
                      ("from app.ownership import verify_account_readiness; "
                      "verify_account_readiness()")])
            report.update({"synthetic_restore_verified": True, "matching_tables": len(original),
                           "migration": "0007_accounts_ownership", "owner": owners,
                           "account_readiness_verified": True,
                           "destination": "temporary local filesystem", "fixture_network": "none"})
            Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report))
        return 0
    finally:
        if created:
            tool.run(["docker", "rm", "--force", name])


if __name__ == "__main__":
    sys.exit(main())
