from __future__ import annotations

from impact_engine.adapters.graphify_paths import (
    find_graphify_graph,
    graphify_artifact_root,
    graphify_graph_path,
    legacy_graphify_graph_path,
)


def test_graphify_uses_one_canonical_artifact_location_and_reads_legacy_only_as_fallback(tmp_path):
    canonical = graphify_graph_path(tmp_path)
    legacy = legacy_graphify_graph_path(tmp_path)
    assert canonical == graphify_artifact_root(tmp_path) / "graphify-out" / "graph.json"

    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}", encoding="utf-8")
    assert find_graphify_graph(tmp_path) == legacy

    canonical.parent.mkdir(parents=True)
    canonical.write_text("{}", encoding="utf-8")
    assert find_graphify_graph(tmp_path) == canonical
