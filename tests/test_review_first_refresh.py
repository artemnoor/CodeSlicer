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


def test_auto_review_passes_real_changed_files_to_incremental_pipeline(tmp_path: Path, monkeypatch) -> None:
    """A second VS Code review must not silently rebuild the full workspace."""
    project = tmp_path / "project"
    project.mkdir()
    source = project / "service.py"
    source.write_text("def enabled() -> int:\n    return 0\n", encoding="utf-8")
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.email", "tests@example.invalid")
    _git(project, "config", "user.name", "CodeSlicer tests")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "baseline")

    # First review creates the canonical graph, snapshot and raw fragment cache.
    source.write_text("def enabled() -> int:\n    return 1\n", encoding="utf-8")
    build_review_report(str(project), base="main", refresh="auto")
    raw_cache = project / ".impact_engine" / "raw_graph.cdb4ee2aea69.json"
    assert raw_cache.is_file()

    import impact_engine.analysis.pipeline as pipeline

    original = pipeline.analyze_project_core
    observed: list[dict] = []

    def record_incremental(*args, **kwargs):
        observed.append(dict(kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, "analyze_project_core", record_incremental)
    source.write_text("def enabled() -> int:\n    return 2\n", encoding="utf-8")
    report = build_review_report(str(project), base="main", refresh="auto")

    assert observed
    assert observed[-1]["changed_files"] == ["service.py"]
    assert observed[-1]["raw_graph_cache_path"] == str(raw_cache)
    assert report["graph_freshness"]["refresh_status"] in {"updated", "reused"}
