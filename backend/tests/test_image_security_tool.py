"""Release gates must not confuse report generation with CVE clearance."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "image_security", Path(__file__).resolve().parents[2] / "deploy/image_security.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def report(severities):
    rules = [{"id": str(i), "properties": {"cvssV3_severity": severity}}
             for i, severity in enumerate(severities)]
    return {"runs": [{"tool": {"driver": {"name": "docker scout", "rules": rules}},
                      "results": [{"ruleId": rule["id"]} for rule in rules]}]}


@pytest.mark.parametrize("severities,passed", [
    ([], True), (["LOW", "MEDIUM"], True), (["HIGH"], False),
    (["CRITICAL"], False), (["UNKNOWN"], False),
])
def test_report_gate(severities, passed):
    result = tool.findings(report(severities))
    assert result["gate_passed"] is passed
    assert sum(result["counts"].values()) == len(severities)


@pytest.mark.parametrize("invalid", [{}, {"runs": []}, {"runs": [{}]}])
def test_missing_evidence_fails(invalid):
    with pytest.raises((KeyError, ValueError)):
        tool.findings(invalid)


def test_tag_drift_refused_before_scan_or_container(monkeypatch, tmp_path):
    calls = []

    def fake(args):
        calls.append(args)
        return '[{"Id": "sha256:other"}]'

    monkeypatch.setattr(tool, "command", fake)
    with pytest.raises(ValueError, match="reviewed candidate"):
        tool.collect("candidate:review", "sha256:expected", tmp_path / "evidence")
    assert len(calls) == 1
    assert not (tmp_path / "evidence").exists()
