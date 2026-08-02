from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import impact_engine.analysis.pipeline as analysis_pipeline
from impact_engine.incremental import incremental_update
from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.semantic_hygiene import externalize_large_hygiene
from impact_engine.models import GraphDocument, Node
from impact_engine.models import Edge
from impact_engine.graph_quality import graph_quality_report
from impact_engine.plugin_architecture.integrity import plugin_graph_integrity_gate
from impact_engine.resolution.helpers import build_module_scope_resolver
from semantic_binding.symbol_table import SymbolTable
from semantic_binding.models import Symbol
from impact_engine.persistence import (
    AtomicCacheStore,
    CacheBusyError,
    CacheMetadata,
    CacheLock,
    CancellationToken,
    canonical_json_bytes,
    classify_path,
    project_snapshot,
    write_json_atomic,
)
from impact_engine.profiling import PROFILE_STAGES, WORK_COUNTERS
from impact_engine.scope import iter_selected_project_files


def test_snapshot_is_content_based_and_scope_aware(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "src" / "other.py").write_text("x = 2", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "bad.py").write_text("x = 3", encoding="utf-8")
    first = project_snapshot(tmp_path, "src")
    assert sorted(first) == ["src/app.py", "src/other.py"]
    (tmp_path / "src" / "app.py").write_text("x = 4", encoding="utf-8")
    second = project_snapshot(tmp_path, "src")
    assert first["src/app.py"] != second["src/app.py"]


def test_changed_file_analysis_does_not_replace_the_canonical_cache_bundle(tmp_path: Path, monkeypatch):
    source = tmp_path / "app.py"
    source.write_text("def value():\n    return 1\n", encoding="utf-8")
    (tmp_path / "other.py").write_text("def other():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(
        analysis_pipeline,
        "externalize_large_hygiene",
        lambda graph: externalize_large_hygiene(graph, threshold=1),
    )
    analyze_project_core(str(tmp_path))
    cached_graph = (tmp_path / ".impact_engine" / "graph.json").read_bytes()
    cached_hygiene = (tmp_path / ".impact_engine" / "project_hygiene.json.gz").read_bytes()

    source.write_text("def value():\n    return 2\n", encoding="utf-8")
    analyze_project_core(
        str(tmp_path),
        changed_files=["app.py"],
        raw_graph_cache_path=str(tmp_path / ".impact_engine" / "raw_graph.changed.json"),
    )

    assert (tmp_path / ".impact_engine" / "graph.json").read_bytes() == cached_graph
    assert (tmp_path / ".impact_engine" / "project_hygiene.json.gz").read_bytes() == cached_hygiene


def test_selected_file_traversal_does_not_walk_sibling_files(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "changed.ts").write_text("export const changed = 1;", encoding="utf-8")
    (tmp_path / "src" / "unchanged.ts").write_text("export const unchanged = 1;", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.ts").write_text("export const ignored = 1;", encoding="utf-8")
    selected = list(iter_selected_project_files(tmp_path, ["src/changed.ts"], {".ts"}))
    assert [item.relative_to(tmp_path).as_posix() for item in selected] == ["src/changed.ts"]


def test_atomic_bundle_rejects_interrupted_write(tmp_path: Path):
    metadata = CacheMetadata.from_project(tmp_path)
    store = AtomicCacheStore(tmp_path)
    store.write_bundle(metadata, {"graph.json": GraphDocument(nodes=[Node("a", "FUNCTION", "a")]).to_dict()})
    assert store.load(metadata).status == "hit"
    (tmp_path / ".impact_engine" / ".cache.journal.json").write_text("{}", encoding="utf-8")
    loaded = store.load(metadata)
    assert loaded.status == "invalidated"
    assert loaded.reason == "interrupted_write"


def test_atomic_json_write_is_deterministic_and_readable(tmp_path: Path):
    """Fast JSON bytes must remain a portable cache artifact, not a new schema."""
    target = tmp_path / "artifact.json"
    payload = {"z": [2, {"b": True, "a": "тест"}], "a": {"nested": 1}}

    write_json_atomic(target, payload)
    first = target.read_bytes()
    write_json_atomic(target, payload)

    assert target.read_bytes() == first
    assert first.endswith(b"\n")
    assert json.loads(first) == payload


def test_native_canonical_json_bytes_preserve_the_legacy_fingerprint_contract():
    """Rust-backed JSON must not invalidate deterministic graph fingerprints."""
    payload = {"z": [2, {"b": True, "a": "тест"}], "a": {"nested": 1, "ratio": 0.75}}
    legacy = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    assert canonical_json_bytes(payload) == legacy


def test_cache_is_branch_aware_and_scope_aware(tmp_path: Path):
    metadata = CacheMetadata.from_project(tmp_path, scope="apps/web")
    store = AtomicCacheStore(tmp_path)
    store.write_bundle(metadata, {"graph.json": {"nodes": [], "edges": [], "metadata": {}}})
    assert store.load(metadata).hit
    branch = replace(metadata, branch="feature", ref="feature")
    assert store.load(branch).reason == "branch_mismatch"
    scope = replace(metadata, scan_scope="services/api", scan_scope_hash="different")
    assert store.load(scope).reason == "scan_scope_mismatch"


def test_lock_has_owner_semantics_and_recovers_stale_owner(tmp_path: Path):
    first = CacheLock(tmp_path, owner="first").acquire()
    with pytest.raises(CacheBusyError):
        CacheLock(tmp_path, owner="second").acquire()
    first.release()
    stale = tmp_path / ".impact_engine" / ".analysis.lock"
    stale.write_text(json.dumps({"pid": 99999999, "owner": "dead"}), encoding="utf-8")
    recovered = CacheLock(tmp_path, owner="recovered").acquire()
    recovered.release()


def test_cancelled_incremental_does_not_call_analyzer(tmp_path: Path):
    (tmp_path / "app.py").write_text("pass", encoding="utf-8")
    token = CancellationToken()
    token.cancel()
    called = []
    with pytest.raises(RuntimeError, match="cancelled"):
        incremental_update(str(tmp_path), lambda: called.append(True), cancellation=token)
    assert called == []


def test_warm_pipeline_uses_persistent_cache(tmp_path: Path):
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    first = analyze_project_core(str(tmp_path), scope=".")
    second = analyze_project_core(str(tmp_path), scope=".")
    assert first["status"] == second["status"] == "ok"
    assert "persistent_cache" in second["extractors_used"]
    assert second["graph"]["metadata"]["cache"]["cache_status"] == "hit"
    assert second["graph"]["metadata"]["cache"]["facts_reused"] > 0
    assert second["profiling"]["work"]["facts_reused"] == second["graph"]["metadata"]["cache"]["facts_reused"]


def test_warm_cache_does_not_rescan_the_project_inventory(tmp_path: Path, monkeypatch):
    """Warm validation may stat files, but must not rebuild inventory facts."""
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    analyze_project_core(str(tmp_path), scope=".")

    def fail_inventory_scan(*_args, **_kwargs):
        raise AssertionError("warm cache must not call scan_project_inventory")

    monkeypatch.setattr("impact_engine.analysis.pipeline.scan_project_inventory", fail_inventory_scan)
    warm = analyze_project_core(str(tmp_path), scope=".")
    assert warm["graph"]["metadata"]["cache"]["cache_status"] == "hit"


def test_warm_cache_invalidates_when_plugin_registry_changes(tmp_path: Path, monkeypatch):
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    analyze_project_core(str(tmp_path), scope=".")
    monkeypatch.setattr("impact_engine.persistence.plugin_registry_fingerprint", lambda _project: "changed-registry")
    rebuilt = analyze_project_core(str(tmp_path), scope=".")
    assert "persistent_cache" not in rebuilt["extractors_used"]


def test_warm_cache_invalidates_when_semantic_pipeline_changes(tmp_path: Path, monkeypatch):
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    analyze_project_core(str(tmp_path), scope=".")
    original = CacheMetadata.from_project

    def newer_pipeline(*args, **kwargs):
        return replace(original(*args, **kwargs), analysis_pipeline_version="semantic-evidence.next")

    monkeypatch.setattr("impact_engine.analysis.pipeline.CacheMetadata.from_project", newer_pipeline)
    rebuilt = analyze_project_core(str(tmp_path), scope=".")

    assert "persistent_cache" not in rebuilt["extractors_used"]


def test_graph_quality_orphans_are_computed_from_one_edge_index():
    """Large graphs must not perform a nodes-times-edges orphan scan."""
    graph = GraphDocument(
        nodes=[Node(f"n{index}", "FUNCTION", f"n{index}") for index in range(500)],
        edges=[Edge(f"e{index}", "CALLS", f"n{index}", f"n{index + 1}") for index in range(0, 499)],
    )
    report = graph_quality_report(graph)
    assert report["orphan_node_count"] == 0


def test_plugin_integrity_gate_reuses_one_node_index_for_all_edges():
    graph = GraphDocument(
        nodes=[Node(f"n{index}", "FUNCTION", f"n{index}") for index in range(500)],
        edges=[Edge(f"e{index}", "CALLS", f"n{index}", f"n{index + 1}") for index in range(499)],
    )
    result = plugin_graph_integrity_gate(graph, "language.python")
    assert result.metadata["plugin_graph_integrity"][-1]["dangling_edges_after"] == 0


def test_symbol_table_indexes_qualified_suffixes_without_changing_ambiguity():
    table = SymbolTable()
    first = Symbol(name="run", qualified_name="one.worker.run", kind="function")
    second = Symbol(name="run", qualified_name="two.worker.run", kind="function")
    table.register(first)
    table.register(second)
    assert table.lookup("one.worker.run") is first
    assert table.lookup("worker.run") is None


def test_module_scope_resolver_reuses_a_longest_prefix_index():
    graph = GraphDocument(
        nodes=[
            Node("module:app", "MODULE", "app"),
            Node("module:app.services", "MODULE", "services"),
        ]
    )
    resolver = build_module_scope_resolver(graph)
    assert resolver("app.services.orders.create") == "app.services"
    assert resolver("app.services.orders.update") == "app.services"
    assert resolver("other.worker.run") == "other"


def test_solution_files_are_manifests_not_source_files():
    assert classify_path("backend/Cruxa.sln") == "manifest"
    assert classify_path("backend/Cruxa.slnx") == "manifest"


def test_analysis_profile_has_stable_stage_and_work_schema(tmp_path: Path):
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    first = analyze_project_core(str(tmp_path))
    profile = first["profiling"]
    assert list(profile["stage_timings_seconds"]) == list(PROFILE_STAGES)
    assert set(WORK_COUNTERS).issubset(profile["work"])
    assert set(profile["work"]) == set(WORK_COUNTERS) | {"plugins_executed", "plugins_skipped"}
    assert all(isinstance(value, float) and value >= 0 for value in profile["stage_timings_seconds"].values())
    second = analyze_project_core(str(tmp_path))
    warm_profile = second["profiling"]
    assert warm_profile["stage_timings_seconds"]["extraction"] == 0.0
    assert warm_profile["stage_timings_seconds"]["precision_resolution"] == 0.0
    assert warm_profile["work"]["files_reused"] >= 1


def test_rename_delete_add_does_not_leave_old_file_nodes(tmp_path: Path):
    (tmp_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from a import a\n", encoding="utf-8")
    raw = tmp_path / ".impact_engine" / "raw.json"
    analyze_project_core(str(tmp_path), raw_graph_cache_path=str(raw))
    (tmp_path / "a.py").rename(tmp_path / "renamed.py")
    renamed = analyze_project_core(
        str(tmp_path), changed_files=["a.py", "renamed.py"], raw_graph_cache_path=str(raw)
    )
    ids = {node["id"] for node in renamed["graph"]["nodes"]}
    assert "file:a.py" not in ids
    assert "file:renamed.py" in ids
    (tmp_path / "b.py").unlink()
    deleted = analyze_project_core(str(tmp_path), changed_files=["b.py"], raw_graph_cache_path=str(raw))
    assert "file:b.py" not in {node["id"] for node in deleted["graph"]["nodes"]}
    (tmp_path / "new.py").write_text("def new():\n    return 2\n", encoding="utf-8")
    added = analyze_project_core(str(tmp_path), changed_files=["new.py"], raw_graph_cache_path=str(raw))
    assert "file:new.py" in {node["id"] for node in added["graph"]["nodes"]}


def test_scope_inventory_does_not_activate_framework_from_sibling_package(tmp_path: Path):
    web = tmp_path / "apps" / "web"
    api = tmp_path / "services" / "api"
    web.mkdir(parents=True)
    api.mkdir(parents=True)
    (web / "package.json").write_text('{"dependencies":{"react":"18.0.0"}}', encoding="utf-8")
    (web / "app.tsx").write_text("export const App = () => <div />\n", encoding="utf-8")
    (api / "requirements.txt").write_text("fastapi==0.100.0\n", encoding="utf-8")
    (api / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    result = analyze_project_core(str(tmp_path), scope="apps/web")
    selected = {item["id"] for item in result["graph"]["metadata"]["plugin_selection_plan"]["selected"]}
    assert "framework.python.fastapi" not in selected
    assert any(item.startswith("language.") and item in selected for item in {"language.typescript", "language.javascript"})
    assert all(str(path).replace("\\", "/").startswith("apps/web/") for path in result["inventory"]["files"])


def test_incremental_execution_records_real_language_plugin_selection(tmp_path: Path):
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "widget.ts").write_text("export const widget = 1;\n", encoding="utf-8")
    raw = tmp_path / ".impact_engine" / "raw.json"
    analyze_project_core(str(tmp_path), raw_graph_cache_path=str(raw))
    (tmp_path / "app.py").write_text("def run():\n    return 2\n", encoding="utf-8")
    result = analyze_project_core(str(tmp_path), changed_files=["app.py"], raw_graph_cache_path=str(raw))
    selective = result["graph"]["metadata"]["selective_execution"]
    assert selective["execution_mode"] == "selective_plugin_execution"
    assert selective["selective_execution_proven"] is True
    assert selective["full_pipeline_called"] is False
    assert "language.python" in selective["selected_language_plugins"]
    assert "language.typescript" in selective["skipped_language_plugins"] or "language.javascript" in selective["skipped_language_plugins"]


def test_manifest_incremental_rechecks_all_source_files_for_semantic_safety(tmp_path: Path):
    """A manifest can change plugin selection, so it must never parse only itself."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    raw = tmp_path / ".impact_engine" / "raw.json"
    analyze_project_core(str(tmp_path), raw_graph_cache_path=str(raw))

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'sample'\n# metadata-only edit\n", encoding="utf-8"
    )
    incremental = analyze_project_core(
        str(tmp_path), changed_files=["pyproject.toml"], raw_graph_cache_path=str(raw)
    )
    clean = analyze_project_core(str(tmp_path))
    selective = incremental["graph"]["metadata"]["selective_execution"]

    assert selective["execution_mode"] == "full_initial_scan"
    assert "manifest changed" in selective["fallback_reason"]
    assert "language.python" in incremental["extractors_used"]
    assert sorted((edge["from"], edge["to"], edge["kind"]) for edge in incremental["graph"]["edges"]) == sorted(
        (edge["from"], edge["to"], edge["kind"]) for edge in clean["graph"]["edges"]
    )
