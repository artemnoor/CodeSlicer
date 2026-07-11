"""Real-project QA matrix runner."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.support_packs.detection import detect_unknown_libraries_core


def run_qa_matrix(projects_root: str | Path, out_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(projects_root).resolve()
    if not root.exists():
        raise FileNotFoundError(f"QA projects root does not exist: {projects_root}")

    output_root = Path(out_dir or ".impact_engine/qa_runs").resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    candidates = _candidate_projects(root)
    runs = [_run_project(project, output_root) for project in candidates]
    summary = _summarize_runs(runs)
    status = "ok" if summary["failed"] == 0 and summary["errors"] == 0 else "failed"
    if summary["known_gaps"] and status == "ok":
        status = "known_gaps"
    return {
        "status": status,
        "projects_root": str(root),
        "out_dir": str(output_root),
        "summary": summary,
        "runs": runs,
    }


def _candidate_projects(root: Path) -> list[Path]:
    if _is_project(root):
        return [root]
    return [path for path in sorted(root.iterdir()) if path.is_dir() and _is_project(path)]


def _is_project(path: Path) -> bool:
    if (path / "qa_matrix.json").exists():
        return True
    if any((path / name).exists() for name in ("pyproject.toml", "package.json", "go.mod", "README.md")):
        return True
    return any(any(path.glob(pattern)) for pattern in ("*.py", "*.js", "*.ts", "*.java", "*.go"))


def _load_manifest(project: Path) -> dict[str, Any]:
    manifest_path = project / "qa_matrix.json"
    if not manifest_path.exists():
        return {"name": project.name, "checks": {}}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _run_project(project: Path, output_root: Path) -> dict[str, Any]:
    manifest = _load_manifest(project)
    graph_path = output_root / f"{project.name}_graph.json"
    try:
        result = analyze_project_core(str(project), out_path=str(graph_path))
        graph = result["graph"]
        unknown = detect_unknown_libraries_core(str(project))
        checks = _evaluate_checks(graph, unknown, manifest)
        status = _status_for_checks(checks)
        return {
            "project": str(project),
            "name": manifest.get("name", project.name),
            "status": status,
            "graph_path": str(graph_path),
            "nodes": result["nodes"],
            "edges": result["edges"],
            "languages": result.get("languages", []),
            "extractors_used": result.get("extractors_used", []),
            "unknown_libraries": unknown,
            "checks": checks,
        }
    except Exception as exc:
        return {
            "project": str(project),
            "name": manifest.get("name", project.name),
            "status": "error",
            "error": str(exc),
            "checks": [],
        }


def _evaluate_checks(graph: dict[str, Any], unknown_libraries: list[str], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    checks_config = manifest.get("checks", {}) or {}
    edges = graph.get("edges", []) or []
    nodes = graph.get("nodes", []) or []
    edge_index = {(edge.get("from"), edge.get("to"), edge.get("kind")): edge for edge in edges}
    edge_text = "\n".join(f"{edge.get('kind')} {edge.get('from')} -> {edge.get('to')}" for edge in edges)
    node_ids = [str(node.get("id", "")) for node in nodes]
    checks: list[dict[str, Any]] = []

    for item in checks_config.get("required_edges", []) or []:
        key = (item.get("from"), item.get("to"), item.get("kind"))
        checks.append(_edge_check("required_edge", item, key in edge_index, edge_index.get(key)))

    for item in checks_config.get("known_gap_edges", []) or []:
        key = (item.get("from"), item.get("to"), item.get("kind"))
        found = key in edge_index
        check = _edge_check("known_gap_edge", item, found, edge_index.get(key))
        check["status"] = "pass" if found else "known_gap"
        checks.append(check)

    for item in checks_config.get("required_node_contains", []) or []:
        needle = str(item.get("contains", item if isinstance(item, str) else ""))
        found = [node_id for node_id in node_ids if needle in node_id]
        checks.append({
            "type": "required_node_contains",
            "status": "pass" if found else "fail",
            "contains": needle,
            "matches": found[:10],
            "description": item.get("description") if isinstance(item, dict) else "",
        })

    for item in checks_config.get("known_gap_node_contains", []) or []:
        needle = str(item.get("contains", item if isinstance(item, str) else ""))
        found = [node_id for node_id in node_ids if needle in node_id]
        checks.append({
            "type": "known_gap_node_contains",
            "status": "pass" if found else "known_gap",
            "contains": needle,
            "matches": found[:10],
            "description": item.get("description") if isinstance(item, dict) else "",
        })

    for item in checks_config.get("forbidden_edge_substrings", []) or []:
        needle = str(item.get("contains", item if isinstance(item, str) else ""))
        found = needle in edge_text
        checks.append({
            "type": "forbidden_edge_substring",
            "status": "fail" if found else "pass",
            "contains": needle,
            "description": item.get("description") if isinstance(item, dict) else "",
        })

    for item in checks_config.get("known_gap_forbidden_edge_substrings", []) or []:
        needle = str(item.get("contains", item if isinstance(item, str) else ""))
        found = needle in edge_text
        checks.append({
            "type": "known_gap_forbidden_edge_substring",
            "status": "known_gap" if found else "pass",
            "contains": needle,
            "description": item.get("description") if isinstance(item, dict) else "",
        })

    expected_unknown = set(checks_config.get("expected_unknown_libraries", []) or [])
    if expected_unknown:
        actual = set(unknown_libraries)
        missing = sorted(expected_unknown - actual)
        checks.append({
            "type": "expected_unknown_libraries",
            "status": "pass" if not missing else "fail",
            "expected": sorted(expected_unknown),
            "actual": sorted(actual),
            "missing": missing,
        })

    forbidden_unknown = set(checks_config.get("forbidden_unknown_libraries", []) or [])
    if forbidden_unknown:
        actual = set(unknown_libraries)
        present = sorted(forbidden_unknown & actual)
        checks.append({
            "type": "forbidden_unknown_libraries",
            "status": "pass" if not present else "fail",
            "forbidden": sorted(forbidden_unknown),
            "actual": sorted(actual),
            "present": present,
        })

    return checks


def _edge_check(kind: str, item: dict[str, Any], found: bool, edge: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "type": kind,
        "status": "pass" if found else "fail",
        "from": item.get("from"),
        "to": item.get("to"),
        "kind": item.get("kind"),
        "description": item.get("description", ""),
        "edge": edge,
    }


def _status_for_checks(checks: list[dict[str, Any]]) -> str:
    statuses = {check.get("status") for check in checks}
    if "fail" in statuses:
        return "failed"
    if "known_gap" in statuses:
        return "known_gaps"
    return "ok"


def _summarize_runs(runs: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"projects": len(runs), "passed": 0, "failed": 0, "known_gaps": 0, "errors": 0, "checks": 0}
    for run in runs:
        status = run.get("status")
        if status == "ok":
            summary["passed"] += 1
        elif status == "known_gaps":
            summary["known_gaps"] += 1
        elif status == "error":
            summary["errors"] += 1
        else:
            summary["failed"] += 1
        summary["checks"] += len(run.get("checks", []) or [])
    return summary
