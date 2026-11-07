"""Offline operational-tool tests; no application DB/settings fallback."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken

spec = importlib.util.spec_from_file_location("backup_tool", Path(__file__).with_name("backup.py"))
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def test_authenticated_roundtrip_and_tamper(tmp_path):
    source, encrypted, restored = [tmp_path / name for name in ("a", "b", "c")]
    source.write_bytes(bytes(range(256)) * 1000)
    key = Fernet.generate_key()
    tool.encrypt(source, encrypted, key)
    tool.decrypt(encrypted, restored, key)
    assert restored.read_bytes() == source.read_bytes()
    changed = bytearray(encrypted.read_bytes())
    changed[len(changed) // 2] ^= 1
    encrypted.write_bytes(changed)
    restored.unlink()
    with pytest.raises(InvalidToken):
        tool.decrypt(encrypted, restored, key)
    assert not restored.exists()


def test_wrong_key_and_overwrite_rejected(tmp_path):
    source, encrypted, restored = [tmp_path / name for name in ("a", "b", "c")]
    source.write_bytes(b"synthetic")
    tool.encrypt(source, encrypted, Fernet.generate_key())
    with pytest.raises(InvalidToken):
        tool.decrypt(encrypted, restored, Fernet.generate_key())
    with pytest.raises(FileExistsError):
        tool.encrypt(source, encrypted, Fernet.generate_key())


def test_delivery_atomic_hash_and_no_overwrite(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"synthetic")
    delivered = tool.deliver(source, tmp_path / "destination")
    assert tool.sha256(delivered) == tool.sha256(source)
    with pytest.raises(tool.BackupError):
        tool.deliver(source, tmp_path / "destination")
    assert not list((tmp_path / "destination").glob(".partial-*"))


def test_identity_rejects_wrong_database_user_and_version(monkeypatch):
    pg = tool.Postgres("agentflow_backup_fixture", "backup")
    for field, value in [("database", "production"), ("user", "admin"), ("version", 150000)]:
        identity = {"database": pg.database, "user": pg.user, "version": 160000}
        identity[field] = value
        monkeypatch.setattr(pg, "query", lambda _, identity=identity: json.dumps(identity))
        with pytest.raises(tool.BackupError):
            pg.identity()


def test_backup_key_separation_and_plaintext_cleanup(tmp_path):
    class FakePostgres:
        def identity(self):
            return {"database": "agentflow_backup_fixture", "user": "backup", "version": 160000}

        def dump(self, path):
            path.write_bytes(b"PGDMP synthetic binary \x00\xff")

        def verify(self, path):
            assert path.read_bytes().startswith(b"PGDMP")

    key = tmp_path / "key"
    key.write_bytes(Fernet.generate_key())
    with pytest.raises(tool.BackupError):
        tool.backup(FakePostgres(), key_file=key, spool=tmp_path,
                    destination=tmp_path / "destination")
    report = tool.backup(FakePostgres(), key_file=key, spool=tmp_path / "spool",
                         destination=tmp_path / "destination")
    assert report["off_host_verified"] is False
    assert not list((tmp_path / "spool").iterdir())
    assert len(list((tmp_path / "destination").iterdir())) == 2


def test_runtime_error_is_redacted(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["backup.py", "backup", "--database", "production",
                                    "--user", "private-user", "--key-file", "secret-key-path",
                                    "--spool", "private-spool"])
    assert tool.main() == 1
    assert "secret" not in capsys.readouterr().err


def test_restore_refuses_nonfixture_and_existing_tables(monkeypatch, tmp_path):
    pg = tool.Postgres("production", "operator")
    with pytest.raises(tool.BackupError):
        pg.restore(tmp_path / "not-opened")
    pg.database = "agentflow_restore_fixture"
    monkeypatch.setattr(pg, "identity", dict)
    monkeypatch.setattr(pg, "query", lambda _: "1")
    with pytest.raises(tool.BackupError):
        pg.restore(tmp_path / "not-opened")


def test_archive_size_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, "MAX_ARCHIVE_BYTES", 3)
    source = tmp_path / "source"
    source.write_bytes(b"four")
    with pytest.raises(tool.BackupError):
        tool.encrypt(source, tmp_path / "encrypted", Fernet.generate_key())


def test_client_timeout_and_sanitized_failure(monkeypatch, capsys):
    def timeout_run(args, **kwargs):
        assert kwargs["timeout"] == 1
        raise subprocess.TimeoutExpired("private-connection-detail", 1,
                                        stderr=b"private-secret")

    monkeypatch.setattr(tool.subprocess, "run", timeout_run)
    monkeypatch.setattr("sys.argv", ["backup.py", "backup", "--database", "agentflow_backup_test",
                                    "--user", "backup", "--key-file", "not-read",
                                    "--spool", "not-read", "--destination", "not-read",
                                    "--command-timeout-seconds", "1"])
    assert tool.main() == 1
    output = capsys.readouterr()
    assert "private" not in output.err
    assert "failed" in output.err


def test_client_timeout_must_be_positive():
    with pytest.raises(tool.BackupError):
        tool.Postgres("agentflow_backup_test", "backup", timeout_seconds=0)
