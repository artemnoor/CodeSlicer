from pathlib import Path
import shutil

import pytest

from impact_engine.models import GraphDocument, Node, Edge, Evidence
from impact_engine.plugin_architecture.contracts import PluginContext, PluginManifest, PluginResult
from impact_engine.plugin_architecture.execution import execute_plugin_hook
from impact_engine.plugin_architecture.integrity import annotate_plugin_provenance, plugin_graph_integrity_gate
from impact_engine.plugin_architecture.registry import discover_plugin_registry
from impact_engine.plugin_architecture.registry import PluginRegistry
from impact_engine.plugin_architecture.selection import build_plugin_selection_plan
from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.inventory.scanner import scan_project_inventory
from dataclasses import asdict
import inspect
import os
import socket
import shutil
import subprocess
import sys
import threading
import time

from impact_engine.plugin_architecture.sandbox import _runtime_read_roots


def _sleeping_plugin_hook(context, graph):
    time.sleep(5)
    return PluginResult(graph=graph)


def _network_plugin_hook(context, graph):
    socket.create_connection(("127.0.0.1", 9), timeout=0.1)
    return PluginResult(graph=graph)


def _subprocess_plugin_hook(context, graph):
    subprocess.run(["cmd", "/c", "echo", "blocked"], check=True, timeout=0.1)
    return PluginResult(graph=graph)


def test_pipeline_accepts_registry_diagnostics_as_dicts(tmp_path):
    """Registry diagnostics may come from JSON compatibility manifests."""
    project = tmp_path / "project"
    (project / "app.py").parent.mkdir(parents=True)
    (project / "app.py").write_text("def app():\n    return 1\n", encoding="utf-8")
    result = analyze_project_core(str(project))
    assert result["status"] == "ok"
    assert isinstance(result["diagnostics"], dict)


def test_builtin_fallback_has_no_language_or_framework_dispatch():
    source = (Path(__file__).parents[1] / "src" / "impact_engine" / "plugin_architecture" / "builtins.py").read_text(encoding="utf-8").lower()
    import re
    for literal in ("fastapi", "react", "express", "gin", "spring", "sqlalchemy", "celery"):
        assert re.search(rf"\b{literal}\b", source) is None
    assert "if self.manifest.language" not in source


def test_manifest_backed_language_entrypoints_are_physical_plugins():
    root = Path(__file__).parents[1] / "plugins" / "languages"
    for manifest_path in root.glob("*/plugin.json"):
        manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["entrypoint"].startswith("plugins.languages.")


def test_integrity_gate_runs_after_selected_plugin_phases():
    result = analyze_project_core(str(Path(__file__).parent / "fixtures" / "fastapi_realistic_project"))
    plan = result["graph"]["metadata"]["plugin_selection_plan"]
    gated = result["graph"]["metadata"].get("plugin_graph_integrity", [])
    gated_ids = {item["plugin_id"] for item in gated}
    assert {item["id"] for item in plan["selected"]}.issubset(gated_ids)
    assert all(item["dangling_edges_after"] == 0 for item in gated)


def _outside_write_plugin_hook(context, graph):
    (context.project_path / "outside-plugin-write.txt").write_text("blocked", encoding="utf-8")
    return PluginResult(graph=graph)


def _delete_rename_plugin_hook(context, graph):
    os.rename(context.project_path / "protected.txt", context.project_path / "renamed.txt")
    return PluginResult(graph=graph)


def _rmtree_plugin_hook(context, graph):
    shutil.rmtree(context.project_path / "protected-dir")
    return PluginResult(graph=graph)


# The worker sets this only immediately before importing the hook module. If
# guards are installed too late, these top-level effects execute unprotected.
_import_probe = os.environ.get("IMPACT_ENGINE_PLUGIN_IMPORT_PROBE")
if _import_probe == "_top_level_network_plugin_hook":
    socket.create_connection(("127.0.0.1", 9), timeout=0.1)
elif _import_probe == "_top_level_subprocess_plugin_hook":
    subprocess.run(["cmd", "/c", "echo", "blocked"], timeout=0.1)
elif _import_probe == "_top_level_write_plugin_hook":
    Path("top-level-plugin-write.txt").write_text("blocked", encoding="utf-8")


def _top_level_network_plugin_hook(context, graph):
    return PluginResult(graph=graph)


def _top_level_subprocess_plugin_hook(context, graph):
    return PluginResult(graph=graph)


def _top_level_write_plugin_hook(context, graph):
    return PluginResult(graph=graph)


def _inventory(*, languages=("python",), files=("app.py",), imports=(), dependencies=()):
    return {
        "languages": list(languages),
        "files": list(files),
        "package_manifests": [],
        "external_imports_by_ecosystem": {"python": list(imports), "javascript": list(imports)},
        "declared_dependencies_by_ecosystem": {"python": list(dependencies), "javascript": list(dependencies)},
    }


def test_plugin_manifest_validation_requires_stable_contract():
    manifest = PluginManifest.from_dict({"id": "x", "kind": "language", "language": "python", "version": "1"})
    assert {"missing entrypoint", "missing cache_key"}.issubset(set(manifest.validate()))
    valid = PluginManifest.from_dict({
        "id": "language.test", "kind": "language", "language": "python", "version": "1",
        "file_extensions": [".py"], "entrypoint": "module:factory", "cache_key": "test-v1", "local_first": True,
    })
    assert valid.validate() == []


def test_registry_discovers_languages_and_frameworks_from_manifests():
    registry = discover_plugin_registry()
    assert "language.python" in registry.manifests
    assert "language.typescript" in registry.manifests
    assert "framework.python.fastapi" in registry.manifests
    assert registry.diagnostics == []


def test_language_selection_uses_manifest_evidence_when_inventory_reports_language():
    registry = discover_plugin_registry(Path("tests/fixtures/e2e_polyglot_project"))
    inventory = {
        "languages": ["javascript", "typescript"],
        "files": ["src/App.jsx", "package.json"],
        "package_manifests": ["package.json"],
    }
    plan = build_plugin_selection_plan(
        "tests/fixtures/e2e_polyglot_project", inventory, registry=registry
    )
    assert "language.javascript" in plan.selected_language_ids
    assert "language.typescript" in plan.selected_language_ids


def test_malformed_manifest_is_rejected_without_breaking_discovery(tmp_path):
    path = tmp_path / "plugins" / "languages" / "broken" / "plugin.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"id": "broken", "kind": "language"}', encoding="utf-8")
    registry = PluginRegistry().discover([tmp_path / "plugins"])
    assert registry.manifests == {}
    assert registry.diagnostics[0]["code"] == "invalid_manifest"


def test_version_mismatch_is_rejected_with_diagnostic():
    registry = discover_plugin_registry()
    manifest = registry.manifests["framework.python.fastapi"]
    from dataclasses import replace
    custom = replace(manifest, supported_versions=("99.x",))
    registry.manifests[custom.id] = custom
    plan = build_plugin_selection_plan(
        Path("."),
        {**_inventory(imports=("fastapi",), dependencies=("fastapi",)), "dependency_versions_by_ecosystem": {"python": {"fastapi": "1.0"}}},
        registry=registry,
    )
    assert "framework.python.fastapi" not in plan.selected_framework_ids
    assert any("supported_versions" in item["reason"] for item in plan.rejected if item["id"] == "framework.python.fastapi")


def test_version_matching_uses_numeric_ranges_not_lexicographic_strings():
    from impact_engine.plugin_architecture.selection import _version_matches

    assert _version_matches("10.0", ("2.x",)) is False
    assert _version_matches("2.10", ("2.x",)) is True
    assert _version_matches("2.4", (">=2.0,<3.0",)) is True
    assert _version_matches("3.0", (">=2.0,<3.0",)) is False


def test_selection_requires_dependency_or_import_evidence():
    registry = discover_plugin_registry()
    flask_plan = build_plugin_selection_plan(
        Path("."), _inventory(imports=("flask",), dependencies=("flask",)), registry=registry
    )
    assert "framework.python.fastapi" not in flask_plan.selected_framework_ids
    assert any(item["id"] == "framework.python.fastapi" for item in flask_plan.rejected)

    fastapi_plan = build_plugin_selection_plan(
        Path("."), _inventory(imports=("fastapi",), dependencies=("fastapi",)), registry=registry
    )
    assert "framework.python.fastapi" in fastapi_plan.selected_framework_ids


def test_js_import_evidence_activates_react_pack_without_package_manifest():
    project = Path("tests/fixtures/frameworks/react_realistic")
    inventory = asdict(scan_project_inventory(project))
    plan = build_plugin_selection_plan(project, inventory)
    assert "framework.javascript.react" in plan.selected_framework_ids


def test_express_does_not_activate_react_and_unknown_import_does_not_activate_pack():
    registry = discover_plugin_registry()
    express_plan = build_plugin_selection_plan(
        Path("."), _inventory(languages=("javascript",), files=("server.js",), imports=("express",), dependencies=("express",)), registry=registry
    )
    assert "framework.javascript.express" in express_plan.selected_framework_ids
    assert "framework.javascript.react" not in express_plan.selected_framework_ids

    unknown_plan = build_plugin_selection_plan(
        Path("."), _inventory(languages=("javascript",), files=("server.js",), imports=("not-a-framework",), dependencies=("not-a-framework",)), registry=registry
    )
    assert not unknown_plan.selected_framework_ids


def test_flask_does_not_create_fastapi_route_edges_without_evidence(tmp_path):
    (tmp_path / "app.py").write_text(
        'from flask import Flask\napp = Flask(__name__)\n@app.get("/health")\ndef health(): return "ok"\n',
        encoding="utf-8",
    )
    result = analyze_project_core(str(tmp_path), create_research_requests=False)
    assert not any(
        edge["kind"] == "ROUTE_HANDLES" and edge["properties"].get("framework") == "fastapi"
        for edge in result["graph"]["edges"]
    )
    assert result["graph"]["metadata"]["backend_route_source_composer"]["status"] == "skipped"


def test_plugin_hook_is_local_only_and_timeout_is_enforced(tmp_path):
    context = PluginContext(tmp_path, _inventory())
    assert context.network_allowed is False
    with pytest.raises(PermissionError):
        context.write_local("../outside.txt", "no")
    assert context.write_local("hook/result.json", "ok").is_file()

    started = time.perf_counter()
    with pytest.raises(TimeoutError):
        execute_plugin_hook(_sleeping_plugin_hook, context, GraphDocument(), timeout_seconds=0.1)
    assert time.perf_counter() - started < 1.5


@pytest.mark.parametrize("hook", [_network_plugin_hook, _subprocess_plugin_hook, _outside_write_plugin_hook])
def test_plugin_process_sandbox_rejects_network_subprocess_and_outside_writes(tmp_path, hook):
    context = PluginContext(tmp_path, _inventory())
    with pytest.raises(PermissionError):
        execute_plugin_hook(hook, context, GraphDocument(), timeout_seconds=5.0)


@pytest.mark.parametrize("hook", [_top_level_network_plugin_hook, _top_level_subprocess_plugin_hook, _top_level_write_plugin_hook])
def test_plugin_process_sandbox_is_installed_before_hook_import(tmp_path, hook):
    context = PluginContext(tmp_path, _inventory())
    with pytest.raises(PermissionError):
        execute_plugin_hook(hook, context, GraphDocument(), timeout_seconds=5.0)


def test_plugin_process_sandbox_blocks_delete_and_rename_outside_cache(tmp_path):
    victim = tmp_path / "protected.txt"
    victim.write_text("keep", encoding="utf-8")
    context = PluginContext(tmp_path, _inventory())
    with pytest.raises(PermissionError):
        execute_plugin_hook(_delete_rename_plugin_hook, context, GraphDocument(), timeout_seconds=5.0)
    assert victim.exists()
    assert not (tmp_path / "renamed.txt").exists()


def test_plugin_process_sandbox_blocks_recursive_delete_outside_cache(tmp_path):
    protected = tmp_path / "protected-dir"
    protected.mkdir()
    (protected / "keep.txt").write_text("keep", encoding="utf-8")
    context = PluginContext(tmp_path, _inventory())
    with pytest.raises(PermissionError):
        execute_plugin_hook(_rmtree_plugin_hook, context, GraphDocument(), timeout_seconds=5.0)
    assert (protected / "keep.txt").exists()


def test_plugin_cancellation_terminates_running_process(tmp_path):
    cancellation = threading.Event()
    context = PluginContext(tmp_path, _inventory(), cancellation=cancellation)
    timer = threading.Timer(0.1, cancellation.set)
    started = time.perf_counter()
    timer.start()
    try:
        with pytest.raises(TimeoutError):
            execute_plugin_hook(_sleeping_plugin_hook, context, GraphDocument(), timeout_seconds=5.0)
    finally:
        timer.cancel()
    assert time.perf_counter() - started < 1.5


def test_pipeline_has_no_direct_compatibility_bridge_dependency():
    from impact_engine.analysis import pipeline

    source = inspect.getsource(pipeline)
    assert "frontend_backend_bridge" not in source
    assert "compatibility_bridge" not in source


def test_plugin_sandbox_allows_only_the_trusted_pyinstaller_runtime_root(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(runtime_root), raising=False)
    assert runtime_root.resolve() in _runtime_read_roots(None)


def test_plugin_sandbox_keeps_the_application_package_root_readable():
    from impact_engine.plugin_architecture import sandbox

    assert Path(sandbox.__file__).resolve().parents[2] in _runtime_read_roots(None)


def test_plugin_sandbox_keeps_the_active_runtime_directory_readable():
    assert Path(sys.executable).resolve().parent in _runtime_read_roots(None)


def test_plugin_sandbox_allows_the_bundle_root_of_a_selected_plugin_hook(tmp_path):
    hook = tmp_path / "bundle" / "plugins" / "frameworks" / "react" / "hooks.py"
    hook.parent.mkdir(parents=True)
    hook.write_text("# fixture", encoding="utf-8")
    assert (tmp_path / "bundle").resolve() in _runtime_read_roots(hook)


def test_ambiguous_backend_routes_are_not_composed_as_confirmed_impact(tmp_path):
    project = tmp_path / "fixture"
    shutil.copytree(Path("tests/fixtures/next_react_fastapi_fullstack"), project)
    backend = project / "backend/app/api/shop.py"
    backend.write_text(
        backend.read_text(encoding="utf-8")
        + '\n@router.post("")\ndef duplicate_order(payload: dict) -> dict:\n    return payload\n',
        encoding="utf-8",
    )
    result = analyze_project_core(str(project))
    route_edges = [
        edge for edge in result["graph"]["edges"]
        if edge.get("kind") == "MATCHES_ENDPOINT"
        and edge.get("to") in {"backend.app.api.shop.create_order", "backend.app.api.shop.duplicate_order"}
    ]
    assert route_edges
    assert all(edge.get("properties", {}).get("status") != "confirmed" for edge in route_edges)


def test_selected_pack_edges_carry_pack_rule_and_location_provenance(tmp_path):
    project = tmp_path / "fixture"
    shutil.copytree(Path("tests/fixtures/next_react_fastapi_fullstack"), project)
    result = analyze_project_core(str(project))
    route_edges = [
        edge for edge in result["graph"]["edges"]
        if edge.get("kind") == "ROUTE_HANDLES"
        and edge.get("properties", {}).get("framework") == "fastapi"
    ]
    assert route_edges
    assert all(edge["properties"].get("plugin_id") == "framework.python.fastapi" for edge in route_edges)
    assert all(any(item.get("file") and item.get("line") for item in edge.get("evidence", [])) for edge in route_edges)


def test_selected_framework_special_rules_are_owned_by_pack_hooks(tmp_path):
    project = tmp_path / "fixture"
    shutil.copytree(Path("tests/fixtures/frameworks/fastapi_realistic"), project)
    result = analyze_project_core(str(project))
    metadata = result["graph"]["metadata"]
    assert "fastapi_router_resolver" in metadata.get("plugin_handled_rule_types", [])
    assert "fastapi_depends_resolver" in metadata.get("plugin_handled_rule_types", [])
    assert any(
        item.get("plugin_id") == "framework.python.fastapi"
        and item.get("capability") == "dependency_resolver"
        and item.get("status") == "applied"
        for item in metadata.get("plugin_hook_execution", [])
    )


@pytest.mark.parametrize("second_pack, second_library", [("sqlalchemy", "sqlalchemy"), ("celery", "celery")])
def test_multiple_python_framework_packs_keep_distinct_provenance(second_pack, second_library):
    registry = discover_plugin_registry()
    plan = build_plugin_selection_plan(
        Path("."),
        _inventory(
            imports=("fastapi", second_library),
            dependencies=("fastapi", second_library),
        ),
        registry=registry,
    )
    assert "framework.python.fastapi" in plan.selected_framework_ids
    assert f"framework.python.{second_pack}" in plan.selected_framework_ids
    graph = GraphDocument()
    for library in ("fastapi", second_library):
        graph.add_edge(Edge(
            f"{library}-edge", "DEPENDS_ON", f"{library}.source", f"{library}.target",
            source="SUPPORT_PACK", confidence=0.8,
            evidence=[Evidence(description=f"{library} evidence", file=f"{library}.py", line=1)],
            properties={"support_pack_library": library, "support_pack_rule_id": f"{library}-rule"},
        ))
        graph.add_node(Node(f"{library}.source", "FUNCTION", f"{library}.source"))
        graph.add_node(Node(f"{library}.target", "FUNCTION", f"{library}.target"))
    annotate_plugin_provenance(graph, plan)
    by_library = {edge.properties["support_pack_library"]: edge for edge in graph.edges}
    assert by_library["fastapi"].properties["plugin_id"] == "framework.python.fastapi"
    assert by_library[second_library].properties["plugin_id"] == f"framework.python.{second_pack}"
    for edge in graph.edges:
        assert edge.properties["rule_id"]
        assert edge.properties["plugin_id"]
        assert edge.evidence


def test_language_provenance_uses_evidence_file_extension_in_polyglot_graph():
    registry = discover_plugin_registry()
    plan = build_plugin_selection_plan(
        Path("."),
        _inventory(languages=("python", "csharp"), files=("src/service.py", "src/Service.cs")),
        registry=registry,
    )
    graph = GraphDocument()
    for node_id, file_name in (("py-source", "src/service.py"), ("py-target", "src/target.py"), ("cs-source", "src/Service.cs"), ("cs-target", "src/Target.cs")):
        graph.add_node(Node(node_id, "METHOD", node_id, {"file": file_name}))
    graph.add_edge(Edge("py-edge", "CALLS", "py-source", "py-target", source="EXTRACTED", confidence=.9, evidence=[Evidence("Python call", "src/service.py", 4, "EXTRACTED")]))
    graph.add_edge(Edge("cs-edge", "CALLS", "cs-source", "cs-target", source="EXTRACTED", confidence=.9, evidence=[Evidence("C# call", "src/Service.cs", 4, "EXTRACTED")]))

    annotate_plugin_provenance(graph, plan)

    by_id = {edge.id: edge for edge in graph.edges}
    assert by_id["py-edge"].properties["plugin_id"] == "language.python"
    assert by_id["cs-edge"].properties["plugin_id"] == "language.csharp"


def test_plugin_integrity_gate_materializes_unresolved_endpoint_with_diagnostics():
    graph = GraphDocument(nodes=[Node("method:app.run", "METHOD", "run", {"scope": "app.run"})])
    graph.add_edge(Edge("e", "CALLS", "app.run", "external:pkg.call", evidence=[Evidence("call", "app.py", 2)]))
    result = plugin_graph_integrity_gate(graph, "language.python")
    assert {node.id for node in result.nodes} >= {"app.run", "external:pkg.call"}
    assert result.metadata["plugin_graph_integrity"][0]["rejected_edges"] == []
    assert all(edge.from_node in {node.id for node in result.nodes} and edge.to_node in {node.id for node in result.nodes} for edge in result.edges)
