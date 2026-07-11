from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PROJECT = ROOT / "fixtures" / "sample_project"


def run_cli(args, cwd: Path):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-m", "ai_library_researcher_pro.cli", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_cli_json_output_is_stable(tmp_path: Path):
    result = run_cli([
        "create",
        "--library",
        "fastapi",
        "--ecosystem",
        "python",
        "--project-path",
        str(FIXTURE_PROJECT),
        "--json",
    ], tmp_path)

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert list(data.keys()) == sorted(data.keys())
    assert data["ok"] is True
    assert data["workflow_id"].startswith("python_fastapi_")


def test_cli_exit_codes_work_for_fetch_without_network(tmp_path: Path):
    create = run_cli([
        "create",
        "--library",
        "fastapi",
        "--ecosystem",
        "python",
        "--project-path",
        str(FIXTURE_PROJECT),
        "--json",
    ], tmp_path)
    workflow_id = json.loads(create.stdout)["workflow_id"]
    result = run_cli(["fetch", workflow_id, "--json"], tmp_path)

    assert result.returncode == 3
    data = json.loads(result.stdout)
    assert data["error_type"] == "NetworkNotAllowed"


def test_cli_exit_code_validation_failed(tmp_path: Path):
    create = run_cli([
        "create",
        "--library",
        "fastapi",
        "--ecosystem",
        "python",
        "--project-path",
        str(FIXTURE_PROJECT),
        "--json",
    ], tmp_path)
    workflow_id = json.loads(create.stdout)["workflow_id"]
    bad_pack = tmp_path / "bad.json"
    bad_pack.write_text(json.dumps({"library": "", "ecosystem": "python", "confidence": 2}), encoding="utf-8")
    result = run_cli(["validate", workflow_id, "--pack", str(bad_pack), "--json"], tmp_path)

    assert result.returncode == 2
    data = json.loads(result.stdout)
    assert data["ok"] is False


def test_cli_full_offline_run_command(tmp_path: Path):
    result = run_cli([
        "run",
        "--library",
        "fastapi",
        "--ecosystem",
        "python",
        "--project-path",
        str(FIXTURE_PROJECT),
        "--json",
    ], tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["workflow_id"].startswith("python_fastapi_")
    assert data["validation"]["valid"] is True
    assert (tmp_path / data["support_pack_path"]).is_file() or Path(data["support_pack_path"]).is_file()


def test_cli_help_runs(tmp_path: Path):
    result = run_cli(["--help"], tmp_path)
    assert result.returncode == 0
    assert "run" in result.stdout
