from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from impact_engine.incremental import incremental_update
from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.models import GraphDocument, Node
from impact_engine.persistence import (
    AtomicCacheStore,
    CacheBusyError,
    CacheMetadata,
    CacheLock,
    CancellationToken,
    classify_path,
    project_snapshot,
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
