"""Local-only Joern/CPG quality benchmark harness.

This module measures the already-importable ``CodeSlicerJoernInterchange/v1``
overlay. It never starts Joern, invokes a subprocess, accesses the network, or
stores the imported overlay in a benchmark result. Only bounded aggregate
metrics are persisted under ``.codeslicer/history`` by default.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable

from impact_engine.adapters.joern import bounded_joern_context
from impact_engine.adapters.registry import AdapterRegistry, MAX_ARTIFACT_BYTES
from impact_engine.models import GraphDocument
from impact_engine.review import build_review_report


BENCHMARK_SCHEMA = "CodeSlicerJoernBenchmark/v1"
GOLDEN_CASE_SCHEMA = "CodeSlicerJoernGoldenCase/v1"
SAFE_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#@$+~<>-]{0,255}$")
SECRET_LIKE = re.compile(r"(?:secret|token|password|passwd|authorization|bearer|cookie|api[_-]?key|private[_-]?key|credential)", re.I)
LANGUAGE_EXTENSIONS = {
    "C": {".c", ".h"},
    "C++": {".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"},
    "Java": {".java"},
}
DEFAULT_DISCOVERY_MAX_FILES = 5_000
DEFAULT_DISCOVERY_TIMEOUT_SECONDS = 10.0
DISCOVERY_EXCLUDED_DIRS = {
    ".git", ".impact_engine", ".codeslicer", "node_modules", "build", "dist",
    "out", "target", "bin", "obj", "coverage", ".venv", "venv", "graphify-out",
}


def _absolute_local(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute local path")
    return path.resolve()


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_ids(paths: Iterable[dict[str, Any]], resolution: str | None = None) -> set[str]:
    return {
        str(item.get("id"))
        for item in paths
        if isinstance(item, dict) and item.get("id") and (resolution is None or item.get("resolution") == resolution)
    }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0 if numerator == 0 else 0.0
    return round(numerator / denominator, 4)


def _expected_ids(case: dict[str, Any], key: str) -> set[str] | None:
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    value = expected.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"golden case expected.{key} must be an array")
    result: set[str] = set()
    for item in value:
        identifier = item.get("id") if isinstance(item, dict) else item
        if not isinstance(identifier, str) or not SAFE_CASE_ID.fullmatch(identifier) or SECRET_LIKE.search(identifier):
            raise ValueError(f"golden case expected.{key} contains an unsafe identifier")
        result.add(identifier)
    return result


def validate_golden_case(case: dict[str, Any]) -> dict[str, Any]:
    """Validate a case without retaining arbitrary case fields."""
    if not isinstance(case, dict) or case.get("schema_version") not in {None, GOLDEN_CASE_SCHEMA}:
        raise ValueError(f"golden case must use {GOLDEN_CASE_SCHEMA}")
    case_id = case.get("case_id")
    language = case.get("language")
    if not isinstance(case_id, str) or not SAFE_CASE_ID.fullmatch(case_id) or SECRET_LIKE.search(case_id):
        raise ValueError("golden case case_id must be a safe bounded identifier")
    if language not in {"C", "C++", "Java"}:
        raise ValueError("golden case language must be C, C++, or Java")
    project_path = _absolute_local(str(case.get("project_path") or ""), "golden case project_path")
    artifact_path = _absolute_local(str(case.get("artifact_path") or ""), "golden case artifact_path")
    safe = {
        "schema_version": GOLDEN_CASE_SCHEMA,
        "case_id": case_id,
        "language": language,
        "project_path": str(project_path),
        "artifact_path": str(artifact_path),
        "source_artifact_fingerprint": str(case.get("source_artifact_fingerprint") or ""),
        "expected": {},
        "prohibited_false_positive_paths": [],
        "required_evidence_locations": bool(case.get("required_evidence_locations", True)),
    }
    for key in ("confirmed_path_ids", "likely_path_ids", "unresolved_path_ids", "dangerous_call_node_ids", "source_node_ids", "sink_node_ids", "step_node_ids"):
        ids = _expected_ids(case, key)
        if ids is not None:
            safe["expected"][key] = sorted(ids)
    resolutions = case.get("expected_resolutions")
    if resolutions is not None:
        if not isinstance(resolutions, dict):
            raise ValueError("golden case expected_resolutions must be an object")
        safe_resolutions: dict[str, str] = {}
        for identifier, resolution in resolutions.items():
            if not isinstance(identifier, str) or not SAFE_CASE_ID.fullmatch(identifier) or SECRET_LIKE.search(identifier) or resolution not in {"confirmed", "likely", "unresolved"}:
                raise ValueError("golden case expected_resolutions contains an unsafe entry")
            safe_resolutions[identifier] = resolution
        safe["expected_resolutions"] = safe_resolutions
    prohibited = case.get("prohibited_false_positive_paths") or []
    if not isinstance(prohibited, list):
        raise ValueError("golden case prohibited_false_positive_paths must be an array")
    for item in prohibited:
        if not isinstance(item, str) or not SAFE_CASE_ID.fullmatch(item) or SECRET_LIKE.search(item):
            raise ValueError("golden case contains an unsafe prohibited path identifier")
    safe["prohibited_false_positive_paths"] = sorted(set(prohibited))
    return safe


def _privacy_leak_count(source: Path, values: list[dict[str, Any]]) -> int:
    """Count suspicious raw values that escaped into the returned projection."""
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 0
    candidates: set[str] = set()

    def collect(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                collect(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                collect(child, key)
        elif isinstance(value, str) and len(value) >= 8 and (SECRET_LIKE.search(key) or SECRET_LIKE.search(value) or "SECRET_" in value.upper()):
            candidates.add(value)

    collect(raw)
    if not candidates:
        return 0
    rendered = json.dumps(values, ensure_ascii=False, sort_keys=True)
    return sum(1 for candidate in candidates if candidate in rendered)


def _review_signature(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "risk": report.get("risk"),
        "top_impacts": report.get("top_impacts", []),
        "test_recommendations": report.get("test_recommendations", []),
    }


def _review_invariance(project: Path, before_graph_bytes: bytes | None, graph: GraphDocument | None, before_signature: dict[str, Any] | None = None) -> dict[str, Any]:
    if graph is None:
        return {"status": "unavailable", "invariant": None, "reason": "canonical graph is unavailable"}
    before = before_signature or _review_signature(build_review_report(str(project), graph=graph, refresh="never", run_tests="none"))
    after = build_review_report(str(project), graph=graph, refresh="never", run_tests="none")
    graph_path = project / ".impact_engine" / "graph.json"
    unchanged = before_graph_bytes is None or not graph_path.exists() or graph_path.read_bytes() == before_graph_bytes
    return {"status": "checked", "invariant": before == _review_signature(after) and unchanged}


def aggregate_joern_benchmark(
    project_path: str | Path,
    artifact_path: str | Path,
    *,
    case: dict[str, Any] | None = None,
    entity: str | None = None,
    max_nodes: int = 80,
    max_edges: int = 160,
    max_paths: int = 40,
    before_review_signature: dict[str, Any] | None = None,
    before_graph_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Collect bounded metrics from an already imported/enabled Joern overlay."""
    project = _absolute_local(project_path, "project_path")
    artifact = _absolute_local(artifact_path, "artifact_path")
    safe_case = validate_golden_case(case) if case else None
    registry = AdapterRegistry(str(project))
    status = registry.status("joern")
    overlay = registry.overlay("joern")
    started = time.perf_counter()
    context = bounded_joern_context(overlay, entity=entity, max_nodes=max_nodes, max_edges=max_edges, max_paths=max_paths)
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    paths = list((overlay or {}).get("taint_paths") or [])
    findings = list((overlay or {}).get("findings") or [])
    confirmed = _path_ids(paths, "confirmed")
    likely = _path_ids(paths, "likely")
    unresolved = _path_ids(paths, "unresolved")
    expected_values = (safe_case or {}).get("expected", {}) if safe_case else {}
    expected_confirmed = set(expected_values.get("confirmed_path_ids", [])) if "confirmed_path_ids" in expected_values else None
    if expected_confirmed is None and safe_case and isinstance(safe_case.get("expected_resolutions"), dict):
        expected_confirmed = {key for key, value in safe_case["expected_resolutions"].items() if value == "confirmed"}
    prohibited = set((safe_case or {}).get("prohibited_false_positive_paths", [])) if safe_case else set()
    expected_dangerous = set((safe_case or {}).get("expected", {}).get("dangerous_call_node_ids", [])) if safe_case else None
    dangerous_nodes = {str(item.get("node")) for item in findings if item.get("kind") == "DANGEROUS_CALL" and item.get("node")}
    if expected_confirmed is None:
        precision = recall = None
        false_confirmed = len(confirmed & prohibited) if prohibited else None
    else:
        true_positive = len(confirmed & expected_confirmed)
        precision = _ratio(true_positive, len(confirmed))
        recall = _ratio(true_positive, len(expected_confirmed))
        false_confirmed = len((confirmed - expected_confirmed) | (confirmed & prohibited))
    dangerous_precision = None
    if expected_dangerous is not None:
        dangerous_precision = _ratio(len(dangerous_nodes & expected_dangerous), len(dangerous_nodes))
    complete = 0
    for path in paths:
        if path.get("resolution") != "confirmed":
            continue
        nodes = {str(item.get("id")): item for item in (overlay or {}).get("nodes", []) if isinstance(item, dict)}
        source = nodes.get(str(path.get("source")), {})
        sink = nodes.get(str(path.get("sink")), {})
        if source.get("provenance") and sink.get("provenance") and path.get("steps") and path.get("locations"):
            complete += 1
    explanation_completeness = _ratio(complete, len(confirmed))
    diagnostic_codes = sorted({
        str(item.get("code")) for item in list((overlay or {}).get("diagnostics") or []) + list(context.get("diagnostics") or [])
        if isinstance(item, dict) and item.get("code")
    })
    graph_path = project / ".impact_engine" / "graph.json"
    graph_bytes = graph_path.read_bytes() if graph_path.is_file() else None
    graph = GraphDocument.from_json(graph_bytes.decode("utf-8")) if graph_bytes else None
    review = _review_invariance(project, before_graph_bytes if before_graph_bytes is not None else graph_bytes, graph, before_review_signature)
    actual_fingerprint = _fingerprint(artifact) if artifact.is_file() else None
    recorded_fingerprint = (safe_case or {}).get("source_artifact_fingerprint") if safe_case else None
    fingerprint_matches = (actual_fingerprint == recorded_fingerprint) if recorded_fingerprint else None
    if recorded_fingerprint and not fingerprint_matches:
        diagnostic_codes.append("joern_golden_fingerprint_mismatch")
    freshness = status.get("freshness") or {}
    report = {
        "schema_version": BENCHMARK_SCHEMA,
        "status": "ok" if overlay is not None and fingerprint_matches is not False else "blocked",
        "case": {key: safe_case[key] for key in ("case_id", "language") if safe_case and key in safe_case} if safe_case else None,
        "project_path": str(project),
        "source_artifact_fingerprint": actual_fingerprint,
        "golden_case": {"fingerprint_provided": bool(recorded_fingerprint), "fingerprint_matches": fingerprint_matches},
        "adapter": {"status": status.get("status"), "enabled": bool(status.get("enabled")), "availability": (overlay or {}).get("availability", "unavailable")},
        "freshness": {"status": freshness.get("status", "unknown"), "verified": bool(freshness.get("verified", False))},
        "counts": {"nodes": len((overlay or {}).get("nodes") or []), "edges": len((overlay or {}).get("edges") or []), "paths": len(paths), "findings": len(findings), "context_nodes": len(context.get("nodes") or []), "context_edges": len(context.get("edges") or [])},
        "resolution": {"confirmed": len(confirmed), "likely": len(likely), "unresolved": len(unresolved), "dangerous_call_findings": len(dangerous_nodes)},
        "metrics": {"confirmed_taint_path_precision": precision, "confirmed_taint_path_recall": recall, "dangerous_call_context_precision": dangerous_precision, "false_confirmed_count": false_confirmed, "explanation_completeness": explanation_completeness, "privacy_leak_count": _privacy_leak_count(artifact, [overlay or {}, context]), "bounded_investigate_latency_ms": latency_ms},
        "review_invariance": review,
        "bounded_context": {"status": context.get("status"), "limits": {"max_nodes": max_nodes, "max_edges": max_edges, "max_paths": max_paths}, "bounded": len(context.get("nodes") or []) <= max_nodes and len(context.get("edges") or []) <= max_edges and len(context.get("taint_paths") or []) <= max_paths},
        "diagnostics": {"count": len(diagnostic_codes), "codes": diagnostic_codes},
        "privacy": {"mode": "local-only", "network_used": False, "joern_invoked": False, "raw_overlay_stored_in_result": False},
    }
    return report


def run_joern_benchmark(
    project_path: str | Path,
    artifact_path: str | Path,
    *,
    case: dict[str, Any] | None = None,
    output_path: str | Path | None = None,
    entity: str | None = None,
    max_nodes: int = 80,
    max_edges: int = 160,
    max_paths: int = 40,
) -> dict[str, Any]:
    """Explicitly import, enable, and measure one local Joern artifact."""
    project = _absolute_local(project_path, "project_path")
    artifact = _absolute_local(artifact_path, "artifact_path")
    if not project.is_dir():
        raise FileNotFoundError(f"project directory does not exist: {project}")
    if not artifact.is_file():
        raise FileNotFoundError(f"Joern artifact does not exist: {artifact}")
    if artifact.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError(f"Joern artifact exceeds {MAX_ARTIFACT_BYTES} bytes")
    graph_path = project / ".impact_engine" / "graph.json"
    before_graph_bytes = graph_path.read_bytes() if graph_path.is_file() else None
    before_graph = GraphDocument.from_json(before_graph_bytes.decode("utf-8")) if before_graph_bytes else None
    before_review_signature = _review_signature(build_review_report(str(project), graph=before_graph, refresh="never", run_tests="none")) if before_graph else None
    registry = AdapterRegistry(str(project))
    registry.import_artifact("joern", str(artifact))
    registry.set_enabled("joern", True)
    report = aggregate_joern_benchmark(project, artifact, case=case, entity=entity, max_nodes=max_nodes, max_edges=max_edges, max_paths=max_paths, before_review_signature=before_review_signature, before_graph_bytes=before_graph_bytes)
    target = _absolute_local(output_path, "output_path") if output_path else project / ".codeslicer" / "history" / "joern-validation" / f"{(case or {}).get('case_id', 'ad-hoc')}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "ok", "report": report, "report_path": str(target)}


def _language_for_project(project: Path) -> list[str]:
    found: set[str] = set()
    for path in project.rglob("*"):
        if not path.is_file() or ".git" in path.parts or ".impact_engine" in path.parts or ".codeslicer" in path.parts:
            continue
        for language, extensions in LANGUAGE_EXTENSIONS.items():
            if path.suffix.lower() in extensions:
                found.add(language)
    return sorted(found)


def _iter_discovery_json_files(root: Path, *, include_synthetic: bool) -> Iterable[Path]:
    excluded = set(DISCOVERY_EXCLUDED_DIRS)
    if not include_synthetic:
        excluded.update({"fixtures", "corpus"})
    if root.is_file():
        if root.suffix.lower() == ".json":
            yield root
        return
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        directories[:] = sorted(item for item in directories if item.lower() not in excluded)
        for filename in sorted(files):
            if filename.lower().endswith(".json"):
                yield Path(current) / filename


def discover_local_joern_corpus(
    search_roots: Iterable[str | Path],
    *,
    max_files: int = DEFAULT_DISCOVERY_MAX_FILES,
    timeout_seconds: float = DEFAULT_DISCOVERY_TIMEOUT_SECONDS,
    include_synthetic: bool = False,
) -> dict[str, Any]:
    """Find local interchange exports with bounded, pruned directory walking."""
    if max_files < 1:
        raise ValueError("max_files must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    roots = [_absolute_local(root, "search root") for root in search_roots]
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    scanned_files = 0
    started = time.monotonic()
    diagnostics: list[str] = []
    stopped_reason: str | None = None
    for root in roots:
        if not root.exists():
            continue
        for artifact in _iter_discovery_json_files(root, include_synthetic=include_synthetic):
            if time.monotonic() - started >= timeout_seconds:
                stopped_reason = "timeout"
                break
            if scanned_files >= max_files:
                stopped_reason = "max_files"
                break
            scanned_files += 1
            if not artifact.is_file() or artifact.stat().st_size > MAX_ARTIFACT_BYTES or str(artifact.resolve()) in seen:
                continue
            try:
                data = json.loads(artifact.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict) or data.get("schema_version") != "CodeSlicerJoernInterchange/v1":
                continue
            seen.add(str(artifact.resolve()))
            metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
            project_value = metadata.get("project_path") or metadata.get("project_root")
            if not project_value:
                continue
            project = Path(str(project_value)).expanduser().resolve()
            languages = _language_for_project(project) if project.is_dir() else []
            synthetic = "tests\\fixtures" in str(artifact).lower() or "tests/fixtures" in str(artifact).lower()
            candidates.append({"artifact_path": str(artifact.resolve()), "project_path": str(project), "languages": languages, "synthetic": synthetic, "status": "available" if project.is_dir() else "foreign_or_missing_project"})
        if stopped_reason:
            break
    real = [item for item in candidates if not item["synthetic"] and item["status"] == "available" and item["languages"]]
    synthetic = [item for item in candidates if item["synthetic"]]
    if stopped_reason == "timeout":
        diagnostics.append(f"Discovery stopped after {timeout_seconds:g}s; narrow the roots or increase --timeout")
    elif stopped_reason == "max_files":
        diagnostics.append(f"Discovery stopped after {max_files} JSON files; narrow the roots or increase --max-files")
    if not real:
        diagnostics.append("Only synthetic Joern fixtures were found; real-corpus execution is blocked" if synthetic else "No local Joern interchange export with a resolvable project was found")
    return {"schema_version": "CodeSlicerJoernCorpusDiscovery/v1", "status": "ready" if real else "blocked", "real_candidates": real, "synthetic_candidates": synthetic, "candidate_count": len(candidates), "scanned_files": scanned_files, "limits": {"max_files": max_files, "timeout_seconds": timeout_seconds, "include_synthetic": include_synthetic}, "stopped_reason": stopped_reason, "diagnostics": diagnostics, "privacy": {"mode": "local-only", "network_used": False, "joern_invoked": False}}
