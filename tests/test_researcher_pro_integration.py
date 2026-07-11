import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from impact_engine.research.pro_adapter import adapt_researcher_pro_draft
from impact_engine.support_packs.schema import validate_support_pack_dict
from tests.helpers.cli_runner import run_cli


ROOT = Path(__file__).resolve().parents[1]
RESEARCHER_PRO = Path(os.environ.get("IMPACT_RESEARCHER_PRO_ROOT", ROOT.parent / "ai_library_researcher_pro")).resolve()
pytestmark = pytest.mark.skipif(
    not RESEARCHER_PRO.exists(),
    reason="optional ai_library_researcher_pro project is not checked out",
)
GOOD_DRAFT = RESEARCHER_PRO / "fixtures" / "good_support_pack.json"


def test_researcher_pro_external_tests_pass_smoke():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_no_impact_imports.py", "tests/test_fetcher.py", "-q"],
        cwd=RESEARCHER_PRO,
        timeout=60,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_researcher_pro_cli_offline_run_produces_draft(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(RESEARCHER_PRO)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ai_library_researcher_pro.cli",
            "--storage-root",
            str(tmp_path),
            "run",
            "--library",
            "fastapi",
            "--ecosystem",
            "python",
            "--project-path",
            str(RESEARCHER_PRO / "fixtures" / "sample_project"),
            "--json",
        ],
        cwd=RESEARCHER_PRO,
        env=env,
        timeout=60,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert Path(data["support_pack_path"]).exists()


def test_researcher_pro_draft_adapter_produces_valid_support_pack():
    draft = json.loads(GOOD_DRAFT.read_text(encoding="utf-8"))
    adapted = adapt_researcher_pro_draft(draft)

    assert adapted["library"] == draft["library"]
    assert adapted["language"] == draft["ecosystem"]
    assert adapted["edge_rules"]
    assert validate_support_pack_dict(adapted) == []


def test_cli_adapt_pro_draft_and_install(tmp_path):
    draft_path = GOOD_DRAFT
    adapted_path = tmp_path / "adapted.json"

    res = run_cli(["--json", "support-packs", "adapt-pro-draft", str(draft_path), "--out", str(adapted_path)], cwd=tmp_path)
    data = json.loads(res.stdout)
    assert data["status"] == "ok"
    assert adapted_path.exists()

    install = run_cli(["--json", "support-packs", "install", str(draft_path)], cwd=tmp_path)
    install_data = json.loads(install.stdout)
    assert install_data["valid"] is True
    assert install_data["adapted_from"] == "ai_library_researcher_pro"
    assert Path(install_data["path"]).exists()


def test_cli_libraries_research_pro_installs_adapted_draft(tmp_path):
    sample_project = RESEARCHER_PRO / "fixtures" / "sample_project"
    res = run_cli(
        [
            "--json",
            "libraries",
            "research",
            str(sample_project),
            "--library",
            "fastapi",
            "--ecosystem",
            "python",
            "--pro",
            "--install-draft",
        ],
        cwd=tmp_path,
    )
    data = json.loads(res.stdout)

    assert data["researcher"] == "ai_library_researcher_pro"
    assert data["ok"] is True
    assert Path(data["support_pack_path"]).exists()
    assert data["install_result"]["status"] == "staged"
    assert data["install_result"]["valid"] is True
    assert (tmp_path / data["install_result"]["path"]).exists()
    assert "support_packs/.staging/python/fastapi" in data["install_result"]["path"].replace("\\", "/")


def test_cli_libraries_research_pro_confirm_install_writes_registry(tmp_path):
    sample_project = RESEARCHER_PRO / "fixtures" / "sample_project"
    res = run_cli(
        [
            "--json",
            "libraries",
            "research",
            str(sample_project),
            "--library",
            "fastapi",
            "--ecosystem",
            "python",
            "--pro",
            "--install-draft",
            "--confirm-install",
        ],
        cwd=tmp_path,
    )
    data = json.loads(res.stdout)

    assert data["install_result"]["status"] == "installed"
    assert data["install_result"]["valid"] is True
    assert data["install_result"]["path"] == "support_packs/python/fastapi/support_pack.json"


def test_cli_libraries_research_pro_confirm_install_blocks_existing_without_overwrite(tmp_path):
    sample_project = RESEARCHER_PRO / "fixtures" / "sample_project"
    args = [
        "--json",
        "libraries",
        "research",
        str(sample_project),
        "--library",
        "fastapi",
        "--ecosystem",
        "python",
        "--pro",
        "--install-draft",
        "--confirm-install",
    ]

    first = run_cli(args, cwd=tmp_path)
    assert json.loads(first.stdout)["install_result"]["status"] == "installed"

    second = run_cli(args, cwd=tmp_path, check=False)
    data = json.loads(second.stdout)

    assert second.returncode == 1
    assert data["install_result"]["status"] == "blocked_existing_pack"
    assert data["install_result"]["valid"] is False
    assert data["install_result"]["target_path"] == "support_packs/python/fastapi/support_pack.json"
    assert (tmp_path / data["install_result"]["path"]).exists()

    overwrite = run_cli([*args, "--overwrite"], cwd=tmp_path)
    overwrite_data = json.loads(overwrite.stdout)
    assert overwrite_data["install_result"]["status"] == "installed"
    assert overwrite_data["install_result"]["valid"] is True
