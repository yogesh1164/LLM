import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import backup as tool

spec = importlib.util.spec_from_file_location("backup_monitor", Path(__file__).with_name("monitor.py"))
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)
spec = importlib.util.spec_from_file_location("backup_key", Path(__file__).with_name("make_key.py"))
key_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(key_tool)


def test_key_creation_does_not_overwrite(tmp_path):
    path = tmp_path / "key"
    key_tool.create(path)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        key_tool.create(path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("suffix", [".fernet", ".age"])
def test_monitor_fresh_stale_missing_and_corrupt(tmp_path, suffix):
    now = datetime.now(UTC)
    with pytest.raises(tool.BackupError):
        monitor.check(tmp_path, now=now)
    artifact = tmp_path / ("agentflow-example" + suffix)
    artifact.write_bytes(b"synthetic-encrypted-placeholder")
    manifest = {"artifact": artifact.name, "created_utc": now.isoformat(),
                "ciphertext_sha256": tool.sha256(artifact)}
    (tmp_path / "agentflow-example.json").write_text(json.dumps(manifest))
    assert monitor.check(tmp_path, now=now)["delivery_fresh"] is True
    with pytest.raises(tool.BackupError):
        monitor.check(tmp_path, now=now + timedelta(hours=27))
    artifact.write_bytes(b"corrupted")
    with pytest.raises(tool.BackupError):
        monitor.check(tmp_path, now=now)


def test_monitor_rejects_path_escape(tmp_path):
    (tmp_path / "agentflow-example.json").write_text(json.dumps({"artifact": "../escape.fernet"}))
    with pytest.raises(tool.BackupError):
        monitor.check(tmp_path)


def test_monitor_malformed_json_fails_without_traceback(tmp_path, monkeypatch, capsys):
    (tmp_path / "agentflow-broken.json").write_text('{"private-invalid-data":')
    monkeypatch.setattr("sys.argv", ["monitor.py", "--destination", str(tmp_path)])
    assert monitor.main() == 1
    output = capsys.readouterr()
    assert "private" not in output.err
    assert "alert operator" in output.err
