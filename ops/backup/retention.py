"""Plan encrypted-archive retention; deletion requires two explicit operator flags."""
import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import backup as tool

ARTIFACT = re.compile(r"agentflow-\d{8}T\d{6}Z-[a-f0-9]{32}\.(age|fernet)\Z")
CONFIRMATION = "DELETE_EXPIRED_ENCRYPTED_BACKUPS"


def plan(destination, *, daily_days=30, monthly_count=12, minimum_sets=2, now=None):
    if daily_days < 1 or monthly_count < 1 or minimum_sets < 2:
        raise tool.BackupError("Retention must protect daily/monthly points and at least two sets")
    destination = Path(destination).resolve(strict=True)
    now = now or datetime.now(UTC)
    sets = []
    for manifest_path in destination.glob("agentflow-*.json"):
        if manifest_path.is_symlink():
            raise tool.BackupError("Retention refuses symlinks")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        name = manifest["artifact"]
        if not ARTIFACT.fullmatch(name) or manifest_path.stem != Path(name).stem:
            raise tool.BackupError("Invalid archive/manifest pairing")
        archive = destination / name
        if archive.is_symlink() or tool.sha256(archive) != manifest["ciphertext_sha256"]:
            raise tool.BackupError("Retention requires intact, regular archive files")
        created = datetime.fromisoformat(manifest["created_utc"])
        if created.tzinfo is None or created > now + timedelta(minutes=5):
            raise tool.BackupError("Invalid archive creation timestamp")
        sets.append((created, archive, manifest_path, manifest["ciphertext_sha256"]))
    sets.sort(key=lambda row: row[0], reverse=True)
    protected = {row[1].name for row in sets[:minimum_sets]}
    months = set()
    for row in sets:
        month = (row[0].year, row[0].month)
        if month not in months and len(months) < monthly_count:
            months.add(month)
            protected.add(row[1].name)
    expired = [row for row in sets if row[0] < now - timedelta(days=daily_days)
               and row[1].name not in protected]
    return destination, expired


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--daily-days", type=int, default=30)
    parser.add_argument("--monthly-count", type=int, default=12)
    parser.add_argument("--execute-local-prune", action="store_true")
    parser.add_argument("--confirm-destination")
    parser.add_argument("--confirm-action")
    args = parser.parse_args()
    try:
        root, expired = plan(args.destination, daily_days=args.daily_days,
                             monthly_count=args.monthly_count)
        if args.execute_local_prune:
            if (args.confirm_action != CONFIRMATION or not args.confirm_destination
                    or Path(args.confirm_destination).resolve(strict=True) != root):
                raise tool.BackupError("Explicit action and exact destination confirmation required")
            for _, artifact, manifest, expected_hash in expired:
                if artifact.is_symlink() or tool.sha256(artifact) != expected_hash:
                    raise tool.BackupError("Archive changed since retention planning")
                # Only the exact previously validated pair inside the confirmed root.
                artifact.unlink()
                manifest.unlink()
        print(json.dumps({"dry_run": not args.execute_local_prune,
                          "expired_sets": [row[1].name for row in expired],
                          "operator_legal_hold_review_required": True}))
        return 0
    except (tool.BackupError, OSError, ValueError, KeyError, TypeError):
        print("Retention failed; no successful retention attestation", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
