"""Collect local-image evidence and fail closed on Scout HIGH/CRITICAL findings.

Never publishes images, applies suppressions, starts networked application
containers or treats successful report generation as a clean vulnerability gate.
"""
import argparse
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path


def findings(report):
    counts = Counter()
    items = []
    runs = report.get("runs", [])
    if not runs:
        raise ValueError("Scanner report contains no runs")
    for run in runs:
        driver = run["tool"]["driver"]
        if driver.get("name") != "docker scout":
            raise ValueError("Expected Docker Scout SARIF")
        rules = {rule["id"]: rule for rule in driver.get("rules", [])}
        if "results" not in run:
            raise ValueError("Scanner report contains no results field")
        for result in run["results"]:
            rule = rules[result["ruleId"]]
            severity = rule.get("properties", {}).get("cvssV3_severity", "UNKNOWN").upper()
            counts[severity] += 1
            items.append({"id": result["ruleId"], "severity": severity,
                          "source": rule.get("helpUri"),
                          "affected_range": rule.get("properties", {}).get("affected_version"),
                          "fixed_version": rule.get("properties", {}).get("fixed_version")})
    # Unknown severities cannot silently pass the release gate.
    return {"counts": dict(counts), "findings": items,
            "gate_passed": not any(counts[s] for s in ("HIGH", "CRITICAL", "UNKNOWN"))}


def command(args):
    return subprocess.check_output(args, text=True, encoding="utf-8", timeout=600)


def collect(image, expected_id, destination):
    info = json.loads(command(["docker", "image", "inspect", image]))[0]
    if info["Id"] != expected_id:
        raise ValueError("Image ID differs from the reviewed candidate")
    destination.mkdir(parents=True, exist_ok=False)
    report_path = destination / "scout.sarif"
    # Resolve to immutable local ID, including after the inspect/scan boundary.
    command(["docker", "scout", "cves", "local://" + expected_id,
             "--format", "sarif", "--output", str(report_path)])
    summary = findings(json.loads(report_path.read_text(encoding="utf-8")))
    package = command(["docker", "run", "--rm", "--network", "none", "--read-only",
                       "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                       "--entrypoint", "dpkg-query", expected_id, "-W",
                       "-f=${binary:Package} ${Version} ${Architecture}", "zlib1g"])
    evidence = {"checked_at": datetime.now(UTC).isoformat(), "image_id": expected_id,
                "repo_digests": info.get("RepoDigests", []),
                "architecture": info["Architecture"], "runtime_user": info["Config"]["User"],
                "zlib_package": package, **summary}
    (destination / "summary.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--output", required=True, type=Path,
                        help="New directory for non-secret scanner evidence")
    args = parser.parse_args()
    try:
        evidence = collect(args.image, args.expected_image_id, args.output)
    except (ValueError, KeyError, OSError, subprocess.SubprocessError, json.JSONDecodeError):
        print("Image security verification failed; inspect local tooling and evidence")
        return 1
    print(json.dumps({"image_id": evidence["image_id"], "counts": evidence["counts"],
                      "gate_passed": evidence["gate_passed"]}))
    return 0 if evidence["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
