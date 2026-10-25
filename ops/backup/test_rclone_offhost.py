"""Local-only rclone adapter tests; no rclone config, token or network is used."""
import json
import subprocess
from hashlib import sha256

import pytest
import rclone_offhost as adapter


def encrypted(directory, data=b"synthetic encrypted payload"):
    path = directory / "agentflow-20261024T120000Z-0123456789abcdef0123456789abcdef.age"
    path.write_bytes(adapter.AGE_HEADER + data)
    directory.joinpath(path.stem + ".json").write_text(json.dumps({
        "format": 2, "encryption": "age/X25519", "artifact": path.name,
        "ciphertext_sha256": sha256(path.read_bytes()).hexdigest()}))
    return path


def test_upload_only_age_and_full_readback_check(tmp_path):
    artifact = encrypted(tmp_path)
    calls = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    report = tmp_path / "status.json"
    result = adapter.upload(artifact, folder="restricted/backups", runner=runner,
                            report_path=report)
    assert result["status"] == "verified"
    assert result["integrity_verified"] is True
    assert len(calls) == 2
    assert calls[0][0][1] == "copyto"
    assert calls[0][0][2:4] == ["--immutable", "--no-traverse"]
    assert calls[0][0][-1] == f"agentflow-gdrive:restricted/backups/{artifact.name}"
    assert calls[1][0][1:4] == ["check", "--download", "--one-way"]
    assert calls[1][0][4:] == [str(tmp_path), "agentflow-gdrive:restricted/backups",
                              "--include", "/" + artifact.name]
    assert json.loads(report.read_text()) == result


@pytest.mark.parametrize("name,data", [("dump.sql", b"plaintext"),
                                        ("bad.age", b"not age ciphertext")])
def test_refuses_non_age_or_plaintext_before_runner(tmp_path, name, data):
    artifact = tmp_path / name
    artifact.write_bytes(data)
    called = []
    with pytest.raises(adapter.TransferError):
        adapter.upload(artifact, folder="backup", runner=lambda *a, **k: called.append(a))
    assert not called


@pytest.mark.parametrize("folder", ["../other", "/absolute", "a\\b", "a//b", "a:drive"])
def test_rejects_unsafe_remote_path(tmp_path, folder):
    artifact = encrypted(tmp_path)
    with pytest.raises(adapter.TransferError):
        adapter.upload(artifact, folder=folder, runner=lambda *a, **k: None)


def test_reports_failed_remote_command_without_echoing_diagnostics(tmp_path):
    artifact = encrypted(tmp_path)
    report = tmp_path / "status.json"

    def runner(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"synthetic-redacted-diagnostic")

    with pytest.raises(adapter.TransferError, match="failed"):
        adapter.upload(artifact, folder="backups", runner=runner, report_path=report)
    value = json.loads(report.read_text())
    assert value["status"] == "failed"
    assert value["integrity_verified"] is False
    assert "synthetic-redacted-diagnostic" not in report.read_text()


def test_detects_source_change_during_transfer(tmp_path):
    artifact = encrypted(tmp_path)
    calls = 0

    def runner(args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            artifact.write_bytes(adapter.AGE_HEADER + b"changed")
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    with pytest.raises(adapter.TransferError, match="changed"):
        adapter.upload(artifact, folder="backups", runner=runner)
