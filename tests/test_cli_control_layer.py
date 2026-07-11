import json
from pathlib import Path

from tests.helpers.cli_runner import run_cli


PROJECT_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"


def test_cli_libraries_detect_outputs_stable_json(tmp_path):
    res = run_cli(["--json", "libraries", "detect", str(PROJECT_PATH)], cwd=tmp_path)
    data = json.loads(res.stdout)

    assert data["status"] == "ok"
    assert data["project_path"] == str(PROJECT_PATH)
    assert data["unknown_libraries"] == []
    assert data["count"] == 0


def test_cli_libraries_research_initializes_workflow_and_builds_input(tmp_path):
    res = run_cli(
        [
            "--json",
            "libraries",
            "research",
            str(PROJECT_PATH),
            "--library",
            "fastapi",
            "--ecosystem",
            "python",
            "--build-input",
        ],
        cwd=tmp_path,
    )
    data = json.loads(res.stdout)

    assert data["status"] == "initialized"
    assert data["library"] == "fastapi"
    assert data["ecosystem"] == "python"
    assert data["input_pack_built"] is True
    assert (tmp_path / ".impact_engine" / "research_workflows" / data["workflow_id"] / "ai_input.json").exists()


def test_cli_doctor_outputs_checks(tmp_path):
    res = run_cli(["--json", "doctor"], cwd=tmp_path)
    data = json.loads(res.stdout)

    assert data["status"] in {"ok", "warning"}
    check_names = {check["name"] for check in data["checks"]}
    assert {"tree_sitter", "support_packs", "research_workspace"}.issubset(check_names)


def test_cli_qa_run_single_project(tmp_path):
    out_dir = tmp_path / "qa"
    res = run_cli(["--json", "qa", "run", str(PROJECT_PATH), "--out-dir", str(out_dir)], cwd=tmp_path)
    data = json.loads(res.stdout)

    assert data["status"] == "ok"
    assert len(data["runs"]) == 1
    assert data["runs"][0]["status"] == "ok"
    assert data["runs"][0]["nodes"] > 0
    assert Path(data["runs"][0]["graph_path"]).exists()
