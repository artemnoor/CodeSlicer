"""Reproducible local performance harness for CodeSlicer.

The runner is intentionally a normal Python script so it can be executed in
CI and on a developer workstation without a benchmark service.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import re
import statistics
import shutil
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.impact import impact_query
from impact_engine.models import GraphDocument
from impact_engine.persistence import project_snapshot
from impact_engine.review import build_review_report


_RELEASE_URL = re.compile(r"https?://[^\s'\"}]+", re.IGNORECASE)
_RELEASE_ENV = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")


def sanitize_performance_report(report: dict[str, Any]) -> dict[str, Any]:
    """Return a release-safe report without source diagnostic payloads."""
    sanitized = copy.deepcopy(report)
    redactions = {"urls": 0, "environment_names": 0, "local_paths": 0}

    def clean(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {item_key: clean(item_value, item_key) for item_key, item_value in value.items()}
        if isinstance(value, list):
            return [clean(item, key) for item in value]
        if not isinstance(value, str):
            return value
        if key in {"path", "source_path"} and value not in {"synthetic://generated", "<local-corpus>"}:
            redactions["local_paths"] += 1
            return "<local-corpus>"
        value, url_count = _RELEASE_URL.subn("[redacted-url]", value)
        value, env_count = _RELEASE_ENV.subn("[redacted-env]", value)
        redactions["urls"] += url_count
        redactions["environment_names"] += env_count
        return value

    sanitized = clean(sanitized)
    sanitized["privacy"] = {
        "mode": "local-only",
        "raw_source_diagnostics_stored": False,
        "redactions": redactions,
    }
    return sanitized


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return round(ordered[index], 6)


def _measure(fn: Callable[[], Any], repeat: int = 1) -> tuple[Any, list[float], int | None]:
    times: list[float] = []
    peak: int | None = None
    value = None
    for _ in range(max(1, repeat)):
        tracemalloc.start()
        started = time.perf_counter()
        value = fn()
        elapsed = time.perf_counter() - started
        _, current_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        times.append(elapsed)
        peak = max(peak or 0, current_peak)
    return value, times, peak


def _semantic_signature(graph: GraphDocument) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(sorted((edge.from_node, edge.to_node, edge.kind, edge.source) for edge in graph.edges))


def _make_synthetic(root: Path) -> None:
    (root / "pyproject.toml").write_text("[project]\nname = 'synthetic'\nversion = '0.0.1'\n", encoding="utf-8")
    (root / "app.py").write_text(
        "from service import run\n\n\ndef main():\n    return run()\n",
        encoding="utf-8",
    )
    (root / "service.py").write_text(
        "def run():\n    return repository()\n\n\ndef repository():\n    return 1\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text("from app import main\n\ndef test_main():\n    assert main() == 1\n", encoding="utf-8")


def _unavailable(path: Path, scope: str) -> dict[str, Any]:
    return {
        "schema_version": "impact-engine.performance-report.v1",
        "corpus": {"path": str(path), "scope": scope, "available": False},
        "status": "corpus_unavailable",
        "timings": {},
        "cache": {},
        "profiling": {},
        "correctness": {"differential_status": "not_run"},
        "incomplete": True,
        "diagnostics": [
            "corpus_unavailable",
            f"reproduce locally with: python benchmarks/performance/runner.py --corpus {path} --scope {scope}",
        ],
    }


def run_case(project: Path, scope: str = ".", *, source_path: Path | None = None, working_copy: bool = False) -> dict[str, Any]:
    if not project.is_dir():
        return _unavailable(project, scope)
    started = time.perf_counter()
    raw_cache = project / ".impact_engine" / "raw_graph.json"
    initial, initial_times, initial_peak = _measure(
        lambda: analyze_project_core(str(project), scope=scope, raw_graph_cache_path=str(raw_cache)), repeat=1
    )
    graph = GraphDocument.from_dict(initial["graph"])
    snapshot = project_snapshot(project, scope)
    initial_signature = _semantic_signature(graph)

    warm, warm_times, warm_peak = _measure(
        lambda: analyze_project_core(str(project), scope=scope, raw_graph_cache_path=str(raw_cache)), repeat=1
    )
    scope_root = project if scope in {"", "."} else project / scope
    candidates = [
        path for path in scope_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java"}
        and ".impact_engine" not in path.parts and ".git" not in path.parts
    ] if scope_root.exists() else []
    source = next((item for item in candidates if item.name == "service.py"), None) or (candidates[0] if candidates else scope_root / "app.py")
    original = source.read_text(encoding="utf-8") if source.exists() else ""
    manifest = next((project / name for name in ("pyproject.toml", "package.json", "requirements.txt", "go.mod", "pom.xml") if (project / name).exists()), project / "pyproject.toml")
    manifest_original = manifest.read_text(encoding="utf-8") if manifest.exists() else None
    manifest_times: list[float] = []
    comment = "#" if source.suffix.lower() in {".py", ".toml", ".txt"} else "//"
    source.write_text(original + f"\n{comment} benchmark mutation\n", encoding="utf-8")
    try:
        incremental, inc_times, inc_peak = _measure(
            lambda: analyze_project_core(str(project), changed_files=[source.relative_to(project).as_posix()], scope=scope, raw_graph_cache_path=str(raw_cache)), repeat=1
        )
        # Compare the clean rebuild with the same final mutation state.  A
        # previous version compared the one-file graph to a clean graph that
        # also included a later manifest mutation, creating a false quality
        # failure for projects that have pyproject.toml/package.json.
        comparison_incremental = incremental
        if manifest_original is not None:
            manifest_comment = "#" if manifest.suffix.lower() in {".toml", ".txt"} else "//"
            manifest.write_text(manifest_original + f"\n{manifest_comment} benchmark manifest mutation\n", encoding="utf-8")
            comparison_incremental, manifest_times, _ = _measure(
                lambda: analyze_project_core(
                    str(project), changed_files=[manifest.relative_to(project).as_posix()],
                    scope=scope, raw_graph_cache_path=str(raw_cache),
                ), repeat=1
            )
        with tempfile.TemporaryDirectory(prefix="impact-engine-clean-") as clean_temp:
            clean_project = Path(clean_temp) / "project"
            shutil.copytree(project, clean_project, ignore=shutil.ignore_patterns(".impact_engine"))
            clean, clean_times, clean_peak = _measure(
                lambda: analyze_project_core(str(clean_project), scope=scope), repeat=1
            )
            clean_graph = GraphDocument.from_dict(clean["graph"])
        differential = _semantic_signature(GraphDocument.from_dict(comparison_incremental["graph"])) == _semantic_signature(clean_graph)
    finally:
        source.write_text(original, encoding="utf-8")
        if manifest_original is not None:
            manifest.write_text(manifest_original, encoding="utf-8")

    query_target = graph.nodes[0].id if graph.nodes else ""
    _, impact_times, impact_peak = _measure(lambda: impact_query(graph, target=query_target, max_depth=5), repeat=5)
    review, review_times, review_peak = _measure(lambda: build_review_report(str(project), graph=graph, refresh="never", scope=scope), repeat=3)
    cache = incremental.get("incremental", {}) or incremental.get("graph", {}).get("metadata", {}).get("incremental_cache", {})
    snapshot_fingerprint = json.dumps(snapshot, sort_keys=True)
    report = {
        "schema_version": "impact-engine.performance-report.v1",
        "corpus": {
            "path": str(source_path or project), "scope": scope, "available": True,
            "working_copy": working_copy,
            "snapshot_fingerprint": __import__("hashlib").sha256(snapshot_fingerprint.encode()).hexdigest(),
            "files": len(snapshot), "loc_context": int(initial.get("inventory", {}).get("loc", 0)),
        },
        "machine": {"platform": platform.platform(), "python": platform.python_version(), "processor": platform.processor()},
        "status": "ok",
        "timings": {
            "initial_scan_wall_seconds": round(initial_times[0], 6),
            "warm_no_change_wall_seconds": round(warm_times[0], 6),
            "one_file_incremental_wall_seconds": round(inc_times[0], 6),
            "manifest_change_incremental_wall_seconds": round(manifest_times[0], 6) if manifest_times else None,
            "top_impact_query": {"p50": _percentile(impact_times, 0.50), "p95": _percentile(impact_times, 0.95), "samples": len(impact_times)},
            "review": {"p50": _percentile(review_times, 0.50), "p95": _percentile(review_times, 0.95), "samples": len(review_times)},
        },
        "memory": {"peak_bytes": max(v or 0 for v in (initial_peak, warm_peak, inc_peak, clean_peak, impact_peak, review_peak))},
        "profiling": {
            "initial": initial.get("profiling", {}),
            "warm": warm.get("profiling", {}),
            "incremental": incremental.get("profiling", {}),
            "review": review.get("profiling", {}),
            "review_projection_seconds": {
                "p50": _percentile(review_times, 0.50),
                "p95": _percentile(review_times, 0.95),
                "samples": len(review_times),
            },
        },
        "plugins": initial.get("graph", {}).get("metadata", {}).get("plugin_selection_plan", {}),
        "cache": {
            "hit_rate": cache.get("cache_hit_rate", 0.0),
            "files_reused": cache.get("files_reused", 0), "files_reanalyzed": cache.get("files_reanalyzed", 0),
            "facts_reused": cache.get("facts_reused", 0), "facts_rebuilt": cache.get("facts_rebuilt", 0),
            "graph_delta": cache.get("graph_delta"),
            "invalidated_nodes": cache.get("invalidated_nodes", []), "snapshot_files": len(snapshot),
        },
        "correctness": {"differential_status": "passed" if differential else "failed", "clean_vs_incremental_equal": differential, "deterministic_signature": initial_signature == _semantic_signature(GraphDocument.from_dict(warm["graph"]))},
        "slo": {"warm_no_change_lt_1s": warm_times[0] < 1.0, "one_file_incremental_lt_2s": inc_times[0] < 2.0, "top_impact_p95_lt_500ms": (_percentile(impact_times, 0.95) or 999) < 0.5},
        "incomplete": bool(initial.get("graph", {}).get("metadata", {}).get("incomplete", False)),
        "diagnostics": initial.get("diagnostics", {}),
        "elapsed_harness_seconds": round(time.perf_counter() - started, 6),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--scope", default=".")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.corpus and not args.synthetic:
        parser.error("choose --synthetic or --corpus")
    if args.synthetic:
        with tempfile.TemporaryDirectory(prefix="impact-engine-bench-") as temp:
            project = Path(temp)
            _make_synthetic(project)
            report = run_case(project, args.scope, source_path=Path("synthetic://generated"))
            report["corpus"]["path"] = "synthetic://generated"
    else:
        source = args.corpus.resolve()
        if not source.is_dir():
            report = _unavailable(source, args.scope)
        else:
            # The benchmark mutates files to measure invalidation. Never point
            # that operation at a user's checkout: copy a filtered working
            # corpus and keep the source path only as report provenance.
            with tempfile.TemporaryDirectory(prefix="impact-engine-corpus-") as temp:
                working = Path(temp) / source.name
                shutil.copytree(
                    source,
                    working,
                    ignore=shutil.ignore_patterns(".impact_engine", ".git", "node_modules", ".venv", "venv", "dist", "build", ".next", "coverage"),
                )
                report = run_case(working, args.scope, source_path=source, working_copy=True)
    report = sanitize_performance_report(report)
    output = args.output
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] in {"ok", "corpus_unavailable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
