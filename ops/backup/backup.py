"""Explicit-identity PostgreSQL backups. No shell, password arguments or dotenv loading.

Fernet is the cryptography project's authenticated-encryption recipe. This adapter
intentionally caps archives at 256 MiB because Fernet operates in memory.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken

MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


class BackupError(Exception):
    pass


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(args, *, output=None, input_file=None, timeout=300):
    # Never echo subprocess stderr: libpq diagnostics can include connection data.
    result = subprocess.run(args, stdout=output or subprocess.PIPE,
                            stdin=input_file, stderr=subprocess.PIPE, check=False, timeout=timeout)
    if result.returncode:
        raise BackupError("PostgreSQL/client command failed; inspect protected local diagnostics")
    return result.stdout


class Postgres:
    def __init__(self, database, user, host="127.0.0.1", port=5432, container=None,
                 timeout_seconds=300):
        if timeout_seconds <= 0:
            raise BackupError("Client timeout must be positive")
        self.timeout = timeout_seconds
        self.database = database
        self.user = user
        self.prefix = ["docker", "exec", "-i", container] if container else []
        self.connection = ["--host", host, "--port", str(port), "--username", user,
                           "--dbname", database, "--no-password"]

    def command(self, binary, *args):
        return [*self.prefix, binary, *self.connection, *args]

    def query(self, sql):
        return run(self.command("psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
                                "-c", sql), timeout=self.timeout).decode().strip()

    def identity(self):
        result = json.loads(self.query("SELECT json_build_object('database', current_database(),"
                                      "'user', current_user, 'version',"
                                      "current_setting('server_version_num')::integer)"))
        if (result["database"] != self.database or result["user"] != self.user
                or result["version"] // 10000 != 16):
            raise BackupError("Database identity or PostgreSQL major version mismatch")
        return result

    def dump(self, path):
        missing = int(self.query("SELECT count(*) FROM pg_class c JOIN pg_namespace n "
                                "ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' "
                                "AND n.nspname <> 'information_schema' AND c.relkind IN ('r','p') "
                                "AND NOT has_table_privilege(c.oid,'SELECT')"))
        if missing:
            raise BackupError("Backup role lacks SELECT on application tables")
        with Path(path).open("xb") as stream:
            run(self.command("pg_dump", "--format=custom", "--lock-wait-timeout=30s"),
                output=stream, timeout=self.timeout)

    def verify(self, path):
        with Path(path).open("rb") as stream:
            # Archive validation does not connect to the database.
            run([*self.prefix, "pg_restore", "--list"], input_file=stream, timeout=self.timeout)

    def restore(self, path, owner=None):
        if not self.database.startswith("agentflow_restore_"):
            raise BackupError("Restore target must start with agentflow_restore_")
        self.identity()
        count = int(self.query("SELECT sum(objects) FROM ("
                               "SELECT count(*) AS objects FROM pg_class c JOIN pg_namespace n "
                               "ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' "
                               "AND n.nspname <> 'information_schema' UNION ALL "
                               "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
                               "ON n.oid=p.pronamespace WHERE n.nspname NOT LIKE 'pg_%' "
                               "AND n.nspname <> 'information_schema' UNION ALL "
                               "SELECT count(*) FROM pg_type t JOIN pg_namespace n "
                               "ON n.oid=t.typnamespace WHERE n.nspname NOT LIKE 'pg_%' "
                               "AND n.nspname <> 'information_schema' "
                               "AND t.typtype IN ('e','d','c','r','m')) AS user_objects"))
        if count:
            raise BackupError("Restore target is not empty")
        args = ["--exit-on-error", "--single-transaction", "--no-owner", "--no-acl"]
        if owner:
            args += ["--role", owner]
        with Path(path).open("rb") as stream:
            run(self.command("pg_restore", *args), input_file=stream, timeout=self.timeout)


def encrypt(archive, encrypted, key):
    if Path(archive).stat().st_size > MAX_ARCHIVE_BYTES:
        raise BackupError("Archive exceeds tested 256 MiB Fernet memory limit")
    with Path(encrypted).open("xb") as stream:
        stream.write(Fernet(key).encrypt(Path(archive).read_bytes()))


def decrypt(encrypted, archive, key):
    if Path(encrypted).stat().st_size > (MAX_ARCHIVE_BYTES * 4 // 3 + 4096):
        raise BackupError("Encrypted archive exceeds supported size")
    plaintext = Fernet(key).decrypt(Path(encrypted).read_bytes())
    with Path(archive).open("xb") as stream:
        stream.write(plaintext)


def deliver(source, destination):
    """Local/OS-mounted destination adapter; never reports off-host attestation."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / Path(source).name
    if target.exists():
        raise BackupError("Destination artifact already exists")
    temporary = destination / (".partial-" + uuid4().hex)
    try:
        with Path(source).open("rb") as reader, temporary.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        if sha256(source) != sha256(temporary):
            raise BackupError("Destination checksum mismatch")
        # Hard-link publication refuses overwrite even under concurrent delivery.
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def backup(pg, *, key_file, spool, destination):
    identity = pg.identity()
    key_file, spool, destination = (Path(p).resolve() for p in (key_file, spool, destination))
    if key_file.is_relative_to(spool) or key_file.is_relative_to(destination):
        raise BackupError("Key must be stored separately from spool and destination")
    key = key_file.read_bytes().strip()
    Fernet(key)
    spool.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agentflow-backup-", dir=spool) as work:
        work = Path(work)
        archive = work / "database.dump"
        pg.dump(archive)
        pg.verify(archive)
        name = datetime.now(UTC).strftime("agentflow-%Y%m%dT%H%M%SZ-") + uuid4().hex
        encrypted = work / (name + ".fernet")
        encrypt(archive, encrypted, key)
        restored = work / "verified.dump"
        decrypt(encrypted, restored, key)
        if sha256(archive) != sha256(restored):
            raise BackupError("Decrypted archive checksum mismatch")
        pg.verify(restored)
        manifest = {"format": 1, "created_utc": datetime.now(UTC).isoformat(),
                    "identity": identity, "archive_sha256": sha256(archive),
                    "ciphertext_sha256": sha256(encrypted), "artifact": encrypted.name,
                    "encryption": "cryptography.Fernet", "delivery_adapter": "filesystem",
                    "off_host_verified": False}
        # The manifest is informational. Authentication is verified by Fernet;
        # untrusted checksum metadata alone must never authorize a restore.
        report = work / (name + ".json")
        report.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        delivered = deliver(encrypted, destination)
        deliver(report, destination)
        if sha256(delivered) != manifest["ciphertext_sha256"]:
            raise BackupError("Final destination checksum mismatch")
        return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("--database", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--command-timeout-seconds", type=int, default=300)
    parser.add_argument("--container")
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--spool", required=True)
    parser.add_argument("--destination")
    parser.add_argument("--artifact")
    parser.add_argument("--execute-restore", action="store_true")
    parser.add_argument("--restore-owner")
    parser.add_argument("--allow-production-read", action="store_true")
    args = parser.parse_args()
    try:
        if (not args.database.startswith(("agentflow_backup_", "agentflow_restore_"))
                and (args.action != "backup" or not args.allow_production_read)):
            raise BackupError("Non-fixture backup requires --allow-production-read")
        pg = Postgres(args.database, args.user, args.host, args.port, args.container,
                      args.command_timeout_seconds)
        if args.action == "backup":
            if not args.destination:
                raise BackupError("Destination required")
            result = backup(pg, key_file=args.key_file, spool=args.spool,
                            destination=args.destination)
        else:
            if not args.execute_restore or not args.artifact:
                raise BackupError("Restore needs --execute-restore and --artifact")
            spool = Path(args.spool)
            spool.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=spool) as work:
                archive = Path(work) / "restore.dump"
                decrypt(args.artifact, archive, Path(args.key_file).read_bytes().strip())
                pg.verify(archive)
                pg.restore(archive, args.restore_owner)
            result = {"restored": True, "identity": pg.identity()}
        print(json.dumps(result))
        return 0
    except (BackupError, OSError, ValueError, KeyError, TypeError, InvalidToken,
            subprocess.SubprocessError):
        # No traceback, connection strings, secret paths or tool stderr in logs.
        print("Backup/restore failed; no success attestation produced", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
