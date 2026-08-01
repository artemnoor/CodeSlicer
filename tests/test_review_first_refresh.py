from __future__ import annotations

import subprocess
from pathlib import Path

from impact_engine.review import build_review_report


def _git(project: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=project, check=True, capture_output=True, text=True, timeout=30)


def test_first_auto_review_persists_graph_and_snapshot(tmp_path: Path) -> None:
    """A new project must not downgrade review because no snapshot exists yet."""
    project = tmp_path / "project"
    project.mkdir()
    source = project / "service.py"
    source.write_text("def enabled() -> bool:\n    return False\n", encoding="utf-8")
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.email", "tests@example.invalid")
    _git(project, "config", "user.name", "CodeSlicer tests")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "baseline")
    source.write_text("def enabled() -> bool:\n    return True\n", encoding="utf-8")

    report = build_review_report(str(project), base="main", refresh="auto")

    assert report["graph_freshness"]["status"] == "fresh"
    assert report["graph_freshness"]["fallback_reason"] == "snapshot_missing_or_graph_missing"
    assert not any("graph refresh failed" in warning for warning in report["warnings"])
    assert (project / ".impact_engine" / "graph.json").is_file()
    assert (project / ".impact_engine" / "project.snapshot.json").is_file()
