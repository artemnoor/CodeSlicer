"""Evidence-oriented benchmark runner for semantic precision."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.graph_quality import graph_fingerprint


def run_benchmark_fixture(manifest_path: str | Path) -> dict[str, Any]:
    manifest_file = Path(manifest_path).resolve()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    project_path = _resolve_project(manifest_file.parent, manifest["project_path"])
    result = analyze_project_core(str(project_path))
    graph = result["graph"]
    edge_kinds = set(manifest.get("edge_kinds", []))
    actual = _edge_keys(graph.get("edges", []), edge_kinds or None)
    expected = {_edge_key(item) for item in _load_list(manifest_file.parent / manifest.get("expected_edges", "expected_edges.json"))}
    forbidden = {_edge_key(item) for item in _load_list(manifest_file.parent / manifest.get("forbidden_edges", "forbidden_edges.json"))}
    true_positive = len(expected & actual)
    false_negative = len(expected - actual)
    false_positive = len(forbidden & actual)
    has_positive_case = bool(true_positive or false_positive or false_negative)
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else (None if not has_positive_case else 0.0)
    recall = true_positive / len(expected) if expected else (None if not has_positive_case else 1.0)
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else (None if not has_positive_case else 0.0)
    return {
        "fixture_id": manifest.get("fixture_id", manifest.get("name", manifest_file.parent.name)),
        "fixture": manifest.get("name", manifest_file.parent.name),
        "category": manifest.get("category", "unknown"),
        "language": manifest.get("language", manifest.get("category", "unknown")),
        "resolver_rules": manifest.get("resolver_rules", []),
        "positive_support": bool(manifest.get("positive_support", bool(expected))),
        "status": "passed" if false_positive == 0 and false_negative == 0 and has_positive_case else ("no_positive_cases" if not has_positive_case else "failed"),
        "project_path": str(project_path),
        "expected_edges": len(expected),
        "actual_edges": len(actual),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": round(precision, 6) if precision is not None else None,
        "scope": "edge_kinds=" + ",".join(sorted(edge_kinds)) if edge_kinds else "all_edges",
        "recall": round(recall, 6) if recall is not None else None,
        "f1": round(f1, 6) if f1 is not None else None,
        "forbidden_violations": sorted(_edge_key_to_string(item) for item in forbidden & actual),
        "graph_fingerprint": graph_fingerprint_from_dict(graph),
        "coverage": graph.get("metadata", {}).get("resolution_coverage", {}),
    }


def run_benchmark_suite(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    manifests = sorted(root_path.rglob("benchmark_manifest.json"))
    runs = [run_benchmark_fixture(path) for path in manifests]
    overall = aggregate_metrics(runs)
    quality_gates = {
        "forbidden_violations_zero": overall["forbidden_violations"] == 0,
        "precision_at_least_0_95": overall["precision"] >= 0.95,
        "positive_support_has_tp": all(not run.get("positive_support") or run["true_positive"] > 0 for run in runs),
    }
    return {
        "status": "ok" if all(item["status"] in {"passed", "no_positive_cases"} for item in runs) and all(quality_gates.values()) else "failed",
        "root": str(root_path),
        "fixtures": len(runs),
        "passed": sum(item["status"] == "passed" for item in runs),
        "failed": sum(item["status"] == "failed" for item in runs),
        "overall": overall,
        "quality_gates": quality_gates,
        "by_language": _aggregate_by(runs, "language"),
        "by_resolver_rule": _aggregate_by_rule(runs),
        "resolution_rule_breakdown": _resolution_rule_breakdown(runs),
        "by_fixture": {item["fixture_id"]: item for item in runs},
        "runs": runs,
    }


SUPPORTED_MUTATIONS = {
    "remove_binding",
    "replace_provider",
    "add_second_candidate",
    "rename_alias",
    "remove_import",
    "change_receiver_type",
}


def run_mutation_suite(root: str | Path) -> dict[str, Any]:
    """Run manifest-declared mutations in isolated temporary project copies.

    Mutations are deliberately textual and fixture-owned.  The runner never
    changes the source fixture and rejects unknown operation names, so a
    mutation result remains reproducible and auditable.
    """
    root_path = Path(root).resolve()
    reports: list[dict[str, Any]] = []
    for manifest_path in sorted(root_path.rglob("benchmark_manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mutations = manifest.get("mutations", [])
        if not mutations:
            continue
        baseline = run_benchmark_fixture(manifest_path)
        project_path = _resolve_project(manifest_path.parent, manifest["project_path"])
        baseline_result = analyze_project_core(str(project_path))
        baseline_graph = baseline_result["graph"]
        baseline_edges = _edge_records(baseline_graph, set(manifest.get("edge_kinds", [])) or None)
        forbidden = {_edge_key(item) for item in _load_list(manifest_path.parent / manifest.get("forbidden_edges", "forbidden_edges.json"))}
        for spec in mutations:
            reports.append(_run_mutation(manifest, manifest_path, project_path, baseline, baseline_edges, forbidden, spec))
    passed = sum(item["status"] == "passed" for item in reports)
    failed = len(reports) - passed
    return {
        "status": "ok" if failed == 0 else "failed",
        "root": str(root_path),
        "mutations": len(reports),
        "mutation_passed": passed,
        "mutation_failed": failed,
        "quality_gates": {"mutation_failures_zero": failed == 0},
        "runs": reports,
    }


def _run_mutation(manifest: dict[str, Any], manifest_path: Path, project_path: Path,
                  baseline: dict[str, Any], baseline_edges: dict[tuple[str, str, str], dict[str, Any]],
                  forbidden: set[tuple[str, str, str]], spec: dict[str, Any]) -> dict[str, Any]:
    operation = str(spec.get("operation", ""))
    checks = list(spec.get("checks", []))
    errors: list[str] = []
    if operation not in SUPPORTED_MUTATIONS:
        errors.append(f"unsupported mutation operation: {operation}")
    old = spec.get("old")
    if not isinstance(old, str) or not old:
        errors.append("mutation requires non-empty 'old' text")
    if errors:
        return {"fixture_id": manifest.get("fixture_id", manifest_path.parent.name), "mutation_id": spec.get("id"), "operation": operation, "status": "failed", "errors": errors}

    with tempfile.TemporaryDirectory(prefix="impact-engine-mutation-") as temp:
        mutated_project = Path(temp) / project_path.name
        shutil.copytree(project_path, mutated_project)
        target = mutated_project / str(spec.get("file", ""))
        if not target.exists():
            return _mutation_failure(manifest, spec, f"mutation file does not exist: {spec.get('file')}")
        edits = spec.get("edits") or [{"file": spec.get("file", ""), "old": old, "new": spec.get("new", "")}]
        for edit in edits:
            edit_target = mutated_project / str(edit.get("file", ""))
            if not edit_target.exists():
                return _mutation_failure(manifest, spec, f"mutation file does not exist: {edit.get('file')}")
            text = edit_target.read_text(encoding="utf-8")
            edit_old = str(edit.get("old", ""))
            if text.count(edit_old) != 1:
                return _mutation_failure(manifest, spec, f"mutation text must occur exactly once: {edit_old!r}")
            edit_target.write_text(text.replace(edit_old, str(edit.get("new", "")), 1), encoding="utf-8")
        result = analyze_project_core(str(mutated_project))
        graph = result["graph"]
        actual = _edge_records(graph, set(manifest.get("edge_kinds", [])) or None)
        observed = _evaluate_mutation_checks(checks, baseline_edges, actual, forbidden, {**baseline, **spec}, result)
        failed_checks = [name for name, ok in observed.items() if not ok]
        return {
            "fixture_id": manifest.get("fixture_id", manifest_path.parent.name),
            "mutation_id": spec.get("id"),
            "operation": operation,
            "status": "passed" if not failed_checks else "failed",
            "checks": observed,
            "failed_checks": failed_checks,
            "expected_outcomes": {key: spec[key] for key in ("expected_target", "forbidden_targets", "expected_resolution_status", "expected_validation_status", "expected_confidence_range", "expected_unknown_region_kind") if key in spec},
            "baseline_edges": len(baseline_edges),
            "mutated_edges": len(actual),
            "mutated_edge_details": [
                {"from": key[0], "to": key[1], "kind": key[2], "confidence": edge.get("confidence"), "resolution_status": edge.get("properties", {}).get("resolution_status"), "validation_status": edge.get("properties", {}).get("validation_status")}
                for key, edge in sorted(actual.items())
            ],
        }


def _evaluate_mutation_checks(checks: list[str], baseline: dict[tuple[str, str, str], dict[str, Any]],
                              mutated: dict[tuple[str, str, str], dict[str, Any]], forbidden: set[tuple[str, str, str]],
                              baseline_report: dict[str, Any], mutated_result: dict[str, Any]) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for check in checks:
        if check == "edge_removed":
            result[check] = set(baseline) - set(mutated) != set()
        elif check == "edge_added":
            result[check] = bool(set(mutated) - set(baseline))
        elif check == "edge_target_changed":
            result[check] = any(a[0] == b[0] and a[2] == b[2] and a[1] != b[1] for a in baseline for b in mutated)
        elif check == "status_changed":
            result[check] = any(baseline[key].get("properties", {}).get("resolution_status") != mutated[key].get("properties", {}).get("resolution_status") for key in set(baseline) & set(mutated))
        elif check == "confidence_lowered":
            result[check] = any(float(mutated[key].get("confidence", 1.0)) < float(baseline[key].get("confidence", 1.0)) for key in set(baseline) & set(mutated))
        elif check == "unknown_region_created":
            before = baseline_report.get("coverage", {}).get("actionable_unresolved", 0)
            after = mutated_result["graph"].get("metadata", {}).get("resolution_coverage", {}).get("actionable_unresolved", 0)
            result[check] = after > before
        elif check == "ambiguous_or_confidence_lowered":
            result[check] = any(
                str(edge.get("properties", {}).get("resolution_status", "")).lower() == "ambiguous"
                or float(edge.get("confidence", 1.0)) < float(baseline[key].get("confidence", 1.0))
                for key, edge in mutated.items() if key in baseline
            ) or any(str(edge.get("properties", {}).get("resolution_status", "")).lower() == "ambiguous" for edge in mutated.values())
        elif check == "expected_target":
            result[check] = any(edge[1] == str(baseline_report.get("expected_target")) for edge in mutated)
        elif check == "forbidden_targets":
            result[check] = not any(edge[1] in set(baseline_report.get("forbidden_targets", [])) for edge in mutated)
        elif check == "expected_resolution_status":
            result[check] = any(str(edge.get("properties", {}).get("resolution_status")) == str(baseline_report.get("expected_resolution_status")) for edge in mutated.values())
        elif check == "expected_validation_status":
            result[check] = any(str(edge.get("properties", {}).get("validation_status")) == str(baseline_report.get("expected_validation_status")) for edge in mutated.values())
        elif check == "expected_confidence_range":
            bounds = baseline_report.get("expected_confidence_range", [])
            result[check] = len(bounds) == 2 and any(float(bounds[0]) <= float(edge.get("confidence", -1)) <= float(bounds[1]) for edge in mutated.values())
        elif check == "expected_unknown_region_kind":
            regions = mutated_result["graph"].get("metadata", {}).get("unknown_regions", {}).get("regions", [])
            expected_kind = str(baseline_report.get("expected_unknown_region_kind"))
            result[check] = any(str(region.get("kind") or region.get("details", {}).get("taxonomy")) == expected_kind for region in regions)
        elif check == "forbidden_edge_absent":
            result[check] = not (set(mutated) & forbidden)
        else:
            result[check] = False
    return result


def _mutation_failure(manifest: dict[str, Any], spec: dict[str, Any], error: str) -> dict[str, Any]:
    return {"fixture_id": manifest.get("fixture_id"), "mutation_id": spec.get("id"), "operation": spec.get("operation"), "status": "failed", "errors": [error]}


def _edge_records(graph: dict[str, Any], edge_kinds: set[str] | None) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {_edge_key(edge): edge for edge in graph.get("edges", []) if edge_kinds is None or str(edge.get("kind")) in edge_kinds}


def _aggregate_by(runs: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    return {str(value): aggregate_metrics([run for run in runs if str(run.get(field)) == str(value)]) for value in sorted({str(run.get(field)) for run in runs})}


def _aggregate_by_rule(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rules = sorted({rule for run in runs for rule in run.get("resolver_rules", [])})
    return {rule: aggregate_metrics([run for run in runs if rule in run.get("resolver_rules", [])]) for rule in rules}


def _resolution_rule_breakdown(runs: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for run in runs:
        totals = run.get("coverage", {}).get("totals", {})
        for rule in run.get("resolver_rules", []):
            bucket = result.setdefault(rule, {"resolved_exact": 0, "resolved_inferred": 0, "ambiguous": 0, "actionable_unresolved": 0})
            for key in bucket:
                bucket[key] += int(totals.get(key, 0) or 0)
    return result


def run_determinism_check(project_path: str | Path, runs: int = 3) -> dict[str, Any]:
    fingerprints = []
    coverage_fingerprints = []
    canonical_fingerprints = []
    for _ in range(max(2, runs)):
        result = analyze_project_core(str(project_path))
        graph = result["graph"]
        fingerprints.append(graph_fingerprint_from_dict(graph))
        coverage_fingerprints.append(json.dumps(graph.get("metadata", {}).get("resolution_coverage", {}), sort_keys=True))
        canonical_fingerprints.append(_canonical_ids(graph))
    return {
        "status": "ok" if len(set(fingerprints)) == 1 and len(set(coverage_fingerprints)) == 1 else "failed",
        "runs": len(fingerprints),
        "graph_fingerprints": fingerprints,
        "coverage_equal": len(set(coverage_fingerprints)) == 1,
        "canonical_ids_equal": len(set(canonical_fingerprints)) == 1,
    }


def run_determinism_suite(root: str | Path, runs: int = 3) -> dict[str, Any]:
    root_path = Path(root).resolve()
    reports = []
    for manifest_path in sorted(root_path.rglob("benchmark_manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        project_path = _resolve_project(manifest_path.parent, manifest["project_path"])
        report = run_determinism_check(project_path, runs=runs)
        report["fixture_id"] = manifest.get("fixture_id", manifest_path.parent.name)
        reports.append(report)
    return {
        "status": "ok" if all(report["status"] == "ok" for report in reports) else "failed",
        "fixtures": len(reports),
        "determinism": all(report["status"] == "ok" for report in reports),
        "runs": reports,
    }


def aggregate_metrics(runs: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(item["true_positive"] for item in runs)
    fp = sum(item["false_positive"] for item in runs)
    fn = sum(item["false_negative"] for item in runs)
    has_positive_case = bool(tp or fp or fn)
    precision = tp / (tp + fp) if tp + fp else (None if not has_positive_case else 0.0)
    recall = tp / (tp + fn) if tp + fn else (None if not has_positive_case else 1.0)
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "forbidden_violations": sum(item.get("false_positive", 0) for item in runs),
        "precision": round(precision, 6) if precision is not None else None,
        "recall": round(recall, 6) if recall is not None else None,
        "f1": round(2 * precision * recall / (precision + recall), 6) if precision is not None and recall is not None and precision + recall else (None if not has_positive_case else 0.0),
        "status": "positive_cases" if has_positive_case else "no_positive_cases",
    }


def graph_fingerprint_from_dict(graph: dict[str, Any]) -> str:
    from impact_engine.models import GraphDocument

    return graph_fingerprint(GraphDocument.from_dict(graph))


def _edge_keys(edges: list[dict[str, Any]], edge_kinds: set[str] | None = None) -> set[tuple[str, str, str]]:
    return {_edge_key(edge) for edge in edges if edge_kinds is None or str(edge.get("kind")) in edge_kinds}


def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str]:
    return str(edge.get("from") or edge.get("from_node")), str(edge.get("to") or edge.get("to_node")), str(edge.get("kind"))


def _edge_key_to_string(key: tuple[str, str, str]) -> str:
    return f"{key[0]} --{key[2]}--> {key[1]}"


def _load_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("edges", [])


def _resolve_project(base: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _canonical_ids(graph: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(str(node.get("properties", {}).get("stable_id", "")) for node in graph.get("nodes", [])))
