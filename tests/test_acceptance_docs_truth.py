from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_acceptance_status_matches_honest_capability_claims():
    status = json.loads((ROOT / "docs" / "acceptance_status.json").read_text(encoding="utf-8"))

    assert status["tests_passed"] is True
    assert status["blocking_issue"] is None
    assert status["full_pytest_command"] == "python -m pytest -ra"
    assert status["supported_languages"] == ["python"]
    assert status["experimental_languages"] == ["javascript", "typescript", "go", "java"]
    assert status["tree_sitter_status"] in ("native", "partial_native", "partial_local_fallback")
    assert status["tree_sitter_enabled"] is True
    assert status["normal_analyze_requires_internet"] is False
    assert status["graphify_optional"] is True
    assert status["cli_subprocess_tests_bounded"] is True
    assert status["cli_subprocess_timeout_seconds"] == 20
    assert status["cli_tests_in_process"] is True
    assert status["real_cli_subprocess_e2e_passed"] is True
    assert status["mcp_tools_available"] is True
    assert status["mcp_tools_count"] >= 15


def test_pytest_verification_is_required_for_tests_passed_true():
    status = json.loads((ROOT / "docs" / "acceptance_status.json").read_text(encoding="utf-8"))
    verification = json.loads((ROOT / "docs" / "pytest_verification.json").read_text(encoding="utf-8"))

    assert verification["command"] == status["full_pytest_command"]
    assert verification["completed"] is True
    assert verification["exit_code"] == 0
    assert verification["tests_passed"] is True
    assert verification["summary"] == status["full_pytest_summary"]
