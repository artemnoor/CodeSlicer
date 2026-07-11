import pytest
from pathlib import Path

from tests.helpers.cli_runner import run_cli

PROJECT_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"


def test_cli_smoke_human_readable_default(tmp_path):
    res = run_cli(["analyze", str(PROJECT_PATH)], cwd=tmp_path)
    assert "Project analysis completed successfully." in res.stdout
    assert "Path: " in res.stdout
    assert "Nodes: " in res.stdout


def test_cli_smoke_validation_failure_exits_nonzero(tmp_path):
    broken_file = tmp_path / "broken_pack.json"
    broken_file.write_text("invalid json or missing fields", encoding="utf-8")

    res = run_cli(["support-packs", "validate", str(broken_file)], cwd=tmp_path, check=False)

    assert res.returncode == 1
    assert "INVALID" in res.stdout
