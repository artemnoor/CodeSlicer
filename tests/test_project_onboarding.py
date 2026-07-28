from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from impact_engine.project_onboarding import onboard_project


def _copy_fixture(tmp_path: Path, name: str = "csharp_dotnet") -> Path:
    source = Path(__file__).parent / "fixtures" / name
    target = tmp_path / name
    shutil.copytree(source, target)
    return target


def test_onboard_local_project_builds_canonical_graph_and_keeps_graphify_separate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _copy_fixture(tmp_path)
    real_run = subprocess.run

    def fake_graphify(command, **kwargs):
        if command[0] != "graphify.exe":
            return real_run(command, **kwargs)
        out = Path(command[command.index("--out") + 1]) / "graphify-out"
        out.mkdir(parents=True)
        (out / "graph.json").write_text(json.dumps({
            "nodes": [{"id": "architecture:orders", "name": "Orders", "community": 0}],
            "links": [{"source": "architecture:orders", "target": "architecture:orders", "relation": "contains"}],
        }), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("impact_engine.project_onboarding.shutil.which", lambda value: "graphify.exe")
    monkeypatch.setattr("impact_engine.project_onboarding.subprocess.run", fake_graphify)
    report = onboard_project(str(project), graphify_mode="auto")

    assert report["status"] == "ok"
    assert report["privacy"] == {"mode": "local-only", "network_used": False, "source_code_sent": False}
    assert Path(report["canonical_graph"]["path"]).is_file()
    assert report["canonical_graph"]["participates_in_ranking"] is True
    assert report["architecture_graph"]["status"] == "ok"
    assert report["architecture_graph"]["separate_from_canonical"] is True
    assert report["architecture_graph"]["participates_in_ranking"] is False
    assert Path(report["architecture_graph"]["graph_path"]).is_file()
    assert Path(report["report_path"]).is_file()


def test_onboard_rejects_git_url_without_explicit_network_permission() -> None:
    with pytest.raises(PermissionError, match="--allow-network"):
        onboard_project("https://github.com/example/repository.git", graphify_mode="off")


def test_onboard_without_graphify_remains_useful(tmp_path: Path) -> None:
    project = _copy_fixture(tmp_path, "ts_basic_project")
    report = onboard_project(str(project), graphify_mode="off")

    assert report["canonical_graph"]["nodes"] > 0
    assert report["architecture_graph"]["status"] == "disabled"
    assert report["architecture_graph"]["participates_in_ranking"] is False
