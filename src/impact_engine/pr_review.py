"""PR impact review layer built on top of the impact graph."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.impact import impact_query
from impact_engine.models import GraphDocument


RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


@dataclass
class ChangedFile:
    path: str
    lines: set[int] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "lines": sorted(self.lines)}


def pr_review_core(
    project_path: str,
    graph_path: str | None = None,
    diff_text: str | None = None,
    max_depth: int = 6,
    min_confidence: float = 0.0,
) -> dict[str, Any]:
    """Create a structured PR impact report from git diff and impact graph."""

    root = Path(project_path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Project path does not exist: {project_path}")

    graph = _load_or_analyze_graph(root, graph_path)
    diff = diff_text if diff_text is not None else _git_diff(root)
    changed_files = parse_git_diff(diff)
    changed_symbols = _changed_symbols(graph, changed_files)

    impact_results = []
    seen_edges: dict[str, dict[str, Any]] = {}
    seen_nodes: dict[str, dict[str, Any]] = {}
    for symbol in changed_symbols:
        result = impact_query(
            graph,
            target=symbol["id"],
            direction="both",
            max_depth=max_depth,
            min_confidence=min_confidence,
        )
        impact_results.append({"changed_symbol": symbol, "impact": result})
        for node in result.get("affected_nodes", []):
            seen_nodes.setdefault(node["id"], node)
        for edge in result.get("edges", []):
            seen_edges.setdefault(edge["id"], edge)

    changed_file_paths = {item.path for item in changed_files}
    risk = score_pr_risk(changed_symbols, list(seen_nodes.values()), list(seen_edges.values()), changed_file_paths)
    tests = recommend_tests(graph, list(seen_nodes.values()), list(seen_edges.values()), changed_file_paths)
    sections = _output_sections(list(seen_edges.values()))

    return {
        "status": "ok",
        "project_path": str(root),
        "changed_files": [item.to_dict() for item in changed_files],
        "changed_symbols": changed_symbols,
        "risk": risk,
        "suggested_tests": tests,
        "impact_sections": sections,
        "impact_results": impact_results,
        "summary": {
            "changed_files": len(changed_files),
            "changed_symbols": len(changed_symbols),
            "affected_nodes": len(seen_nodes),
            "affected_edges": len(seen_edges),
            "risk_level": risk["level"],
        },
    }


def parse_git_diff(diff_text: str) -> list[ChangedFile]:
    """Parse a unified git diff into changed files and added/modified line numbers."""

    files: list[ChangedFile] = []
    current: ChangedFile | None = None
    new_line: int | None = None
    for raw in diff_text.splitlines():
        line = raw.rstrip("\n")
        if line.startswith("diff --git "):
            current = None
            new_line = None
            continue
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path == "/dev/null":
                current = None
                continue
            if path.startswith("b/"):
                path = path[2:]
            current = ChangedFile(path=path.replace("\\", "/"))
            files.append(current)
            continue
        if line.startswith("@@"):
            new_line = _parse_hunk_new_start(line)
            continue
        if current is None or new_line is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            current.lines.add(new_line)
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        else:
            new_line += 1
    return files


def score_pr_risk(
    changed_symbols: list[dict[str, Any]],
    affected_nodes: list[dict[str, Any]],
    affected_edges: list[dict[str, Any]],
    changed_files: set[str],
) -> dict[str, Any]:
    score = 0
    reasons: list[str] = []

    all_ids = " ".join([s.get("id", "") for s in changed_symbols] + [n.get("id", "") for n in affected_nodes]).lower()
    all_files = " ".join(changed_files).lower()

    if any(token in all_ids for token in ["repository", "repo", "save", "delete", "commit", "payment", "billing"]):
        score += 3
        reasons.append("persistence/payment/billing symbol involved")
    if any(node.get("kind") == "ROUTE" or str(node.get("id", "")).startswith("HTTP ") for node in affected_nodes):
        score += 3
        reasons.append("public route affected")
    if any("frontend" in str(node.get("properties", {}).get("file", "")).lower() or str(node.get("id", "")).startswith("HTTP ") for node in affected_nodes):
        score += 1
        reasons.append("frontend or HTTP client flow affected")
    if any("test" in str(node.get("id", "")).lower() or "tests/" in str(node.get("properties", {}).get("file", "")).lower() for node in affected_nodes):
        score += 1
        reasons.append("tests are connected to impacted graph")
    if any(edge.get("quality", {}).get("status") in {"weak", "suspicious"} for edge in affected_edges):
        score += 1
        reasons.append("low-confidence or suspicious edges present")
    if any(part in all_files for part in ["docs/", "readme", ".md"]):
        score -= 2
        reasons.append("documentation-only changes reduce risk")
    if any(part in all_files for part in ["generated", "dist/", "build/"]):
        score -= 1
        reasons.append("generated/build artifact changes reduce review priority")

    if score >= 7:
        level = "CRITICAL"
    elif score >= 5:
        level = "HIGH"
    elif score >= 2:
        level = "MEDIUM"
    else:
        level = "LOW"
    return {"level": level, "score": max(0, score), "reasons": reasons}


def recommend_tests(
    graph: GraphDocument,
    affected_nodes: list[dict[str, Any]],
    affected_edges: list[dict[str, Any]],
    changed_files: set[str],
) -> dict[str, list[dict[str, Any]]]:
    required: dict[str, dict[str, Any]] = {}
    recommended: dict[str, dict[str, Any]] = {}
    affected_ids = {node["id"] for node in affected_nodes}

    for edge in graph.edges:
        if edge.kind != "TESTS":
            continue
        if edge.to_node in affected_ids or edge.from_node in affected_ids:
            test_file = _test_file_for_node(graph, edge.from_node)
            item = {
                "node": edge.from_node,
                "file": test_file,
                "reason": f"TESTS edge targets {edge.to_node}",
            }
            required[f"{edge.from_node}:{test_file}"] = item

    for node in graph.nodes:
        file_name = str(node.properties.get("file") or node.properties.get("path") or "")
        if not file_name:
            continue
        lower = file_name.lower()
        if "test" not in lower:
            continue
        if any(_same_area(file_name, changed) for changed in changed_files):
            recommended[file_name] = {
                "node": node.id,
                "file": file_name,
                "reason": "test file is near a changed file",
            }

    for edge in affected_edges:
        if edge.get("kind") == "TESTS":
            test_file = _test_file_for_node(graph, edge.get("from", ""))
            required[f"{edge.get('from')}:{test_file}"] = {
                "node": edge.get("from"),
                "file": test_file,
                "reason": f"impact traversal includes TESTS edge to {edge.get('to')}",
            }

    return {"required": list(required.values()), "recommended": list(recommended.values())}


def _load_or_analyze_graph(root: Path, graph_path: str | None) -> GraphDocument:
    if graph_path:
        return GraphDocument.from_json(Path(graph_path).read_text(encoding="utf-8"))
    result = analyze_project_core(str(root))
    return GraphDocument.from_dict(result["graph"])


def _git_diff(root: Path) -> str:
    try:
        result = subprocess.run(["git", "diff", "--unified=0"], cwd=root, capture_output=True, text=True, timeout=20)
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return ""


def _changed_symbols(graph: GraphDocument, changed_files: list[ChangedFile]) -> list[dict[str, Any]]:
    changed_by_path = {item.path: item for item in changed_files}
    symbols: list[dict[str, Any]] = []
    seen = set()
    for node in graph.nodes:
        file_name = str(node.properties.get("file") or node.properties.get("path") or "")
        if not file_name:
            continue
        matched = next((cf for path, cf in changed_by_path.items() if _path_matches(file_name, path)), None)
        if matched is None:
            continue
        line = node.properties.get("line")
        if matched.lines and isinstance(line, int) and node.kind in {"METHOD", "FUNCTION", "CLASS"}:
            # Keep symbols at or before the changed line in the same file. This
            # is a conservative hunk mapping without requiring full AST ranges.
            if all(abs(line - changed_line) > 80 and line > changed_line for changed_line in matched.lines):
                continue
        if node.kind not in {"METHOD", "FUNCTION", "CLASS", "ROUTE", "FILE", "MODULE"}:
            continue
        if node.id in seen:
            continue
        seen.add(node.id)
        symbols.append({"id": node.id, "kind": node.kind, "file": file_name, "line": line})

    if not symbols:
        for item in changed_files:
            symbols.append({"id": item.path, "kind": "FILE", "file": item.path, "line": None})
    return symbols


def _output_sections(edge_dicts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    sections = {name: [] for name in ["confirmed", "likely", "weak", "suspicious", "rejected", "not_resolved"]}
    for edge in edge_dicts:
        status = edge.get("quality", {}).get("status") or edge.get("properties", {}).get("status") or "weak"
        if status not in sections:
            status = "suspicious"
        sections[status].append(edge)
    return sections


def _parse_hunk_new_start(line: str) -> int | None:
    # @@ -a,b +c,d @@
    marker = line.split(" +", 1)
    if len(marker) < 2:
        return None
    text = marker[1].split(" ", 1)[0].split(",", 1)[0]
    try:
        return int(text)
    except ValueError:
        return None


def _path_matches(node_file: str, changed_file: str) -> bool:
    node_norm = node_file.replace("\\", "/").lstrip("./")
    changed_norm = changed_file.replace("\\", "/").lstrip("./")
    return node_norm == changed_norm or node_norm.endswith("/" + changed_norm) or changed_norm.endswith("/" + node_norm)


def _same_area(test_file: str, changed_file: str) -> bool:
    test_parts = test_file.replace("\\", "/").split("/")
    changed_parts = changed_file.replace("\\", "/").split("/")
    if not test_parts or not changed_parts:
        return False
    return bool(set(test_parts[:-1]) & set(changed_parts[:-1])) or test_parts[-1].replace("test_", "").replace(".test", "") in changed_parts[-1]


def _test_file_for_node(graph: GraphDocument, node_id: str) -> str | None:
    node = next((item for item in graph.nodes if item.id == node_id), None)
    if node is None:
        return None
    return node.properties.get("file") or node.properties.get("path")
