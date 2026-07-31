import json
from pathlib import Path

from impact_engine.models import GraphDocument, Node
from impact_engine.incremental import project_snapshot as incremental_project_snapshot
from impact_engine.persistence import project_snapshot
from impact_engine.review import _resolve_graph


def _write_project_graph(project: Path) -> None:
    cache = project / ".impact_engine"
    cache.mkdir()
    (cache / "graph.json").write_text(GraphDocument(nodes=[Node("method:app.run", "METHOD", "run", {"file": "app.py"})]).to_json(), encoding="utf-8")


def test_disk_graph_without_snapshot_is_stale_when_refresh_is_never(tmp_path: Path):
    (tmp_path / "app.py").write_text("def run(): return 1\n", encoding="utf-8")
    _write_project_graph(tmp_path)
    warnings: list[str] = []

    _graph, freshness = _resolve_graph(tmp_path, None, "never", warnings)

    assert freshness["stale"] is True
    assert "snapshot is unavailable" in " ".join(warnings)


def test_persistent_snapshot_verifies_disk_graph_without_legacy_snapshot(tmp_path: Path):
    (tmp_path / "app.py").write_text("def run(): return 1\n", encoding="utf-8")
    _write_project_graph(tmp_path)
    (tmp_path / ".impact_engine" / "snapshot.json").write_text(json.dumps(project_snapshot(tmp_path), sort_keys=True), encoding="utf-8")
    warnings: list[str] = []

    _graph, freshness = _resolve_graph(tmp_path, None, "never", warnings)

    assert freshness["stale"] is False


def test_review_freshness_uses_the_same_project_boundary_as_incremental_cache(tmp_path: Path):
    (tmp_path / "app.py").write_text("def run(): return 1\n", encoding="utf-8")
    # These files are intentionally outside the CodeSlicer project boundary.
    # They must not make a graph stale after a full analysis skipped them.
    (tmp_path / ".mypy_cache").mkdir()
    (tmp_path / ".mypy_cache" / "state.json").write_text("{}", encoding="utf-8")
    _write_project_graph(tmp_path)
    (tmp_path / ".impact_engine" / "snapshot.json").write_text(
        json.dumps(project_snapshot(tmp_path), sort_keys=True), encoding="utf-8"
    )
    warnings: list[str] = []

    _graph, freshness = _resolve_graph(tmp_path, None, "never", warnings)

    assert incremental_project_snapshot(tmp_path) == project_snapshot(tmp_path)
    assert freshness["stale"] is False
