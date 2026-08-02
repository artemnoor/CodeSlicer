import pytest
from pathlib import Path

from tests.helpers.cli_runner import run_cli
from impact_engine.cli_parser import build_parser
from impact_engine.cli_dispatch import _error_message

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


def test_cli_version_is_immediate_and_machine_readable(capsys):
    with pytest.raises(SystemExit) as result:
        build_parser("codeslicer").parse_args(["--version"])

    assert result.value.code == 0
    assert capsys.readouterr().out.strip().startswith("codeslicer ")


def test_cli_error_message_preserves_exception_type_when_text_is_empty():
    assert _error_message(RuntimeError()) == "RuntimeError was raised without a diagnostic message"
