"""Measure a separate age backup worker and its children on >256 MiB synthetic data.

Requires requirements-test.txt. It never connects to a database or remote service.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import backup as tool
import make_key
import psutil


def worker(args):
    source, encrypted = Path(args.work) / "synthetic.dump", Path(args.work) / "synthetic.age"
    tool.age_transform(source, encrypted, args.key, age_binary=args.age_binary)
    # Restore uses bytes retrieved from a separately named destination directory.
    delivered = tool.deliver(encrypted, Path(args.work) / "independent-destination")
    retrieved = tool.deliver(delivered, Path(args.work) / "independent-recovery")
    restored = Path(args.work) / "independent-recovery" / "restored.dump"
    tool.decrypt_archive(retrieved, restored, args.key, age_binary=args.age_binary)
    assert tool.sha256(source) == tool.sha256(restored)


def measure(size_mib, *, age_binary, age_keygen):
    with tempfile.TemporaryDirectory(prefix="agentflow-streaming-memory-") as work:
        work = Path(work)
        key = work / "separate-identity"
        make_key.create(key, format="age", age_keygen=age_keygen)
        source = work / "synthetic.dump"
        with source.open("xb") as stream:
            for _ in range(size_mib):
                stream.write(os.urandom(1024 * 1024))
        command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--work", str(work),
                   "--key", str(key), "--age-binary", str(age_binary)]
        started = time.monotonic()
        peak = 0
        samples = 0
        with subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) as process:
            child = psutil.Process(process.pid)
            while process.poll() is None:
                if time.monotonic() - started > 400:
                    for descendant in child.children(recursive=True):
                        descendant.kill()
                    process.kill()
                    raise tool.BackupError("Synthetic memory drill timed out")
                try:
                    rss = child.memory_info().rss
                    for descendant in child.children(recursive=True):
                        try:
                            rss += descendant.memory_info().rss
                        except psutil.NoSuchProcess:
                            continue
                    peak = max(peak, rss)
                    samples += 1
                except psutil.NoSuchProcess:
                    break
                time.sleep(0.01)
            _, _ = process.communicate()
            if process.returncode:
                raise tool.BackupError("Synthetic streaming encryption/restore worker failed")
        if peak >= 128 * 1024 * 1024:
            raise tool.BackupError("Synthetic age worker exceeded 128 MiB measured memory budget")
        return {"archive_bytes": source.stat().st_size, "worker_and_children_peak_rss_bytes": peak,
                "rss_samples": samples, "seconds": round(time.monotonic() - started, 3),
                "authenticated_restore_hash_matched": True,
                "independent_local_destination_retrieval": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--age-binary", default="age")
    parser.add_argument("--age-keygen", default="age-keygen")
    parser.add_argument("--report")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--work", help=argparse.SUPPRESS)
    parser.add_argument("--key", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return 0
    if not args.report:
        parser.error("--report is required")
    small = measure(16, age_binary=args.age_binary, age_keygen=args.age_keygen)
    large = measure(300, age_binary=args.age_binary, age_keygen=args.age_keygen)
    assert large["archive_bytes"] > 256 * 1024 * 1024
    result = {"age_version": tool.run([args.age_binary, "--version"]).decode().strip(),
              "small": small, "large": large, "off_host_verified": False,
              "memory_budget_bytes": 128 * 1024 * 1024, "sample_interval_ms": 10}
    Path(args.report).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
