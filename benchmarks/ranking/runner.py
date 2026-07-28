"""Deterministic local evaluator for the review ranking projection."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.models import GraphDocument
from impact_engine.ranking_policy import DEFAULT_RANKING_POLICY, REVIEW_PROJECTION_POLICY_VERSION, TEST_SELECTION_POLICY_VERSION, REVIEW_SCHEMA_VERSION
from impact_engine.review import build_review_report


DEFAULT_QUALITY_GATES = {
    "min_top_5_precision": 0.80,
    "min_top_10_recall": 0.80,
    "min_test_recommendation_precision": 0.80,
    "max_noise_ratio": 0.25,
    "min_explanation_completeness": 0.90,
    "min_default_entities_are_actionable": 0.95,
    "max_review_seconds": 30.0,
}


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _unavailable(project: Path, diff: Path | None, scenario: str) -> dict[str, Any]:
    return {
        "schema_version": "impact-engine.ranking-report.v1", "status": "corpus_unavailable",
        "corpus": {"scenario": scenario, "path": str(project), "diff": str(diff) if diff else None, "available": False},
        "policy": {"ranking_policy_version": DEFAULT_RANKING_POLICY.version, "review_projection_policy_version": REVIEW_PROJECTION_POLICY_VERSION, "test_selection_policy_version": TEST_SELECTION_POLICY_VERSION, "review_schema_version": REVIEW_SCHEMA_VERSION},
        "metrics": {}, "quality_gates": {"status": "not_evaluable", "reason": "corpus_unavailable"}, "comparison": {"status": "not_run"}, "diagnostics": ["corpus_unavailable"],
    }


def _expected(scenario: Path) -> dict[str, Any]:
    path = scenario / "expected.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _project_path(scenario: Path, expected: dict[str, Any]) -> Path:
    configured = expected.get("project")
    return (scenario / configured).resolve() if configured else (scenario / "project").resolve()


def _manifest_expected(corpus: Path) -> dict[str, Any]:
    manifest_path = ROOT / "tests" / "fixtures" / "review_corpora.json"
    if not manifest_path.is_file():
        return {}
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    name = corpus.name
    item = (data.get("cases") or {}).get(name, {})
    if not item:
        return {}
    return {
        "expected_top_5_entities": item.get("expected_top_impacts", []),
        # The corpus manifest pins top-5 relevance, not every admissible
        # top-10 alternative.  Leave allowed_top_10 open for the metric run.
        "allowed_top_10_entities": [],
        "expected_tests": item.get("expected_test_files", []),
        "expected_chain_status": item.get("expected_chain_status"),
        "quality_gates": {"max_review_seconds": item.get("max_review_seconds", item.get("max_duration_seconds", 30.0))},
    }


def _entity_key(value: Any) -> str:
    """Compare semantic IDs while tolerating extractor kind aliases."""
    text = str(value or "")
    for prefix in ("method:", "function:", "class:"):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


def _metrics(report: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    top = report.get("top_impacts", [])
    top_ids = [_entity_key(item.get("entity_id")) for item in top]
    expected_top = {_entity_key(item) for item in expected.get("expected_top_5_entities", [])}
    expected_tests = set(expected.get("expected_tests", []))
    actual_tests = {str(item.get("file")) for item in report.get("test_recommendations", []) if item.get("file")}
    forbidden_ids = {_entity_key(item) for item in expected.get("forbidden_noise_entities", [])}
    forbidden_kinds = {"ASSIGNMENT", "CALL_EXPR", "EXTERNAL_LIBRARY", "SUPPORT_PACK", "LIBRARY"}
    noise_count = sum(1 for item in top if item.get("kind") in forbidden_kinds or item.get("entity_id") in forbidden_ids)
    evidence_min = int((expected.get("explanation_evidence_requirements") or {}).get("minimum_evidence_per_top_result", 1))
    complete = 0
    for item in top:
        evidence = (item.get("why_affected") or {}).get("evidence") or (item.get("why") or {}).get("evidence_locations") or []
        if len(evidence) >= evidence_min:
            complete += 1
    actionable = sum(1 for item in top if item.get("kind") not in forbidden_kinds and item.get("confidence") != "speculative")
    precision_denominator = max(1, min(5, len(top)))
    recall_denominator = max(1, len(expected_top))
    test_denominator = max(1, len(actual_tests))
    return {
        "top_5_precision": round(len(set(top_ids[:5]) & expected_top) / precision_denominator, 6),
        "top_10_recall": round(len(set(top_ids[:10]) & expected_top) / recall_denominator, 6),
        "test_recommendation_precision": round(len(actual_tests & expected_tests) / test_denominator, 6) if actual_tests else (1.0 if not expected_tests else 0.0),
        "noise_ratio": round(noise_count / max(1, len(top)), 6),
        "explanation_completeness": round(complete / max(1, len(top)), 6),
        "review_entity_count": len(top),
        "default_entities_are_actionable": round(actionable / max(1, len(top)), 6),
        "developer_time_to_decision_proxy": len(top) + (2 * len(report.get("warnings", []))) + (3 if report.get("risk", {}).get("level") == "UNKNOWN" else 0),
        "chain_status": report.get("chain_summary", {}).get("status"),
        "risk": report.get("risk", {}).get("level"),
        "confidence": report.get("risk", {}).get("confidence"),
    }


def _quality_gates(metrics: dict[str, Any], expected: dict[str, Any], review_time_seconds: float, max_review_seconds: float | None = None) -> dict[str, Any]:
    """Apply absolute gates from policy-independent golden expectations.

    A current-policy baseline is useful for regression comparison, but cannot
    certify absolute quality.  These gates are evaluated against human/pinned
    labels in ``expected.json`` and fixed safety thresholds.
    """
    configured = dict(DEFAULT_QUALITY_GATES)
    configured.update(expected.get("quality_gates") or {})
    if max_review_seconds is not None:
        configured["max_review_seconds"] = max_review_seconds
    has_impact_labels = bool(expected.get("expected_top_5_entities"))
    has_test_labels = bool(expected.get("expected_tests"))
    checks: dict[str, dict[str, Any]] = {}

    def check(name: str, actual: float, threshold: float, comparator: str, evaluable: bool = True) -> None:
        passed = None if not evaluable else (actual >= threshold if comparator == "min" else actual <= threshold)
        checks[name] = {"actual": round(actual, 6), "threshold": threshold, "comparator": comparator, "passed": passed, "source": "manual_golden" if name in {"top_5_precision", "top_10_recall", "test_recommendation_precision"} else "minimum_thresholds"}

    check("top_5_precision", float(metrics.get("top_5_precision", 0.0)), float(configured["min_top_5_precision"]), "min", has_impact_labels)
    check("top_10_recall", float(metrics.get("top_10_recall", 0.0)), float(configured["min_top_10_recall"]), "min", has_impact_labels)
    check("test_recommendation_precision", float(metrics.get("test_recommendation_precision", 0.0)), float(configured["min_test_recommendation_precision"]), "min", has_test_labels)
    check("noise_ratio", float(metrics.get("noise_ratio", 1.0)), float(configured["max_noise_ratio"]), "max")
    check("explanation_completeness", float(metrics.get("explanation_completeness", 0.0)), float(configured["min_explanation_completeness"]), "min")
    check("default_entities_are_actionable", float(metrics.get("default_entities_are_actionable", 0.0)), float(configured["min_default_entities_are_actionable"]), "min")
    check("review_time_seconds", review_time_seconds, float(configured["max_review_seconds"]), "max")
    failed = [name for name, item in checks.items() if item["passed"] is False]
    unevaluable = [name for name, item in checks.items() if item["passed"] is None]
    status = "failed" if failed else "not_evaluable" if len(unevaluable) == len(checks) else "passed"
    return {"status": status, "checks": checks, "failed": failed, "not_evaluable": unevaluable, "policy_independent": True}


def _compare(metrics: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    if not baseline:
        return {"status": "no_baseline"}
    baseline_kind = baseline.get("baseline_kind")
    baseline_policy = baseline.get("policy", {}).get("ranking_policy_version")
    if baseline_kind not in {"manual_golden", "historical_review"}:
        return {"status": "ignored_non_independent_baseline", "reason": "baseline has no independent provenance; absolute gates remain authoritative", "baseline_policy_version": baseline_policy}
    quality = ("top_5_precision", "top_10_recall", "test_recommendation_precision", "explanation_completeness", "default_entities_are_actionable")
    regressions = [key for key in quality if float(metrics.get(key, 0.0)) < float(baseline.get("metrics", {}).get(key, 0.0))]
    return {"status": "regression" if regressions else "passed", "regressions": regressions, "baseline_policy_version": baseline.get("policy", {}).get("ranking_policy_version")}


def _golden_checks(report: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    top_ids = [_entity_key(item.get("entity_id")) for item in report.get("top_impacts", [])]
    allowed = {_entity_key(item) for item in expected.get("allowed_top_10_entities", [])}
    forbidden = {_entity_key(item) for item in expected.get("forbidden_noise_entities", [])}
    actual_tests = {str(item.get("file")) for item in report.get("test_recommendations", []) if item.get("file")}
    expected_tests = set(expected.get("expected_tests", []))
    failures = []
    if allowed:
        failures.extend(f"unexpected_top_entity:{item}" for item in top_ids[:10] if item not in allowed)
    failures.extend(f"forbidden_noise_entity:{item}" for item in top_ids if item in forbidden)
    if expected.get("expected_tests") is not None and actual_tests != expected_tests:
        failures.append("targeted_tests_mismatch")
    expected_chain = expected.get("expected_chain_status")
    if expected_chain and report.get("chain_summary", {}).get("status") != expected_chain:
        failures.append("chain_status_mismatch")
    expected_risk = expected.get("expected_risk")
    if expected_risk and report.get("risk", {}).get("level") != expected_risk:
        failures.append("risk_mismatch")
    expected_confidence = expected.get("expected_confidence")
    if expected_confidence and report.get("risk", {}).get("confidence") != expected_confidence:
        failures.append("confidence_mismatch")
    return {"status": "passed" if not failures else "failed", "failures": failures}


def run_scenario(scenario: Path, *, baseline_path: Path | None = None, max_review_seconds: float | None = None) -> dict[str, Any]:
    scenario = scenario.resolve()
    if baseline_path is None:
        candidate_baseline = ROOT / "benchmarks" / "ranking" / "baseline" / f"{scenario.name}.json"
        baseline_path = candidate_baseline if candidate_baseline.is_file() else None
    expected = _expected(scenario)
    project = _project_path(scenario, expected)
    diff_path = scenario / "diff.patch"
    if not project.is_dir() or not diff_path.is_file():
        return _unavailable(project, diff_path, scenario.name)
    with tempfile.TemporaryDirectory(prefix="impact-engine-ranking-") as temporary:
        working = Path(temporary) / project.name
        shutil.copytree(project, working, ignore=shutil.ignore_patterns(".git", ".impact_engine", "node_modules", "dist", "build", "__pycache__"))
        source_graph = project / ".impact_engine" / "graph.json"
        if source_graph.is_file():
            graph = GraphDocument.from_json(source_graph.read_text(encoding="utf-8"))
        else:
            result = analyze_project_core(str(working), out_path=str(working / ".impact_engine" / "graph.json"))
            graph = GraphDocument.from_dict(result["graph"])
        started = time.perf_counter()
        report = build_review_report(str(working), graph=graph, diff_text=diff_path.read_text(encoding="utf-8"), refresh="never", max_results=10)
        review_time_seconds = round(time.perf_counter() - started, 6)
        metrics = _metrics(report, expected)
        metrics["review_time_seconds"] = review_time_seconds
        quality_gates = _quality_gates(metrics, expected, review_time_seconds, max_review_seconds)
        golden_checks = _golden_checks(report, expected)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path and baseline_path.is_file() else None
    comparison = _compare(metrics, baseline)
    failed_quality = quality_gates.get("status") == "failed"
    return {
        "schema_version": "impact-engine.ranking-report.v1",
        "status": "regression" if comparison.get("status") == "regression" or golden_checks.get("status") == "failed" or failed_quality else "ok",
        "corpus": {"scenario": scenario.name, "path": str(project), "diff_sha256": _hash(diff_path), "available": True},
        "policy": {"ranking_policy_version": DEFAULT_RANKING_POLICY.version, "review_projection_policy_version": REVIEW_PROJECTION_POLICY_VERSION, "test_selection_policy_version": TEST_SELECTION_POLICY_VERSION, "review_schema_version": REVIEW_SCHEMA_VERSION},
        "metrics": metrics, "quality_gates": quality_gates, "comparison": comparison, "golden_checks": golden_checks,
        "golden": {"changed_entities": expected.get("changed_entities", []), "expected_top_5_entities": expected.get("expected_top_5_entities", []), "allowed_top_10_entities": expected.get("allowed_top_10_entities", []), "expected_tests": expected.get("expected_tests", [])},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--diff", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-review-seconds", type=float, default=None)
    args = parser.parse_args(argv)
    if bool(args.scenario) == bool(args.corpus):
        parser.error("choose exactly one of --scenario or --corpus")
    if args.corpus:
        if not args.corpus.is_dir():
            report = _unavailable(args.corpus.resolve(), args.diff.resolve() if args.diff else None, args.corpus.name)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0
        scenario = Path(tempfile.mkdtemp(prefix="impact-engine-ranking-scenario-"))
        try:
            project_link = scenario / "project"
            shutil.copytree(args.corpus, project_link, ignore=shutil.ignore_patterns(".git", ".impact_engine", "node_modules", "dist", "build", "__pycache__"))
            source_graph = args.corpus / ".impact_engine" / "graph.json"
            if source_graph.is_file():
                (project_link / ".impact_engine").mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_graph, project_link / ".impact_engine" / "graph.json")
            if args.diff:
                shutil.copy2(args.diff, scenario / "diff.patch")
            manifest_expected = _manifest_expected(args.corpus.resolve())
            if manifest_expected:
                (scenario / "expected.json").write_text(json.dumps(manifest_expected), encoding="utf-8")
            baseline = args.baseline or (ROOT / "benchmarks" / "ranking" / "baseline" / f"{args.corpus.name}.json")
            report = run_scenario(scenario, baseline_path=baseline, max_review_seconds=args.max_review_seconds)
            report["corpus"]["scenario"] = args.corpus.name
            report["corpus"]["path"] = str(args.corpus.resolve())
        finally:
            shutil.rmtree(scenario, ignore_errors=True)
    else:
        report = run_scenario(args.scenario, baseline_path=args.baseline, max_review_seconds=args.max_review_seconds)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report.get("status") in {"error", "regression"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
