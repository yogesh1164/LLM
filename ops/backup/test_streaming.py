import os
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).parent))
import backup as tool
import make_key


@pytest.fixture
def age_tools(tmp_path):
    binary = os.environ.get("AGENTFLOW_TEST_AGE_BINARY")
    keygen = os.environ.get("AGENTFLOW_TEST_AGE_KEYGEN")
    if not binary or not keygen:
        pytest.skip("Explicit test age/age-keygen paths not supplied")
    key = tmp_path / "identity"
    make_key.create(key, format="age", age_keygen=keygen)
    return binary, key


def test_age_roundtrip_and_detected_legacy_decryption(tmp_path, age_tools):
    binary, key = age_tools
    source, encrypted, restored = [tmp_path / name for name in ("plain", "archive.age", "restored")]
    source.write_bytes(os.urandom(200_000))
    tool.age_transform(source, encrypted, key, age_binary=binary)
    tool.decrypt_archive(encrypted, restored, key, age_binary=binary)
    assert tool.sha256(source) == tool.sha256(restored)
    legacy_key = tmp_path / "legacy-key"
    legacy_key.write_bytes(Fernet.generate_key())
    legacy_archive = tmp_path / "legacy.fernet"
    tool.encrypt(source, legacy_archive, legacy_key.read_bytes())
    legacy_plain = tmp_path / "legacy-restored"
    tool.decrypt_archive(legacy_archive, legacy_plain, legacy_key)
    assert tool.sha256(source) == tool.sha256(legacy_plain)


@pytest.mark.parametrize("damage", ["middle", "truncate", "append", "wrong-key"])
def test_age_authentication_failure_never_publishes_plaintext(tmp_path, age_tools, damage):
    binary, key = age_tools
    source, encrypted, restored = [tmp_path / name for name in ("plain", "archive.age", "restored")]
    source.write_bytes(os.urandom(200_000))
    tool.age_transform(source, encrypted, key, age_binary=binary)
    ciphertext = bytearray(encrypted.read_bytes())
    if damage == "middle":
        ciphertext[len(ciphertext) // 2] ^= 1
    elif damage == "truncate":
        del ciphertext[-1:]
    elif damage == "append":
        ciphertext += b"extra"
    else:
        other = tmp_path / "other-identity"
        # Native key generation is a maintained external implementation.
        make_key.create(other, format="age", age_keygen=os.environ["AGENTFLOW_TEST_AGE_KEYGEN"])
        key = other
    encrypted.write_bytes(ciphertext)
    with pytest.raises(tool.BackupError):
        tool.decrypt_archive(encrypted, restored, key, age_binary=binary)
    assert not restored.exists()
    assert not list(tmp_path.glob(".crypto-partial-*"))


def test_age_no_overwrite_and_no_legacy_fallback(tmp_path, age_tools):
    binary, key = age_tools
    source, encrypted = tmp_path / "plain", tmp_path / "archive.age"
    source.write_bytes(b"synthetic")
    encrypted.write_bytes(b"already-here")
    with pytest.raises(tool.BackupError):
        tool.age_transform(source, encrypted, key, age_binary=binary)
    assert encrypted.read_bytes() == b"already-here"
    with pytest.raises(tool.BackupError):
        tool.decrypt_archive(encrypted, tmp_path / "plain2", key, age_binary=binary)


def test_failed_age_process_removes_partial_output(tmp_path, monkeypatch):
    key, source, target = [tmp_path / name for name in ("key", "source", "target")]
    key.write_bytes(b"AGE-SECRET-KEY-1synthetic-not-used")
    source.write_bytes(b"synthetic")

    def fail(args, **kwargs):
        kwargs["output"].write(b"unauthenticated-partial-plaintext")
        raise tool.BackupError("simulated failure")

    monkeypatch.setattr(tool, "run", fail)
    with pytest.raises(tool.BackupError):
        tool.age_transform(source, target, key, decrypting=True)
    assert not target.exists()
    assert not list(tmp_path.glob(".crypto-partial-*"))
