from pathlib import Path

import pytest

from impact_engine.community import annotate_communities
from impact_engine.graph_quality import annotate_graph_quality, apply_quality_guard, graph_quality_report
from impact_engine.graph_identity import annotate_stable_identities
from impact_engine.impact import impact_path
from impact_engine.incremental import incremental_update, normalize_changed_files, project_snapshot, project_snapshot_state
from impact_engine.models import Edge, Evidence, GraphDocument, Node
from impact_engine.watch import watch_project
from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.resolution.helpers import module_for_scope
from semantic_binding.facts import FactSet
from semantic_binding.models import Symbol
from semantic_binding.symbol_table import SymbolTable


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


def test_quality_report_finds_orphans_without_quadratic_edge_scans():
    graph = GraphDocument(nodes=[Node(str(index), "FUNCTION", str(index)) for index in range(300)])
    for index in range(299):
        graph.add_edge(Edge(f"{index}-{index + 1}", "CALLS", str(index), str(index + 1), evidence=[Evidence("call")]))
    graph.add_node(Node("orphan", "FUNCTION", "orphan"))

    report = graph_quality_report(graph)

    assert report["orphan_node_count"] == 1
    assert report["orphan_nodes"] == ["orphan"]


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


def test_versioned_snapshot_reuses_unchanged_file_hashes(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("pass", encoding="utf-8")
    first = project_snapshot_state(project)

    def fail_if_read(_self):
        raise AssertionError("unchanged file was hashed again")

    monkeypatch.setattr(Path, "read_bytes", fail_if_read)
    second = project_snapshot_state(project, first)
    assert second["files"]["main.py"]["sha256"] == first["files"]["main.py"]["sha256"]


def test_changed_paths_are_canonical_and_cannot_escape_project(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "nested" / "main.py"
    source.parent.mkdir()
    source.write_text("pass", encoding="utf-8")

    assert normalize_changed_files(project, [str(source), "nested\\main.py"]) == ["nested/main.py"]
    with pytest.raises(ValueError, match="outside the project"):
        normalize_changed_files(project, [str(tmp_path / "other.py")])


def test_symbol_lookup_uses_qualified_suffix_index_without_changing_ambiguity_rules():
    facts = FactSet(symbols=[
        Symbol(name=f"name{index}", qualified_name=f"package.module{index}.name{index}", kind="function")
        for index in range(500)
    ])
    table = SymbolTable.from_facts(facts)

    assert table.lookup("module245.name245").qualified_name == "package.module245.name245"
    assert table.lookup("name245").qualified_name == "package.module245.name245"


def test_module_for_scope_caches_the_longest_module_prefix():
    graph = GraphDocument(nodes=[
        Node("module:package", "MODULE", "package"),
        Node("module:package.feature", "MODULE", "feature"),
    ])

    assert module_for_scope("package.feature.service.run", graph) == "package.feature"
    assert module_for_scope("package.feature.service.run", graph) == "package.feature"
    assert graph._module_scope_cache["scopes"]["package.feature.service.run"] == "package.feature"


def test_large_graphs_skip_unbounded_enrichment_with_an_explicit_coverage_marker(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "main.py"
    source.write_text("\n".join(f"value_{index} = helper({index})" for index in range(12_050)), encoding="utf-8")

    result = analyze_project_core(str(project))

    budget = result["graph"]["metadata"]["deep_resolution_budget"]
    assert budget["status"] == "skipped_by_scale_budget"
    assert result["graph"]["metadata"]["precision_resolution"]["status"] == "skipped_by_scale_budget"


def test_large_incremental_graph_defers_global_unknown_region_inventory(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "main.py"
    source.write_text("\n".join(f"value_{index} = helper({index})" for index in range(12_050)), encoding="utf-8")

    result = analyze_project_core(str(project), changed_files=["main.py"])

    assert result["graph"]["metadata"]["unknown_regions"]["status"] == "deferred_by_scale_budget"

    incremental = incremental_update(str(project), lambda: analyze_project_core(str(project), changed_files=["main.py"]))
    assert incremental["affected_closure"]["status"] == "deferred_by_scale_budget"
    assert incremental["resolver_context"]["fact_count"] == 0


def test_large_fact_delta_uses_bounded_incremental_planning(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "main.py"
    source.write_text("\n".join(f"value_{index} = helper({index})" for index in range(3_000)), encoding="utf-8")

    result = incremental_update(str(project), lambda: analyze_project_core(str(project)))

    assert result["affected_closure"]["status"] == "deferred_by_fact_delta_budget"
    assert result["resolver_context"]["fact_count"] == 0


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


def test_incremental_fact_association_reuses_symbol_index_for_edges(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("pass", encoding="utf-8")
    graph = make_graph()

    result = incremental_update(str(project), lambda: {"status": "ok", "graph": graph.to_dict()})

    edge = next(item for item in result["graph"]["edges"] if item["id"] == "ab")
    assert edge["properties"]["source_fact_ids"]
