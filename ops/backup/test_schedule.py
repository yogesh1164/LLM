import json
import hashlib
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import schedule


def config(tmp_path, enabled=False):
    return {"enabled": enabled, "status_dir": str(tmp_path / "status"),
            "database": "agentflow_backup_fixture", "user": "backup", "host": "localhost",
            "key_file": "protected-key", "spool": str(tmp_path / "spool"),
            "destination": str(tmp_path / "destination"),
            "remote_folder": "AgentFlow-AI-Encrypted-Backups"}


def test_schedule_disabled_by_default_does_not_invoke_tools(tmp_path):
    called = []
    result = schedule.run(config(tmp_path), runner=lambda *a, **k: called.append(a))
    assert result == {"status": "disabled"}
    assert called == []
    assert not (tmp_path / "status").exists()


def test_scheduled_success_calls_backup_upload_and_monitor(tmp_path, monkeypatch):
    cfg = config(tmp_path, enabled=True)
    artifact = Path(cfg["destination"]) / ("agentflow-20261107T000000Z-" + "0" * 32 + ".age")
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"age")
    manifest = {"artifact": artifact.name, "ciphertext_sha256": "abc"}
    runner_calls = []
    def runner(command, **kwargs):
        runner_calls.append(command)
        return type("Result", (), {"returncode": 0, "stdout": json.dumps(manifest).encode()})()
    uploaded = []
    monkeypatch.setattr(schedule.rclone_offhost, "upload", lambda *a, **k: uploaded.append((a, k)))
    monkeypatch.setattr(schedule.monitor, "check", lambda *a: {"delivery_fresh": True})
    result = schedule.run(cfg, runner=runner, now=datetime(2026, 11, 7, tzinfo=UTC))
    assert result["status"] == "success"
    assert len(runner_calls) == len(uploaded) == 1
    assert runner_calls[0][-1] == "--allow-production-read"
    assert json.loads((Path(cfg["status_dir"]) / "schedule.jsonl").read_text())["status"] == "success"


def test_failure_is_logged_and_notified_without_secrets(tmp_path, monkeypatch):
    cfg = config(tmp_path, enabled=True)
    alerts = []
    monkeypatch.setattr(schedule, "_notify", lambda message, environ: alerts.append(message) or True)
    result = schedule.run(cfg, runner=lambda *a, **k: (_ for _ in ()).throw(OSError("secret")),
                          environ={"AGENTFLOW_BACKUP_ALERT_WEBHOOK": "https://example.invalid"})
    assert result["status"] == "failed"
    assert result["alert_sent"] is True
    assert len(alerts) == 1
    log = (Path(cfg["status_dir"]) / "schedule.jsonl").read_text()
    assert "secret" not in log
    assert "failed" in log


def test_example_config_is_disabled():
    path = Path(__file__).with_name("schedule.example.json")
    assert json.loads(path.read_text())["enabled"] is False


def test_invalid_config_fails_closed_before_job(tmp_path, monkeypatch, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"enabled": "yes"}')
    monkeypatch.setattr("sys.argv", ["schedule.py", "--config", str(path)])
    assert schedule.main() == 1
    assert "invalid" in capsys.readouterr().err


def test_failed_backup_notifies_and_preserves_last_valid_backup(tmp_path, monkeypatch):
    cfg = config(tmp_path, enabled=True)
    destination = Path(cfg["destination"])
    destination.mkdir()
    old = destination / ("agentflow-20261106T000000Z-" + "1" * 32 + ".age")
    old.write_bytes(b"age: previously verified ciphertext")
    old_hash = hashlib.sha256(old.read_bytes()).hexdigest()
    alerts, uploads = [], []
    monkeypatch.setattr(schedule, "_notify", lambda message, env: alerts.append(message) or True)
    monkeypatch.setattr(schedule.rclone_offhost, "upload", lambda *a, **k: uploads.append(a))
    def failed(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "backup", stderr=b"sensitive connection string")
    result = schedule.run(cfg, runner=failed,
                          environ={"AGENTFLOW_BACKUP_ALERT_WEBHOOK": "configured"})
    assert result["status"] == "failed"
    assert result["alert_sent"] is True and len(alerts) == 1 and not uploads
    assert hashlib.sha256(old.read_bytes()).hexdigest() == old_hash
    log = (Path(cfg["status_dir"]) / "schedule.jsonl").read_text()
    assert "sensitive" not in log


def test_upload_failure_preserves_existing_verified_artifact(tmp_path, monkeypatch):
    cfg = config(tmp_path, enabled=True)
    destination = Path(cfg["destination"])
    destination.mkdir()
    old = destination / ("agentflow-20261106T000000Z-" + "2" * 32 + ".age")
    old.write_bytes(b"old verified ciphertext")
    old_bytes = old.read_bytes()
    new = "agentflow-20261107T000000Z-" + "3" * 32 + ".age"
    manifest = {"artifact": new, "ciphertext_sha256": "new-hash"}
    def runner(command, **kwargs):
        (destination / new).write_bytes(b"age-encrypted synthetic")
        return type("Result", (), {"returncode": 0, "stdout": json.dumps(manifest).encode()})()
    def upload(*args, **kwargs):
        raise schedule.rclone_offhost.TransferError("private diagnostic")
    alerts = []
    monkeypatch.setattr(schedule.rclone_offhost, "upload", upload)
    monkeypatch.setattr(schedule, "_notify", lambda message, env: alerts.append(message) or False)
    result = schedule.run(cfg, runner=runner,
                          environ={"AGENTFLOW_BACKUP_ALERT_WEBHOOK": "configured"})
    assert result["status"] == "failed" and result["alert_sent"] is False
    assert old.read_bytes() == old_bytes
    assert "private" not in (Path(cfg["status_dir"]) / "schedule.jsonl").read_text()
    assert len(alerts) == 1


def test_expired_freshness_is_a_failure(tmp_path, monkeypatch):
    cfg = config(tmp_path, enabled=True)
    destination = Path(cfg["destination"])
    destination.mkdir()
    artifact = "agentflow-20261107T000000Z-" + "4" * 32 + ".age"
    manifest = {"artifact": artifact, "ciphertext_sha256": "hash"}
    monkeypatch.setattr(schedule.rclone_offhost, "upload", lambda *a, **k: None)
    monkeypatch.setattr(schedule.monitor, "check", lambda *a: (_ for _ in ()).throw(
        schedule.backup.BackupError("stale backup")))
    def runner(command, **kwargs):
        (destination / artifact).write_bytes(b"synthetic ciphertext")
        return type("Result", (), {"returncode": 0, "stdout": json.dumps(manifest).encode()})()
    alerts = []
    monkeypatch.setattr(schedule, "_notify", lambda message, env: alerts.append(message) or True)
    result = schedule.run(cfg, runner=runner, environ={"AGENTFLOW_BACKUP_ALERT_WEBHOOK": "configured"})
    assert result["status"] == "failed" and result["alert_sent"] is True
    assert len(alerts) == 1


def test_synthetic_encryption_precedes_upload(tmp_path, monkeypatch):
    age = Path(__file__).parents[2] / "backups/v2-age-tools/bin/age/age.exe"
    keygen = age.with_name("age-keygen.exe")
    if not age.exists() or not keygen.exists():
        import pytest
        pytest.skip("Verified age test binaries are unavailable")
    cfg = config(tmp_path, enabled=True)
    destination = Path(cfg["destination"])
    destination.mkdir()
    identity = tmp_path / "identity"
    subprocess.run([str(keygen), "-o", str(identity)], check=True, capture_output=True)
    recipient = next(line.split(":", 1)[1].strip() for line in identity.read_text().splitlines()
                     if line.startswith("# public key:"))
    class SyntheticPostgres:
        timeout = 30
        def identity(self):
            return {"database": "agentflow_backup_fixture", "user": "backup", "version": 160000}
        def dump(self, path):
            path.write_bytes(b"SYNTHETIC-ONLY-PLAINTEXT-MARKER")
        def verify(self, path):
            assert path.read_bytes().startswith(b"SYNTHETIC-ONLY-PLAINTEXT-MARKER")
    observed = []
    def runner(command, **kwargs):
        manifest = schedule.backup.backup(SyntheticPostgres(), key_file=identity,
                                          spool=cfg["spool"], destination=destination,
                                          encryption="age", age_binary=str(age))
        return type("Result", (), {"returncode": 0, "stdout": json.dumps(manifest).encode()})()
    def upload(path, **kwargs):
        data = Path(path).read_bytes()
        assert data.startswith(b"age-encryption.org/v1\n")
        assert b"SYNTHETIC-ONLY-PLAINTEXT-MARKER" not in data
        observed.append(True)
    monkeypatch.setattr(schedule.rclone_offhost, "upload", upload)
    result = schedule.run(cfg, runner=runner)
    assert result["status"] == "success" and observed == [True]
    assert not list(Path(cfg["spool"]).glob("**/database.dump"))
    assert all(path.suffix in {".age", ".json"} for path in destination.iterdir())
