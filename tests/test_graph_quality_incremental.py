from pathlib import Path

from impact_engine.community import annotate_communities
from impact_engine.graph_quality import annotate_graph_quality, apply_quality_guard, graph_quality_report
from impact_engine.graph_identity import annotate_stable_identities
from impact_engine.impact import impact_path
from impact_engine.incremental import incremental_update, project_snapshot
from impact_engine.models import Edge, Evidence, GraphDocument, Node
from impact_engine.watch import watch_project
from impact_engine.analysis.pipeline import analyze_project_core


def make_graph() -> GraphDocument:
    graph = GraphDocument(nodes=[
        Node("a", "FUNCTION", "a"),
        Node("b", "FUNCTION", "b"),
        Node("c", "FUNCTION", "c"),
    ])
    graph.add_edge(Edge("ab", "CALLS", "a", "b", confidence=0.9, evidence=[Evidence("call")]))
    graph.add_edge(Edge("bc", "CALLS", "b", "c", confidence=0.9, evidence=[Evidence("call")]))
    return graph


def test_quality_fingerprint_and_community_annotations_are_deterministic():
    graph = annotate_communities(make_graph())
    annotate_stable_identities(graph, ".")
    annotate_graph_quality(graph)
    report = graph_quality_report(graph)
    assert report["status"] == "ok"
    assert len(report["fingerprint"]) == 64
    assert graph.nodes[0].properties["community_id"] == "community-0001"
    assert graph.metadata["communities"]["count"] == 1
    assert graph.nodes[0].properties["stable_id"].startswith("function:")


def test_impact_path_returns_evidence_chain():
    result = impact_path(make_graph(), "a", "c")
    assert result["found"] is True
    assert result["nodes"] == ["a", "b", "c"]
    assert result["confidence"] == 0.9


def test_quality_report_detects_dangling_edge():
    graph = make_graph()
    graph.add_edge(Edge("bad", "CALLS", "a", "missing", evidence=[Evidence("external")]))
    assert graph_quality_report(graph)["dangling_edge_count"] == 1


def test_quality_guard_quarantines_dangling_edge_from_impact():
    graph = make_graph()
    graph.add_edge(Edge("bad", "CALLS", "a", "missing", confidence=0.99, evidence=[Evidence("external")]))
    apply_quality_guard(graph)
    bad = next(edge for edge in graph.edges if edge.id == "bad")
    assert bad.properties["status"] == "suspicious"
    assert bad.properties["quality_guard"] == "quarantined_dangling_endpoint"
    assert impact_path(graph, "a", "missing")["found"] is False


def test_incremental_update_records_changed_files_and_writes_atomically(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("print('one')", encoding="utf-8")
    result = incremental_update(str(project), lambda: {"status": "ok", "graph": make_graph().to_dict()})
    assert result["incremental"]["changed_file_count"] == 1
    snapshot = project_snapshot(project)
    (project / "main.py").write_text("print('two')", encoding="utf-8")
    result = incremental_update(str(project), lambda: {"status": "ok", "graph": make_graph().to_dict()}, snapshot)
    assert result["incremental"]["changed_files"] == ["main.py"]


def test_watch_can_run_bounded_cycles(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("pass", encoding="utf-8")
    results = list(watch_project(str(project), lambda: {"status": "ok", "graph": make_graph().to_dict()}, iterations=2))
    assert len(results) == 2
    assert all(item["incremental"]["safe_replace"] for item in results)


def test_incremental_reuses_unchanged_graph(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("pass", encoding="utf-8")
    graph_path = tmp_path / "graph.json"
    first = incremental_update(
        str(project), lambda: {"status": "ok", "graph": make_graph().to_dict()}, out_path=graph_path
    )
    calls = []
    second = incremental_update(
        str(project), lambda: calls.append(True) or {"status": "bad", "graph": {}},
        previous_snapshot=first["incremental"]["snapshot"], out_path=graph_path,
        previous_graph_path=graph_path,
    )
    assert second["incremental"]["analysis_reused"] is True
    assert calls == []


def test_incremental_pipeline_reuses_raw_extraction_for_changed_file(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "main.py"
    source.write_text("def first():\n    return 1\n", encoding="utf-8")
    cache = tmp_path / "raw_graph.json"
    first = analyze_project_core(
        str(project), changed_files=["main.py"], raw_graph_cache_path=str(cache)
    )
    assert cache.exists()
    source.write_text("def second():\n    return 2\n", encoding="utf-8")
    second = analyze_project_core(
        str(project), changed_files=["main.py"], raw_graph_cache_path=str(cache)
    )
    assert "incremental_raw_cache" in second["extractors_used"]
    assert any(node["name"] == "second" for node in second["graph"]["nodes"])
    assert not any(node["name"] == "first" for node in second["graph"]["nodes"])
