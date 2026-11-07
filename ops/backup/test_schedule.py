import json
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
