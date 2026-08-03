from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks" / "real_projects" / "manifest.json"
SNAPSHOT = ROOT / "docs" / "benchmarks" / "real-project-cli-validation-2026-08-03.json"


def _strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


def test_checked_in_real_project_snapshot_is_pinned_sanitized_and_complete():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert snapshot["schema_version"] == "CodeSlicerRealProjectBenchmarkReport/v1"
    assert snapshot["codeslicer_version"] == "0.5.3"
    assert snapshot["status"] == "passed"
    assert snapshot["method"]["project_dependencies_installed"] is False
    assert snapshot["method"]["project_tests_executed"] is True
    expected = {item["id"]: item for item in manifest["projects"]}
    observed = {item["id"]: item for item in snapshot["results"]}
    assert observed.keys() == expected.keys()
    for project_id, spec in expected.items():
        result = observed[project_id]
        assert result["repository"] == spec["repository"]
        assert result["commit"] == spec["commit"]
        assert result["language"] == spec["language"]
        assert result["validation"]["status"] == "passed"
        assert all(result["validation"]["gates"].values())
        assert result["analysis"]["nodes"] > 0
        assert result["analysis"]["edges"] > 0
        assert result["review"]["historical_commit"]["errors"] == 0
        assert result["review"]["freshness_control"]["errors"] == 0
    assert {item["id"] for item in snapshot["proof_cases"]} == {
        "gin-bindxml-regression", "fastapi-response-serialization-regression"
    }
    for proof in snapshot["proof_cases"]:
        assert proof["validation"]["status"] == "passed"
        assert all(proof["validation"]["gates"].values())
        assert proof["observed_test"]["baseline"]["exit_code"] == 0
        assert proof["observed_test"]["broken_change"]["exit_code"] != 0
        assert proof["observed_test"]["restored"]["exit_code"] == 0
        assert proof["codeslicer_review"]["changed_symbols"]
    assert not any("C:\\Users\\" in item or "/Users/" in item or "<local-corpus>" in item for item in _strings(snapshot))
