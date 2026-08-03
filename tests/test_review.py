import json
import subprocess
import sys
from pathlib import Path

from impact_engine.models import Edge, Evidence, GraphDocument, Node
from impact_engine.review import build_review_report


def _graph(project: Path) -> Path:
    graph = GraphDocument(metadata={"project_path": str(project), "graph_fingerprint": "fixture-fp", "language_semantic_capabilities": {"python": {"language_id": "python", "provider_id": "python_ast_precision", "capabilities": {"production_semantic_baseline": True, "call_resolution": "semantic"}}}})
    graph.add_node(Node("app/service.py:create_order", "FUNCTION", "create_order", {"file": "app/service.py", "line": 3}))
    graph.add_node(Node("app/repo.py:save", "METHOD", "save", {"file": "app/repo.py", "line": 4}))
    graph.add_node(Node("tests/test_orders.py:test_create_order", "TEST", "test_create_order", {"file": "tests/test_orders.py", "line": 2}))
    graph.add_node(Node("assignment:tmp", "ASSIGNMENT", "tmp", {"file": "app/service.py", "line": 4}))
    graph.add_edge(Edge("e1", "CALLS", "app/service.py:create_order", "app/repo.py:save", confidence=.94, evidence=[Evidence("service calls repository", "app/service.py", 3)]))
    graph.add_edge(Edge("e2", "TESTS", "tests/test_orders.py:test_create_order", "app/service.py:create_order", confidence=.91, evidence=[Evidence("test covers service", "tests/test_orders.py", 2)]))
    graph.add_edge(Edge("e3", "ASSIGNS", "app/service.py:create_order", "assignment:tmp", confidence=1.0))
    path = project / ".impact_engine" / "graph.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(graph.to_dict()), encoding="utf-8")
    return path


def _diff():
    return """diff --git a/app/service.py b/app/service.py
--- a/app/service.py
+++ b/app/service.py
@@ -3 +3 @@
-    return old()
+    return new()
"""


def test_review_is_bounded_and_suppresses_low_value_nodes(tmp_path: Path):
    graph_path = _graph(tmp_path)
    graph = GraphDocument.from_json(graph_path.read_text())
    report = build_review_report(str(tmp_path), graph=graph, diff_text=_diff(), refresh="never")

    assert report["schema_version"] == "ReviewReport/v2"
    assert report["contract_compatibility"]["legacy_fields_preserved"] is True
    assert len(report["top_impacts"]) <= 10
    assert all(item["kind"] != "ASSIGNMENT" for item in report["top_impacts"])
    assert report["chains"][0]["edge_ids"]
    assert report["chains"][0]["evidence_locations"]
    assert report["graph_freshness"]["fingerprint"] == "fixture-fp"


def test_review_root_scope_keeps_repository_relative_changed_files(tmp_path: Path):
    graph_path = _graph(tmp_path)
    graph = GraphDocument.from_json(graph_path.read_text())

    report = build_review_report(str(tmp_path), graph=graph, diff_text=_diff(), refresh="never", scope=".")

    assert report["changed"]["symbols"][0]["id"] == "app/service.py:create_order"
    assert report["top_impacts"]


def test_review_excludes_its_own_tracked_artifacts_from_changed_files(tmp_path: Path):
    graph_path = _graph(tmp_path)
    graph = GraphDocument.from_json(graph_path.read_text())
    diff = _diff() + """diff --git a/.impact_engine/graph.json b/.impact_engine/graph.json
--- a/.impact_engine/graph.json
+++ b/.impact_engine/graph.json
@@ -1 +1 @@
-old
+new
diff --git a/.codeslicer/artifacts/onboarding/last.json b/.codeslicer/artifacts/onboarding/last.json
--- a/.codeslicer/artifacts/onboarding/last.json
+++ b/.codeslicer/artifacts/onboarding/last.json
@@ -1 +1 @@
-old
+new
"""
    report = build_review_report(str(tmp_path), graph=graph, diff_text=diff, refresh="never")

    assert [item["path"] for item in report["changed"]["files"]] == ["app/service.py"]
    assert any("generated CodeSlicer artifact changes excluded" in warning for warning in report["warnings"])


def test_entity_scoped_review_preserves_selected_entity_without_diff(tmp_path: Path):
    graph_path = _graph(tmp_path)
    graph = GraphDocument.from_json(graph_path.read_text())
    report = build_review_report(
        str(tmp_path), graph=graph, diff_text="", refresh="never",
        entity="app/service.py:create_order",
    )
    assert report["changed"]["symbols"][0]["id"] == "app/service.py:create_order"
    assert report["top_impacts"][0]["entity_id"] == "app/service.py:create_order"
    assert any("entity-scoped review" in warning for warning in report["warnings"])


def test_default_projection_suppresses_technical_expression_noise(tmp_path: Path):
    graph_path = _graph(tmp_path)
    graph = GraphDocument.from_json(graph_path.read_text())
    graph.add_node(Node("call:len", "CALL_EXPR", "len(items)", {"file": "app/service.py", "line": 4}))
    graph.add_node(Node("call:api", "CALL_EXPR", "client.get", {"file": "app/service.py", "line": 5, "boundary": True}))
    graph.add_edge(Edge("e4", "CALLS", "app/service.py:create_order", "call:len", confidence=.99))
    graph.add_edge(Edge("e5", "CALLS", "app/service.py:create_order", "call:api", confidence=.99))
    report = build_review_report(str(tmp_path), graph=graph, diff_text=_diff(), refresh="never", include_potential=True)
    ids = {item["entity_id"] for item in report["top_impacts"]}
    assert "call:len" not in ids
    assert "call:api" not in ids
    assert "call:api" in {item["entity_id"] for item in report["potential_impacts"]}
    assert "assignment:tmp" not in ids


def test_review_returns_potential_scope_separately_without_changing_primary_output(tmp_path: Path):
    graph_path = _graph(tmp_path)
    graph = GraphDocument.from_json(graph_path.read_text())
    graph.add_node(Node("app/possible.py:dynamic_call", "FUNCTION", "dynamic_call", {"file": "app/possible.py", "line": 4}))
    graph.add_node(Node("route:rejected", "ROUTE", "POST /rejected", {"file": "app/routes.py", "line": 7, "boundary_category": "api"}))
    graph.add_edge(Edge("possible-dynamic", "CALLS", "app/service.py:create_order", "app/possible.py:dynamic_call", confidence=.42, evidence=[Evidence("dynamic dispatch", "app/service.py", 3)], properties={"resolution_status": "unresolved"}))
    graph.add_edge(Edge("rejected-route", "ROUTE_HANDLES", "route:rejected", "app/service.py:create_order", confidence=.2, evidence=[Evidence("rejected route candidate", "app/routes.py", 7)], properties={"status": "rejected"}))

    concise = build_review_report(str(tmp_path), graph=graph, diff_text=_diff(), refresh="never")
    report = build_review_report(str(tmp_path), graph=graph, diff_text=_diff(), refresh="never", include_potential=True)

    assert "app/possible.py:dynamic_call" not in {item["entity_id"] for item in report["top_impacts"]}
    assert concise["potential_impacts"] == []
    assert concise["potential_impact"]["status"] == "available_on_explicit_request"
    assert concise["potential_impact"]["count"] == 1
    potential = {item["entity_id"]: item for item in report["potential_impacts"]}
    assert potential["app/possible.py:dynamic_call"]["impact_tier"] == "possible"
    assert potential["app/possible.py:dynamic_call"]["confidence"] == "low"
    assert potential["app/possible.py:dynamic_call"]["reason"] == "unresolved dynamic call"
    assert "route:rejected" not in potential
    assert report["impact_summary"]["possible"] == 1
    assert report["potential_impact"]["status"] == "included_on_explicit_request"
    assert report["rejected_relations"][0]["kind"] == "ROUTE_HANDLES"
    assert "explicit resolver status: rejected" in report["rejected_relations"][0]["reason"]


def test_dangling_edges_are_reported_and_excluded_from_concise_review(tmp_path: Path):
    graph_path = _graph(tmp_path)
    graph = GraphDocument.from_json(graph_path.read_text())
    graph.add_edge(Edge(
        "dangling-call", "CALLS", "app/service.py:create_order", "missing:expression",
        confidence=.99, evidence=[Evidence("unresolved call", "app/service.py", 8)],
    ))
    report = build_review_report(str(tmp_path), graph=graph, diff_text=_diff(), refresh="never")
    integrity = report["graph_integrity"]
    assert integrity["dangling_endpoint_edges"] == 1
    assert integrity["edges_by_kind_with_missing_endpoint"] == {"CALLS": 1}
    assert integrity["dangling_endpoint_ratio"] > 0
    assert "missing:expression" not in {item["entity_id"] for item in report["top_impacts"]}
    assert all(edge_id != "dangling-call" for chain in report["chains"] for edge_id in chain["edge_ids"])
    assert any("dangling edges excluded" in warning for warning in report["warnings"])


def test_concise_chain_skips_call_expression_between_meaningful_nodes(tmp_path: Path):
    graph_path = _graph(tmp_path)
    graph = GraphDocument.from_json(graph_path.read_text())
    graph.add_node(Node("call:replace", "CALL_EXPR", ".replace", {"file": "app/service.py", "line": 5}))
    graph.add_edge(Edge("e-call", "CALLS", "app/service.py:create_order", "call:replace", confidence=.90))
    graph.add_edge(Edge("e-test", "TESTS", "tests/test_orders.py:test_create_order", "call:replace", confidence=.91, evidence=[Evidence("test covers call", "tests/test_orders.py", 2)]))
    report = build_review_report(str(tmp_path), graph=graph, diff_text=_diff(), refresh="never")
    assert report["chains"]
    assert all("call:replace" not in chain["node_ids"] for chain in report["chains"])
    assert any("tests/test_orders.py:test_create_order" in chain["node_ids"] for chain in report["chains"])


def test_review_explicitly_reports_when_no_cross_file_chain_is_proven(tmp_path: Path):
    graph = GraphDocument(metadata={
        "project_path": str(tmp_path),
        "language_semantic_capabilities": {
            "typescript": {"capabilities": {"production_semantic_baseline": False, "call_resolution": "limited"}}
        },
    })
    graph.add_node(Node("src/memory.ts:CogneeMemory", "CLASS", "CogneeMemory", {"file": "src/memory.ts", "line": 12}))
    graph.add_node(Node("file:src/memory.ts", "FILE", "memory.ts", {"path": "src/memory.ts"}))
    diff = "diff --git a/src/memory.ts b/src/memory.ts\n+++ b/src/memory.ts\n@@ -12 +12 @@\n-old\n+new"
    report = build_review_report(str(tmp_path), graph=graph, diff_text=diff, refresh="never")
    assert report["chains"] == []
    assert report["chain_summary"] == {"status": "no_cross_file_impact_proven", "count": 0}
    assert any("no cross-file impact proven" in warning for warning in report["warnings"])


def test_heuristic_cards_are_explicit_and_non_heuristic_cards_have_evidence(tmp_path: Path):
    graph_path = _graph(tmp_path)
    graph = GraphDocument.from_json(graph_path.read_text())
    report = build_review_report(str(tmp_path), graph=graph, diff_text=_diff(), refresh="never")
    assert report["top_impacts"]
    for item in report["top_impacts"]:
        if item.get("heuristic"):
            assert item["why"].get("heuristic")
            assert item["confidence"] != "high"
        else:
            assert item["why"].get("evidence_locations")


def test_incomplete_language_coverage_makes_risk_unknown(tmp_path: Path):
    graph_path = _graph(tmp_path)
    graph = GraphDocument.from_json(graph_path.read_text())
    graph.metadata["language_semantic_capabilities"]["csharp"] = {
        "language_id": "csharp", "capabilities": {"production_semantic_baseline": False, "call_resolution": "limited"}
    }
    diff = _diff().replace("app/service.py", "api/Orders.cs")
    report = build_review_report(str(tmp_path), graph=graph, diff_text=diff, refresh="never")
    assert report["risk"]["level"] == "UNKNOWN"
    assert report["risk"]["confidence"] == "low"
    assert report["risk"]["reason"] == "incomplete language coverage"
    assert any(item["status"] in {"unsupported", "limited"} for item in report["coverage"])


def test_review_deterministic_and_unsupported_coverage_visible(tmp_path: Path):
    graph_path = _graph(tmp_path)
    graph = GraphDocument.from_json(graph_path.read_text())
    diff = _diff().replace("app/service.py", "app/legacy.cs")
    first = build_review_report(str(tmp_path), graph=graph, diff_text=diff, refresh="never")
    second = build_review_report(str(tmp_path), graph=graph, diff_text=diff, refresh="never")

    assert [x["entity_id"] for x in first["top_impacts"]] == [x["entity_id"] for x in second["top_impacts"]]
    assert any(item["status"] == "unsupported" for item in first["coverage"])
    assert first["warnings"]


def test_review_cli_json_contract(tmp_path: Path):
    graph_path = _graph(tmp_path)
    diff_path = tmp_path / "change.diff"
    diff_path.write_text(_diff(), encoding="utf-8")
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "impact_engine.cli", "review", str(tmp_path), "--graph", str(graph_path), "--diff-file", str(diff_path), "--refresh", "never", "--deep", "--entity", "app/service.py:create_order", "--json"],
        cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "ReviewReport/v2"
    assert payload["actions"]["selected_entity"] == "app/service.py:create_order"


def test_review_mcp_contract(tmp_path: Path):
    graph_path = _graph(tmp_path)
    from impact_engine.mcp.server import TOOLS, review

    assert any(tool["name"] == "review" for tool in TOOLS)
    result = review(str(tmp_path), graph_path=str(graph_path), diff_text=_diff(), refresh="never")
    assert result["status"] == "ok"
    assert result["result"]["schema_version"] == "ReviewReport/v2"
    assert result["result"]["graph_freshness"]["graph_path"] == str(graph_path.resolve())


def test_review_history_is_local_and_feedback_is_separate(tmp_path: Path):
    graph = GraphDocument.from_json(_graph(tmp_path).read_text())
    report = build_review_report(str(tmp_path), graph=graph, diff_text=_diff(), refresh="never")
    from impact_engine.review_history import add_feedback, db_path, list_history, record_review

    review_id = record_review(tmp_path, report)
    add_feedback(tmp_path, review_id, "ignored", "fixture reason")
    rows = list_history(tmp_path)
    assert rows[0]["review_id"] == review_id
    assert db_path(tmp_path).name == "impact_registry.sqlite"
    assert "diff" not in rows[0]["summary_json"]


def test_deep_mode_returns_selected_bounded_query(tmp_path: Path):
    graph = GraphDocument.from_json(_graph(tmp_path).read_text())
    report = build_review_report(
        str(tmp_path), graph=graph, diff_text=_diff(), refresh="never",
        deep=True, entity="app/service.py:create_order",
    )
    assert report["actions"]["selected_entity"] == "app/service.py:create_order"
    assert report["deep_result"]["impact_paths"]


def test_stale_snapshot_is_not_silently_cleared(tmp_path: Path):
    graph_path = _graph(tmp_path)
    snapshot = graph_path.parent / "project.snapshot.json"
    snapshot.write_text(json.dumps({"app/service.py": "old-hash"}), encoding="utf-8")
    graph = GraphDocument.from_json(graph_path.read_text())
    report = build_review_report(str(tmp_path), graph=graph, diff_text=_diff(), refresh="never")
    assert report["graph_freshness"]["stale"] is True
    assert report["risk"]["level"] == "UNKNOWN"
    assert report["risk"]["confidence"] == "low"
    assert report["risk"]["reason"] == "graph freshness is not verified"
    assert all(item["confidence"] == "low" for item in report["top_impacts"])


def test_review_cache_does_not_reuse_a_stale_verdict_after_refresh(tmp_path: Path):
    graph_path = _graph(tmp_path)
    snapshot = graph_path.parent / "project.snapshot.json"
    snapshot.write_text(json.dumps({"app/service.py": "old-hash"}), encoding="utf-8")
    graph = GraphDocument.from_json(graph_path.read_text())
    stale = build_review_report(str(tmp_path), graph=graph, diff_text=_diff(), refresh="never")
    assert stale["graph_freshness"]["stale"] is True
    assert stale["risk"]["level"] == "UNKNOWN"

    from impact_engine.incremental import project_snapshot, save_snapshot

    save_snapshot(project_snapshot(tmp_path), snapshot)
    fresh = build_review_report(str(tmp_path), graph=graph, diff_text=_diff(), refresh="never")
    assert fresh["graph_freshness"]["stale"] is False
    assert fresh["risk"]["level"] != "UNKNOWN"
    assert "graph is stale; high-confidence claims are suppressed" not in fresh["warnings"]


def test_comment_only_diff_does_not_promote_a_python_symbol_to_runtime_impact(tmp_path: Path):
    graph = GraphDocument.from_json(_graph(tmp_path).read_text())
    diff = """diff --git a/app/service.py b/app/service.py
--- a/app/service.py
+++ b/app/service.py
@@ -3,0 +4 @@
+    # This explains why the repository is called here.
"""
    report = build_review_report(str(tmp_path), graph=graph, diff_text=diff, refresh="never")
    assert report["semantic_diff"]["has_runtime_change"] is False
    assert report["changed"]["symbols"] == []
    assert report["risk"]["level"] == "LOW"
    assert any("no runtime change detected" in warning for warning in report["warnings"])


def test_typed_default_change_is_high_risk_and_gets_an_advisory_suite(tmp_path: Path):
    graph = GraphDocument(metadata={"project_path": str(tmp_path), "language_semantic_capabilities": {"python": {"capabilities": {"production_semantic_baseline": True, "call_resolution": "semantic"}}}})
    graph.add_node(Node("class:app.params.Depends", "CLASS", "Depends", {"file": "app/params.py", "line": 1}))
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_params.py").write_text("def test_placeholder(): pass\n", encoding="utf-8")
    diff = """diff --git a/app/params.py b/app/params.py
--- a/app/params.py
+++ b/app/params.py
@@ -2 +2 @@
-    use_cache: bool = True
+    use_cache: bool = False
"""
    report = build_review_report(str(tmp_path), graph=graph, diff_text=diff, refresh="never")
    assert report["semantic_diff"]["has_behavioral_default_change"] is True
    assert report["risk"]["level"] == "HIGH"
    recommendation = report["test_recommendations"][0]
    assert recommendation["advisory"] is True
    assert recommendation["command"] == ["pytest", "tests"]


def test_supported_python_coverage_is_explicitly_review_usable(tmp_path: Path):
    graph = GraphDocument(metadata={"language_semantic_capabilities": {
        "python": {"capabilities": {"production_semantic_baseline": True, "call_resolution": "semantic"}},
    }})
    graph.add_node(Node("method:app.service.save", "METHOD", "save", {"file": "app/service.py", "line": 1}))
    diff = """diff --git a/app/service.py b/app/service.py
--- a/app/service.py
+++ b/app/service.py
@@ -1 +1 @@
-    return value
+    return transformed_value
"""

    report = build_review_report(str(tmp_path), graph=graph, diff_text=diff, refresh="never")

    coverage = report["coverage"][0]
    assert coverage["status"] == "supported"
    assert coverage["review_usable"] is True
    assert "semantic_call_resolution" in coverage["review_usable_features"]
    assert coverage["review_usable_reason"] == "production semantic baseline with semantic call resolution"


def test_diff_base_failure_falls_back_to_working_tree(monkeypatch, tmp_path: Path):
    from impact_engine import review as review_module

    def fake_git(_root, args):
        if len(args) == 2 and args[:2] == ["diff", "--unified=0"]:
            return "working-tree"
        return None

    monkeypatch.setattr(review_module, "_git", fake_git)
    diff, source = review_module._resolve_diff(tmp_path, None, None, "missing-base")
    assert diff == "working-tree"
    assert source == "working-tree:staged+unstaged-fallback"


def test_diff_base_includes_current_working_tree_changes(monkeypatch, tmp_path: Path):
    from impact_engine import review as review_module

    def fake_git(_root, args):
        if args == ["diff", "--unified=0", "main...HEAD"]:
            return "committed"
        if args == ["diff", "--unified=0"]:
            return "unstaged"
        if args == ["diff", "--cached", "--unified=0"]:
            return "staged"
        return None

    monkeypatch.setattr(review_module, "_git", fake_git)
    diff, source = review_module._resolve_diff(tmp_path, None, None, "main")
    assert diff == "committed\nunstaged\nstaged"
    assert source == "base:main...HEAD+working-tree"


def test_real_capability_metadata_marks_polyglot_as_limited(tmp_path: Path):
    graph_path = _graph(tmp_path)
    graph = GraphDocument.from_json(graph_path.read_text())
    graph.metadata["language_semantic_capabilities"]["typescript"] = {
        "language_id": "typescript", "provider_id": "typescript_tree_sitter_endpoint_provider",
        "capabilities": {"production_semantic_baseline": False, "call_resolution": "limited"},
    }
    diff = _diff().replace("app/service.py", "src/memory.ts")
    report = build_review_report(str(tmp_path), graph=graph, diff_text=diff, refresh="never")
    item = next(item for item in report["coverage"] if item["language"] == "typescript")
    assert item["status"] == "limited"
    assert item["may_be_incomplete"] is True


def test_real_capability_metadata_marks_all_limited_languages_honestly(tmp_path: Path):
    graph_path = _graph(tmp_path)
    graph = GraphDocument.from_json(graph_path.read_text())
    graph.metadata["language_semantic_capabilities"] = {
        language: {
            "language_id": language,
            "capabilities": {"production_semantic_baseline": False, "call_resolution": "limited"},
        }
        for language in ("javascript", "typescript", "go", "java")
    }
    diff = "\n".join(
        f"diff --git a/src/{language}/changed.{extension} b/src/{language}/changed.{extension}\n+++ b/src/{language}/changed.{extension}\n@@ -1 +1 @@\n-old\n+new"
        for language, extension in (("javascript", "js"), ("typescript", "ts"), ("go", "go"), ("java", "java"))
    )
    report = build_review_report(str(tmp_path), graph=graph, diff_text=diff, refresh="never")
    statuses = {item["language"]: item["status"] for item in report["coverage"]}
    assert statuses == {"javascript": "limited", "typescript": "limited", "go": "limited", "java": "limited"}


def test_external_graph_path_is_used_for_freshness_and_deep_action(tmp_path: Path):
    source = _graph(tmp_path)
    custom = tmp_path / "custom-graph.json"
    custom.write_text(source.read_text(), encoding="utf-8")
    graph = GraphDocument.from_json(custom.read_text())
    report = build_review_report(str(tmp_path), graph=graph, graph_path=custom, diff_text=_diff(), refresh="auto", deep=True)
    assert report["graph_freshness"]["graph_path"] == str(custom.resolve())
    assert report["graph_freshness"]["external_graph"] is True
    assert report["graph_freshness"]["status"] == "externally_supplied_unverified"
    assert report["graph_freshness"]["stale"] is True
    assert report["risk"]["confidence"] == "low"
    assert str(custom.resolve()) in report["top_impacts"][0]["deep_action"]


def test_default_projection_does_not_call_full_impact_query(monkeypatch, tmp_path: Path):
    from impact_engine import review as review_module

    graph = GraphDocument.from_json(_graph(tmp_path).read_text())
    monkeypatch.setattr(review_module, "impact_query", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("full impact query called")))
    report = build_review_report(str(tmp_path), graph=graph, diff_text=_diff(), refresh="never")
    assert report["top_impacts"]


def test_negative_max_results_is_empty(tmp_path: Path):
    graph = GraphDocument.from_json(_graph(tmp_path).read_text())
    report = build_review_report(str(tmp_path), graph=graph, diff_text=_diff(), refresh="never", max_results=-1)
    assert report["top_impacts"] == []
    assert report["potential_impacts"] == []


def test_auto_refresh_uses_incremental_reuse_when_snapshot_is_current(tmp_path: Path):
    graph_path = _graph(tmp_path)
    from impact_engine.incremental import project_snapshot, save_snapshot

    snapshot_path = graph_path.parent / "project.snapshot.json"
    save_snapshot(project_snapshot(tmp_path), snapshot_path)
    graph = GraphDocument.from_json(graph_path.read_text())
    report = build_review_report(str(tmp_path), graph=graph, diff_text=_diff(), refresh="auto")
    assert report["graph_freshness"]["refresh_status"] == "reused"
    assert report["graph_freshness"]["fallback_reason"] is None
