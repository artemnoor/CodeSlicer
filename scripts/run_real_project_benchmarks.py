"""Run reproducible CLI validation against pinned public source projects.

The runner only writes to disposable working copies.  It deliberately does not
install or execute a benchmark project's dependencies: it validates the
CodeSlicer scan/analyze/review workflow itself, including a review over a
minimal, source-anchored diff.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from impact_engine import __version__


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "benchmarks" / "real_projects" / "manifest.json"
IGNORE = shutil.ignore_patterns(".git", ".impact_engine", ".codeslicer", "node_modules", ".venv", "venv", "dist", "build", ".next", "coverage", "__pycache__")


def _env() -> dict[str, str]:
    environment = os.environ.copy()
    source = str(ROOT / "src")
    environment["PYTHONPATH"] = source + os.pathsep + environment.get("PYTHONPATH", "")
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def _run(command: list[str], *, cwd: Path, timeout: int = 900) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    result = subprocess.run(command, cwd=cwd, env=_env(), text=True, capture_output=True, timeout=timeout)
    elapsed = round(time.perf_counter() - started, 6)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip().replace("\n", " ")
        raise RuntimeError(f"CLI command failed ({result.returncode}): {message[:800]}")
    try:
        return json.loads(result.stdout), elapsed
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"CLI did not return JSON: {result.stdout[:800]!r}") from exc


def _git_head(project: Path) -> str | None:
    result = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], text=True, capture_output=True, timeout=20)
    return result.stdout.strip() if result.returncode == 0 else None


def _materialize(spec: dict[str, Any], source_root: Path | None, destination: Path) -> tuple[Path, str | None, Path]:
    if source_root is not None:
        source = source_root / str(spec["id"])
        if not source.is_dir():
            raise FileNotFoundError(f"missing source directory for {spec['id']}: {source}")
        shutil.copytree(source, destination, ignore=IGNORE)
        return destination, _git_head(source), source
    repository = str(spec["repository"])
    expected_commit = str(spec.get("commit") or "")
    if not expected_commit:
        raise ValueError(f"{spec['id']} has no pinned commit")
    # Do not clone the moving default branch and merely compare it afterwards:
    # a later upstream commit would make the benchmark impossible to reproduce.
    # Fetching the manifest SHA makes the no-source-root path deterministic too.
    subprocess.run(["git", "init", str(destination)], check=True, text=True, capture_output=True, timeout=30)
    subprocess.run(["git", "-C", str(destination), "remote", "add", "origin", repository], check=True, text=True, capture_output=True, timeout=20)
    subprocess.run(["git", "-C", str(destination), "fetch", "--depth", "2", "origin", expected_commit], check=True, text=True, capture_output=True, timeout=300)
    subprocess.run(["git", "-C", str(destination), "checkout", "--detach", "FETCH_HEAD"], check=True, text=True, capture_output=True, timeout=60)
    return destination, _git_head(destination), destination


def _historical_diff(source: Path, destination: Path) -> tuple[Path, int]:
    result = subprocess.run(
        ["git", "-C", str(source), "diff", "--binary", "HEAD~1", "HEAD", "--"],
        text=True, capture_output=True, timeout=30,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"a non-empty HEAD~1..HEAD diff is required for {source}")
    # Keep the external diff outside project root: otherwise adding the input
    # file itself changes the source snapshot and correctly makes Review stale.
    target = destination.parent / f"{destination.name}.historical-commit.diff"
    target.write_text(result.stdout, encoding="utf-8")
    changed_files = sum(1 for line in result.stdout.splitlines() if line.startswith("+++ b/"))
    return target, changed_files


def _source_diff(project: Path, mutation: dict[str, str]) -> Path:
    relative = Path(mutation["file"])
    target = project / relative
    if not target.is_file():
        raise FileNotFoundError(f"mutation target is missing: {relative.as_posix()}")
    original = target.read_text(encoding="utf-8")
    anchor = str(mutation["anchor"])
    if original.count(anchor) != 1:
        raise ValueError(f"mutation anchor must occur once in {relative.as_posix()}: {anchor!r}")
    updated = original.replace(anchor, f"{mutation['comment']}\n{anchor}", 1)
    target.write_text(updated, encoding="utf-8")
    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True), updated.splitlines(keepends=True),
        fromfile=f"a/{relative.as_posix()}", tofile=f"b/{relative.as_posix()}", n=3,
    ))
    if not diff:
        raise RuntimeError(f"mutation produced an empty diff for {relative.as_posix()}")
    # As with the historical input, keep the diff outside the tree being
    # fingerprinted so the control changes only the source comment.
    diff_path = project.parent / f"{project.name}.freshness-control.diff"
    diff_path.write_text(diff, encoding="utf-8")
    return diff_path


def _behavioral_diff(project: Path, change: dict[str, Any]) -> tuple[Path, Path, str]:
    """Apply one reversible behavior change and return its exact external diff."""
    relative = Path(str(change["file"]))
    target = project / relative
    if not target.is_file():
        raise FileNotFoundError(f"behavioral-change target is missing: {relative.as_posix()}")
    original = target.read_text(encoding="utf-8")
    before = str(change["before"])
    after = str(change["after"])
    if original.count(before) != 1:
        raise ValueError(f"behavioral-change source must occur once in {relative.as_posix()}: {before!r}")
    updated = original.replace(before, after, 1)
    target.write_text(updated, encoding="utf-8")
    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True), updated.splitlines(keepends=True),
        fromfile=f"a/{relative.as_posix()}", tofile=f"b/{relative.as_posix()}", n=3,
    ))
    if not diff:
        raise RuntimeError(f"behavioral change produced an empty diff for {relative.as_posix()}")
    diff_path = project.parent / f"{project.name}.{change['id']}.diff"
    diff_path.write_text(diff, encoding="utf-8")
    return target, diff_path, original


def _test_command(command: list[str], *, cwd: Path, expected_test: str) -> dict[str, Any]:
    """Run an explicit, shell-free target test and retain minimal evidence."""
    started = time.perf_counter()
    result = subprocess.run(command, cwd=cwd, env=_env(), text=True, capture_output=True, timeout=300)
    output = f"{result.stdout}\n{result.stderr}"
    return {
        "command": command,
        "exit_code": result.returncode,
        "wall_seconds": round(time.perf_counter() - started, 6),
        "mentions_expected_test": expected_test in output,
    }


def _evidence_items(value: Any) -> list[dict[str, Any]]:
    """Keep a bounded, JSON-safe review projection for a human benchmark."""
    if not isinstance(value, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in value[:5]:
        if not isinstance(item, dict):
            continue
        why = item.get("why_affected") if isinstance(item.get("why_affected"), dict) else {}
        locations = why.get("evidence") if isinstance(why.get("evidence"), list) else []
        compact.append({
            "entity_id": item.get("entity_id"), "symbol": item.get("symbol") or item.get("label"),
            "kind": item.get("kind"), "impact_class": item.get("impact_class") or item.get("class"),
            "impact_tier": item.get("impact_tier"), "review_confidence": item.get("confidence"),
            "evidence_confidence": why.get("confidence"), "rank_score": item.get("rank_score"),
            "chain": list(why.get("chain") or []),
            "evidence": [
                {key: location.get(key) for key in ("file", "line", "kind", "source", "confidence", "description")}
                for location in locations[:3] if isinstance(location, dict)
            ],
        })
    return compact


def _changed_symbol_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        {key: item.get(key) for key in ("id", "kind", "file", "line", "changed_lines")}
        for item in value[:5] if isinstance(item, dict)
    ]


def _count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _review(project: Path, diff: Path, scope: str, refresh: str) -> tuple[dict[str, Any], float]:
    return _run([
        sys.executable, "-m", "impact_engine.cli", "review", str(project), "--source", "diff-file", "--diff-file", str(diff),
        "--refresh", refresh, "--run-tests", "suggested", "--no-daemon", "--scope", scope, "--json",
    ], cwd=project)


def _review_summary(review: dict[str, Any], elapsed: float, *, diff_file: str, changed_files: int | None = None) -> dict[str, Any]:
    summary = {
        "wall_seconds": elapsed, "schema_version": review.get("schema_version"), "risk": review.get("risk"),
        "risk_confidence": review.get("risk_confidence"), "top_impacts": _count(review.get("top_impacts")),
        "test_recommendations": _count(review.get("test_recommendations")), "errors": _count(review.get("errors")),
        "diff_file": diff_file,
    }
    if changed_files is not None:
        summary["changed_files"] = changed_files
    return summary


def run_case(spec: dict[str, Any], source_root: Path | None, work_root: Path) -> dict[str, Any]:
    expected_commit = str(spec.get("commit") or "")
    project, actual_commit, source = _materialize(spec, source_root, work_root / str(spec["id"]))
    if expected_commit and actual_commit != expected_commit:
        raise RuntimeError(f"{spec['id']} is at {actual_commit or 'no git metadata'}, expected {expected_commit}")
    # The commands use the canonical .impact_engine/graph.json path. Review
    # deliberately never refreshes an externally supplied --graph path; this
    # benchmark must exercise ordinary canonical freshness recovery instead.
    common = ["--no-daemon", "--no-research-requests", "--scope", str(spec.get("scope") or ".")]
    cold, cold_seconds = _run([
        sys.executable, "-m", "impact_engine.cli", "--json", "analyze", str(project), "--use-scan-plan", *common,
    ], cwd=project)
    warm, warm_seconds = _run([
        sys.executable, "-m", "impact_engine.cli", "--json", "analyze", str(project), *common,
    ], cwd=project)
    historical_diff, historical_changed_files = _historical_diff(source, project)
    historical_review, historical_review_seconds = _review(project, historical_diff, str(spec.get("scope") or "."), "never")
    diff = _source_diff(project, dict(spec["mutation"]))
    freshness_review, freshness_review_seconds = _review(project, diff, str(spec.get("scope") or "."), "auto")
    inventory = cold.get("inventory", {}) if isinstance(cold.get("inventory"), dict) else {}
    warm_cache = warm.get("graph", {}).get("metadata", {}).get("cache", {}) if isinstance(warm.get("graph"), dict) else {}
    gate = {
        "pinned_commit": actual_commit == expected_commit if expected_commit else actual_commit is not None,
        "cold_analysis_ok": cold.get("status") == "ok" and int(cold.get("nodes") or 0) > 0,
        "warm_cache_hit": warm_cache.get("status") == "hit",
        "historical_review_ok": str(historical_review.get("schema_version", "")).startswith("ReviewReport/") and not historical_review.get("errors"),
        "freshness_review_ok": str(freshness_review.get("schema_version", "")).startswith("ReviewReport/") and not freshness_review.get("errors"),
        "language_detected": str(spec["language"]) in (cold.get("languages") or []),
    }
    return {
        "id": spec["id"], "repository": spec["repository"], "commit": actual_commit, "language": spec["language"], "scope": spec.get("scope") or ".",
        "validation": {"status": "passed" if all(gate.values()) else "failed", "gates": gate},
        "analysis": {
            "cold_wall_seconds": cold_seconds, "warm_wall_seconds": warm_seconds, "files": inventory.get("files_count", inventory.get("files")),
            "loc": inventory.get("loc"), "nodes": cold.get("nodes"), "edges": cold.get("edges"), "languages": cold.get("languages", []),
        },
        "review": {
            "historical_commit": _review_summary(historical_review, historical_review_seconds, diff_file="HEAD~1..HEAD", changed_files=historical_changed_files),
            "freshness_control": _review_summary(freshness_review, freshness_review_seconds, diff_file=str(spec["mutation"]["file"])),
        },
    }


def run_proof_case(spec: dict[str, Any], projects: dict[str, dict[str, Any]], source_root: Path | None, work_root: Path) -> dict[str, Any]:
    """Prove one real behavioral regression is caught and restored by its test."""
    project_id = str(spec["project"])
    project_spec = projects.get(project_id)
    if project_spec is None:
        raise ValueError(f"proof case {spec['id']} references unknown project {project_id}")
    project, actual_commit, _ = _materialize(project_spec, source_root, work_root / str(spec["id"]))
    expected_commit = str(project_spec.get("commit") or "")
    if expected_commit and actual_commit != expected_commit:
        raise RuntimeError(f"proof case {spec['id']} is at {actual_commit or 'no git metadata'}, expected {expected_commit}")
    command = [str(part) for part in spec["test_command"]]
    expected_test = str(spec["expected_test"])
    baseline = _test_command(command, cwd=project, expected_test=expected_test)
    common = ["--no-daemon", "--no-research-requests", "--scope", str(project_spec.get("scope") or ".")]
    _run([sys.executable, "-m", "impact_engine.cli", "--json", "analyze", str(project), "--use-scan-plan", *common], cwd=project)
    target, diff, original = _behavioral_diff(project, spec)
    try:
        # This is a PR-style experiment: compare a behavior-only diff to the
        # graph of the pinned baseline.  Refreshing after injecting the known
        # regression would make the graph describe the broken implementation,
        # not the revision under review, and can erase the baseline call facts
        # used to select affected code and tests.
        review, review_seconds = _review(project, diff, str(project_spec.get("scope") or "."), "never")
        broken = _test_command(command, cwd=project, expected_test=expected_test)
    finally:
        target.write_text(original, encoding="utf-8")
    restored = _test_command(command, cwd=project, expected_test=expected_test)
    gates = {
        "pinned_commit": actual_commit == expected_commit if expected_commit else actual_commit is not None,
        "baseline_target_test_passed": baseline["exit_code"] == 0,
        "review_ok": str(review.get("schema_version", "")).startswith("ReviewReport/") and not review.get("errors"),
        "broken_behavior_detected": broken["exit_code"] != 0 and broken["mentions_expected_test"],
        "restored_behavior_passed": restored["exit_code"] == 0,
    }
    return {
        "id": spec["id"], "project": project_id, "repository": project_spec["repository"], "commit": actual_commit,
        "language": project_spec["language"],
        "change": {"file": spec["file"], "symbol": spec["symbol"], "before": spec["before"], "after": spec["after"]},
        "codeslicer_review": {
            **_review_summary(review, review_seconds, diff_file=str(spec["file"])),
            "changed_symbols": _changed_symbol_items(review.get("changed", {}).get("symbols") if isinstance(review.get("changed"), dict) else []),
            "semantic_diff": review.get("semantic_diff", {}),
            "top_impact_entities": _evidence_items(review.get("top_impacts")),
            "recommended_tests": _evidence_items(review.get("test_recommendations")),
            "limitations": list(review.get("limitations") or []),
        },
        "observed_test": {"baseline": baseline, "broken_change": broken, "restored": restored},
        "validation": {"status": "passed" if all(gates.values()) else "failed", "gates": gates},
    }


def run_benchmarks(manifest_path: Path, *, source_root: Path | None = None) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    specs = manifest.get("projects", [])
    if not isinstance(specs, list) or not specs:
        raise ValueError("manifest must contain at least one project")
    with tempfile.TemporaryDirectory(prefix="codeslicer-real-project-benchmark-") as raw_work:
        work_root = Path(raw_work)
        results: list[dict[str, Any]] = []
        for spec in specs:
            try:
                results.append(run_case(spec, source_root, work_root))
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                results.append({"id": spec.get("id", "unknown"), "repository": spec.get("repository"), "language": spec.get("language"), "validation": {"status": "failed", "gates": {}}, "error": str(exc)})
        project_index = {str(item["id"]): item for item in specs}
        proof_cases: list[dict[str, Any]] = []
        for spec in manifest.get("proof_cases", []):
            try:
                proof_cases.append(run_proof_case(spec, project_index, source_root, work_root))
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                proof_cases.append({"id": spec.get("id", "unknown"), "project": spec.get("project"), "validation": {"status": "failed", "gates": {}}, "error": str(exc)})
    return {
        "schema_version": "CodeSlicerRealProjectBenchmarkReport/v1",
        "codeslicer_version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "workflow": ["pinned source snapshot", "CLI analyze with scan plan", "warm cache analyze", "CLI review of the real HEAD~1..HEAD diff", "CLI review with automatic freshness refresh over a minimal source-anchored diff", "reversible behavior diff against the pinned baseline graph, target-test fail, restore, target-test pass"],
            "project_dependencies_installed": False,
            "project_tests_executed": bool(manifest.get("proof_cases")),
            "privacy": "only public repository identity, pinned commit and aggregate metrics are emitted",
        },
        "environment": {"platform": platform.platform(), "python": platform.python_version()},
        "results": results,
        "proof_cases": proof_cases,
        "status": "passed" if results and all(item.get("validation", {}).get("status") == "passed" for item in [*results, *proof_cases]) else "failed",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-root", type=Path, help="Directory containing already materialized <project-id> repositories; avoids network access")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run_benchmarks(args.manifest.resolve(), source_root=args.source_root.resolve() if args.source_root else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
