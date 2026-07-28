from pathlib import Path
import os
import shutil
import pytest

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.inventory.scanner import scan_project_inventory
from impact_engine.languages.registry import detect_languages
from impact_engine.languages.registry import get_language_profile
from impact_engine.plugin_architecture.registry import discover_plugin_registry
from impact_engine.review import build_review_report
from plugins.frameworks.csharp_common import apply_aspnet, apply_di, apply_efcore, apply_mediatr, apply_tests
from plugins.languages.csharp.extractor import extract_csharp_project


FIXTURE = Path(__file__).parent / "fixtures" / "csharp_dotnet"


def test_csharp_inventory_and_manifest_selection_are_local_first():
    assert "csharp" in detect_languages(FIXTURE.resolve())
    inventory = scan_project_inventory(FIXTURE.resolve()).to_dict()
    assert ".csproj" in {Path(item).suffix for item in inventory["package_manifests"]}
    assert "MediatR" in inventory["declared_dependencies_by_ecosystem"]["csharp"]
    registry = discover_plugin_registry(FIXTURE.resolve())
    assert registry.manifests["language.csharp"].local_first is True
    assert registry.manifests["framework.csharp.aspnetcore"].local_first is True


def test_csharp_structural_extractor_emits_evidence_and_skips_build_trees():
    graph = extract_csharp_project(str(FIXTURE.resolve()))
    assert graph.metadata["csharp_provider"]["status"] == "limited"
    assert graph.metadata["csharp_feature_status"]["syntax"] == "supported"
    assert any(node.name == "OrderHandler" for node in graph.nodes)
    assert any(node.name == "Handle" and node.kind == "METHOD" for node in graph.nodes)
    assert any(edge.kind == "IMPORTS" and edge.evidence for edge in graph.edges)
    assert not any("bin" in str(node.properties.get("file", "")) for node in graph.nodes)


def test_csharp_member_lines_are_git_compatible_and_anchor_the_changed_handler():
    graph = extract_csharp_project(str(FIXTURE.resolve()))
    handler = graph.get_node("method:Sample.Application.OrderService.Handle")
    constructor = graph.get_node("method:Sample.Application.OrderService.OrderService")

    assert handler is not None and handler.properties["line"] == 19
    assert constructor is not None and constructor.properties["line"] == 18

    diff = """diff --git a/Application.cs b/Application.cs
--- a/Application.cs
+++ b/Application.cs
@@ -17,3 +17,3 @@ public sealed class OrderService : IOrderService
    private readonly SampleDbContext db;
    public OrderService(SampleDbContext db) { this.db = db; }
-    public Task Handle(OrderRequest request) { return db.Orders.AnyAsync(); }
+    public Task Handle(OrderRequest request) { return Task.CompletedTask; }
"""
    report = build_review_report(str(FIXTURE.resolve()), graph=graph, diff_text=diff, refresh="never")
    assert [item["id"] for item in report["changed"]["symbols"]] == ["method:Sample.Application.OrderService.Handle"]


def test_csharp_pipeline_activates_framework_packs_and_preserves_coverage(tmp_path):
    project = tmp_path / "project"
    shutil.copytree(FIXTURE, project)
    result = analyze_project_core(str(project.resolve()), create_research_requests=False)
    assert result["status"] == "ok"
    graph = result["graph"]
    selected = {item["id"] for item in graph["metadata"]["plugin_selection_plan"]["selected"]}
    assert "language.csharp" in selected
    assert "framework.csharp.dotnet-tests" in selected
    assert graph["metadata"]["csharp_provider"]["status"] == "limited"
    assert graph["metadata"]["csharp_framework_features"]["dotnet_tests"]["tests"] == 1
    assert graph["metadata"]["csharp_framework_features"]["di"]["registrations"] == 1
    assert any(n.get("name") == "Get" for n in graph["nodes"]), graph["metadata"].get("csharp_diagnostics")
    assert graph["metadata"]["csharp_framework_features"]["aspnetcore"]["routes"] == 1
    assert graph["metadata"]["csharp_framework_features"]["entityframework"]["dbset_relations"] == 1
    assert "csharp" in graph["metadata"]["resolution_coverage"].get("by_language", {})


def test_cruxa_review_uses_evidence_backed_limited_csharp_features():
    """The real Cruxa source must produce a usable route/test projection.

    This deliberately exercises the C# provider and all framework hooks
    directly, then runs the normal review projection. It avoids the expensive
    whole-project compiler pipeline while still covering the production graph
    facts and ranking boundary used by daily review.
    """
    project = Path(os.environ.get("IMPACT_ENGINE_CRUXA_ROOT", Path(__file__).parent / "corpus" / "Cruxa"))
    project = project.resolve()
    diff_path = Path(os.environ.get("IMPACT_ENGINE_CRUXA_DIFF", Path(__file__).parent / "corpus" / "diffs" / "cruxa-change.diff"))
    if not project.is_dir() or not diff_path.is_file():
        pytest.skip("optional Cruxa corpus/diff is not present in this checkout")
    graph = extract_csharp_project(str(project))
    for hook in (apply_aspnet, apply_di, apply_mediatr, apply_efcore, apply_tests):
        hook(graph, project)
    graph.metadata["language_semantic_capabilities"] = {
        "csharp": get_language_profile("csharp").capabilities_dict()
    }
    graph.metadata["project_path"] = str(project)

    diff = diff_path.read_text(encoding="utf-8")
    report = build_review_report(
        str(project), graph=graph, diff_text=diff, refresh="never",
        max_results=10, run_tests="suggested",
    )

    assert len(report["top_impacts"]) <= 10
    assert report["coverage"][0]["status"] == "limited"
    assert report["coverage"][0]["review_usable"] is True
    assert any("RoutesController" in item["entity_id"] for item in report["top_impacts"])
    assert any(node.kind == "ROUTE" and "RoutesController.cs" in str(node.properties.get("file")) for node in graph.nodes)
    assert report["chain_summary"]["status"] == "cross_file_proven"
    assert report["chains"]
    assert report["test_recommendations"]
    assert any(
        item["category"] in {"route_controller_integration", "frontend_backend_contract"}
        and "RouteIntegrationTests.cs" in str(item.get("file"))
        for item in report["test_recommendations"]
    )
    assert report["risk"]["level"] != "UNKNOWN"
    assert not any(item["kind"] in {"CALL_EXPR", "EXTERNAL_LIBRARY", "ASSIGNMENT"} for item in report["top_impacts"])
    assert any(edge.properties.get("relationship") == "test_literal_http_call" for edge in graph.edges)
