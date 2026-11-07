"""Disabled-by-default daily backup job runner and failure notifier.

Configuration contains paths and non-secret identifiers only. Credentials are
read by their native clients from protected worker stores/environment.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from pathlib import PurePosixPath

import backup
import rclone_offhost
import monitor


class ScheduleError(Exception):
    pass


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_config(config)
    return config


def validate_config(config):
    if not isinstance(config, dict) or not isinstance(config.get("enabled"), bool):
        raise ScheduleError("Schedule config must contain a boolean enabled flag")
    if not config["enabled"]:
        return
    required = ("database", "user", "host", "key_file", "spool", "destination",
                "status_dir", "remote_folder")
    if any(not isinstance(config.get(key), str) or not config[key].strip()
           or config[key].startswith("REPLACE_") for key in required):
        raise ScheduleError("Enabled schedule config is incomplete")
    folder = config["remote_folder"]
    path = PurePosixPath(folder)
    if (folder.startswith("/") or ".." in path.parts or "\\" in folder or ":" in folder
            or any(part in {"", "."} for part in folder.split("/"))):
        raise ScheduleError("Invalid remote folder")
    for key, default in (("port", 5432), ("timeout_seconds", 7200), ("max_age_hours", 26)):
        value = config.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ScheduleError("Invalid numeric schedule setting")
    if config.get("port", 5432) > 65535:
        raise ScheduleError("Invalid database port")
    return config


def _run(config, runner):
    root = Path(__file__).resolve().parent
    command = [sys.executable, str(root / "backup.py"), "backup",
               "--database", config["database"], "--user", config["user"],
               "--host", config["host"], "--port", str(config.get("port", 5432)),
               "--key-file", config["key_file"], "--spool", config["spool"],
               "--destination", config["destination"], "--allow-production-read"]
    result = runner(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    check=False, timeout=config.get("timeout_seconds", 7200))
    if result.returncode:
        raise ScheduleError("Encrypted backup command failed")
    try:
        manifest = json.loads(result.stdout)
        artifact = Path(config["destination"]) / manifest["artifact"]
        sidecar = artifact.with_suffix(".json")
        rclone_offhost.upload(artifact, manifest=sidecar,
                              remote=config.get("remote", "agentflow-gdrive"),
                              folder=config["remote_folder"], rclone=config.get("rclone", "rclone"),
                              report_path=Path(config["status_dir"]) /
                              (artifact.stem + ".transfer.json"))
        freshness = monitor.check(config["destination"], config.get("max_age_hours", 26))
        return {"status": "success", "artifact": artifact.name,
                "ciphertext_sha256": manifest["ciphertext_sha256"],
                "delivery_fresh": freshness["delivery_fresh"]}
    except (KeyError, ValueError, OSError, rclone_offhost.TransferError,
            backup.BackupError) as exc:
        raise ScheduleError("Backup delivery or freshness verification failed") from exc


def _notify(message, environ):
    url = environ.get("AGENTFLOW_BACKUP_ALERT_WEBHOOK")
    if not url:
        return False
    try:
        request = urllib.request.Request(url, data=json.dumps({"text": message}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def run(config, *, runner=subprocess.run, environ=None, now=None):
    validate_config(config)
    if config.get("enabled") is not True:
        return {"status": "disabled"}
    environ = os.environ if environ is None else environ
    now = now or datetime.now(UTC)
    status_dir = Path(config["status_dir"])
    status_dir.mkdir(parents=True, exist_ok=True)
    log = status_dir / "schedule.jsonl"
    try:
        outcome = _run(config, runner)
    except (ScheduleError, KeyError, OSError, ValueError, TypeError, subprocess.SubprocessError):
        outcome = {"status": "failed", "error": "backup job failed"}
        notified = _notify("AgentFlow encrypted backup failed; inspect protected worker logs.", environ)
        outcome["alert_sent"] = notified
    outcome["completed_utc"] = now.isoformat()
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(outcome, sort_keys=True) + "\n")
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        result = run(config)
        print(json.dumps(result, sort_keys=True))
        return 1 if result.get("status") == "failed" else 0
    except (OSError, ValueError, KeyError, TypeError, ScheduleError):
        print("Backup schedule configuration invalid; no job started", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
