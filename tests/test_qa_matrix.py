from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from impact_engine.qa import run_qa_matrix


QA_ROOT = Path(__file__).parent / "fixtures" / "qa_matrix"


def test_qa_matrix_runner_reports_passes_without_known_gaps(tmp_path):
    result = run_qa_matrix(QA_ROOT, tmp_path)

    assert result["status"] == "ok"
    assert result["summary"]["projects"] == 4
    assert result["summary"]["errors"] == 0
    assert result["summary"]["failed"] == 0
    assert result["summary"]["known_gaps"] == 0
    assert result["summary"]["checks"] >= 10

    names = {run["name"]: run for run in result["runs"]}
    assert names["Polyglot Microservices"]["status"] == "ok"
    assert names["Python FastAPI UOW Backend"]["status"] == "ok"
    assert names["Fullstack React TS Python"]["status"] == "ok"
    assert names["Unknown Library Workflow"]["unknown_libraries"]


def test_qa_matrix_cli_json_smoke(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "impact_engine.cli",
            "--json",
            "qa",
            "run",
            str(QA_ROOT),
            "--out-dir",
            str(tmp_path),
        ],
        cwd=Path(__file__).parent.parent,
        timeout=60,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    data = json.loads(completed.stdout)
    assert data["status"] == "ok"
    assert data["summary"]["projects"] == 4
    assert data["summary"]["known_gaps"] == 0
