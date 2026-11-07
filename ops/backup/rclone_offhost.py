"""Upload age artifacts from the verified backup pipeline through rclone.

This adapter never reads rclone configuration and never accepts plaintext input.
Errors from rclone are deliberately discarded because remote diagnostics may
include account or configuration details.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

REMOTE_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
ARTIFACT_NAME = re.compile(r"agentflow-\d{8}T\d{6}Z-[a-f0-9]{32}\.age\Z")
AGE_HEADER = b"age-encryption.org/v1\n"


class TransferError(Exception):
    pass


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate(source, manifest_path, remote, folder):
    source = Path(source)
    if source.is_symlink():
        raise TransferError("Only a regular encrypted .age artifact can be transferred")
    source = source.resolve(strict=True)
    if not source.is_file() or not ARTIFACT_NAME.fullmatch(source.name):
        raise TransferError("Only a regular encrypted .age artifact can be transferred")
    with source.open("rb") as stream:
        if stream.read(len(AGE_HEADER)) != AGE_HEADER:
            raise TransferError("Artifact does not have the age ciphertext header")
    if not REMOTE_NAME.fullmatch(remote):
        raise TransferError("Invalid rclone remote name")
    manifest_path = Path(manifest_path)
    if manifest_path.is_symlink() or manifest_path.resolve(strict=True) != source.with_suffix(".json"):
        raise TransferError("Matching local backup manifest is required")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("format") != 2 or manifest.get("encryption") != "age/X25519"
            or manifest.get("artifact") != source.name
            or manifest.get("ciphertext_sha256") != sha256(source)):
        raise TransferError("Backup manifest does not match the ciphertext file")
    path = PurePosixPath(folder)
    if (not folder or folder.startswith("/") or ".." in path.parts
            or "\\" in folder or ":" in folder or any(part in {"", "."} for part in folder.split("/"))):
        raise TransferError("Destination folder must be a relative remote path")
    return source, f"{remote}:{path.as_posix()}/{source.name}"


def _invoke(rclone, args, runner):
    try:
        result = runner([rclone, *args], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, check=False, timeout=3600)
    except (OSError, subprocess.SubprocessError) as exc:
        raise TransferError("rclone transfer or verification failed") from exc
    if result.returncode:
        raise TransferError("rclone transfer or verification failed")
    return result.stdout


def upload(source, *, manifest=None, remote="agentflow-gdrive", folder, rclone="rclone",
           runner=subprocess.run, report_path=None):
    """Copy one encrypted file and verify by downloading/comparing both streams.

    The caller must invoke this only after the remote has been authenticated.
    The function itself does not run config/authentication commands.
    """
    # A prior verified report must never be mistaken for this attempt's result.
    if report_path and Path(report_path).exists():
        raise TransferError("Transfer report path already exists")
    source_path = Path(source)
    manifest = manifest or source_path.with_suffix(".json")
    source, target = validate(source, manifest, remote, folder)
    digest = sha256(source)
    result = {"status": "failed", "artifact": source.name, "sha256": digest,
              "remote_object": target, "integrity_verified": False,
              "retention_policy": "operator-managed; remote deletion disabled"}
    if report_path:
        with Path(report_path).open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, sort_keys=True) + "\n")
    _invoke(rclone, ["copyto", "--immutable", "--no-traverse", str(source), target], runner)
    # --download forces a full content readback, independent of remote hash support.
    remote_folder = target.rsplit("/", 1)[0]
    _invoke(rclone, ["check", "--download", "--one-way", str(source.parent),
                     remote_folder, "--include", "/" + source.name], runner)
    if sha256(source) != digest:
        raise TransferError("Source ciphertext changed during transfer")
    result.update(status="verified", integrity_verified=True)
    if report_path:
        Path(report_path).write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact")
    parser.add_argument("--manifest", help="matching local manifest; defaults to the artifact .json sidecar")
    parser.add_argument("--remote", default="agentflow-gdrive")
    parser.add_argument("--folder", required=True, help="operator-configured path within the remote")
    parser.add_argument("--rclone", default="rclone")
    parser.add_argument("--report", required=True, help="protected local transfer status JSON path")
    args = parser.parse_args()
    try:
        print(json.dumps(upload(args.artifact, manifest=args.manifest, remote=args.remote, folder=args.folder,
                                rclone=args.rclone, report_path=args.report), sort_keys=True))
        return 0
    except (TransferError, OSError, ValueError):
        print("Encrypted off-host transfer failed; no success attestation produced", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
