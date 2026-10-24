import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import backup as tool
import retention


def create_set(root, created, index):
    name = created.strftime("agentflow-%Y%m%dT%H%M%SZ-") + f"{index:032x}.age"
    artifact = root / name
    artifact.write_bytes(b"synthetic-encrypted-placeholder")
    manifest = artifact.with_suffix(".json")
    manifest.write_text(json.dumps({"artifact": name, "created_utc": created.isoformat(),
                                   "ciphertext_sha256": tool.sha256(artifact)}))
    return artifact, manifest


def test_retention_default_is_dry_run_and_preserves_newest_and_monthly(tmp_path, monkeypatch, capsys):
    now = datetime.now(UTC)
    sets = [create_set(tmp_path, now - timedelta(days=day), index)
            for index, day in enumerate((1, 2, 40, 41, 42, 80, 81))]
    _, expired = retention.plan(tmp_path, now=now)
    assert sets[0][0] not in [row[1] for row in expired]
    assert sets[1][0] not in [row[1] for row in expired]
    assert len(expired) >= 2
    monkeypatch.setattr("sys.argv", ["retention.py", "--destination", str(tmp_path)])
    assert retention.main() == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert all(artifact.exists() and manifest.exists() for artifact, manifest in sets)


def test_retention_execution_requires_exact_confirmation(tmp_path, monkeypatch):
    create_set(tmp_path, datetime.now(UTC) - timedelta(days=60), 1)
    monkeypatch.setattr("sys.argv", ["retention.py", "--destination", str(tmp_path),
                                    "--execute-local-prune"])
    assert retention.main() == 1
    assert len(list(tmp_path.iterdir())) == 2


def test_retention_refuses_corrupt_archive_and_preserves_other_files(tmp_path):
    artifact, _ = create_set(tmp_path, datetime.now(UTC) - timedelta(days=60), 1)
    artifact.write_bytes(b"corrupted")
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("preserved")
    with pytest.raises(tool.BackupError):
        retention.plan(tmp_path)
    assert unrelated.read_text() == "preserved"


def test_explicit_retention_only_deletes_planned_synthetic_pairs(tmp_path, monkeypatch, capsys):
    now = datetime.now(UTC)
    sets = [create_set(tmp_path, now - timedelta(days=day), index)
            for index, day in enumerate((1, 2, 40, 41, 42, 80, 81))]
    _, expired = retention.plan(tmp_path, now=now)
    expiring = {row[1].name for row in expired}
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("preserved")
    monkeypatch.setattr("sys.argv", ["retention.py", "--destination", str(tmp_path),
                                    "--execute-local-prune", "--confirm-destination", str(tmp_path),
                                    "--confirm-action", retention.CONFIRMATION])
    assert retention.main() == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is False
    for artifact, manifest in sets:
        assert artifact.exists() == (artifact.name not in expiring)
        assert manifest.exists() == (artifact.name not in expiring)
    assert unrelated.read_text() == "preserved"
