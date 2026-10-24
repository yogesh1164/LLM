"""Check destination delivery freshness and checksum without reading encryption keys.

Exit 0 means recent delivered bytes match a manifest, not a successful restore or
off-host attestation. Scheduler must alert on nonzero exit and missing executions.
"""
import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import backup as tool


def check(destination, max_age_hours=26, now=None):
    now = now or datetime.now(UTC)
    if max_age_hours <= 0:
        raise tool.BackupError("Invalid freshness interval")
    valid = []
    for path in Path(destination).glob("agentflow-*.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        artifact_name = manifest["artifact"]
        if (Path(artifact_name).name != artifact_name
                or not artifact_name.endswith((".age", ".fernet"))):
            raise tool.BackupError("Invalid artifact path")
        artifact = path.parent / artifact_name
        created = datetime.fromisoformat(manifest["created_utc"])
        if (created.tzinfo is None or created > now + timedelta(minutes=5)
                or tool.sha256(artifact) != manifest["ciphertext_sha256"]):
            raise tool.BackupError("Destination checksum or timestamp failed")
        valid.append(created)
    if not valid or now - max(valid) > timedelta(hours=max_age_hours):
        raise tool.BackupError("Backup missing or stale")
    return {"delivery_fresh": True, "latest_utc": max(valid).isoformat(),
            "off_host_verified": False, "restore_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--max-age-hours", type=float, default=26)
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.destination, args.max_age_hours)))
        return 0
    except (tool.BackupError, OSError, ValueError, KeyError, TypeError):
        print("Backup monitoring failed; alert operator", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
