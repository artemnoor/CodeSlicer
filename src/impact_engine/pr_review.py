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
from impact_engine.project_storage import is_codeslicer_artifact_path


RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


@dataclass
class ChangedFile:
    path: str
    lines: set[int] = field(default_factory=set)
    additions: int = 0
    deletions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "lines": sorted(self.lines),
            "additions": self.additions,
            "deletions": self.deletions,
        }


def pr_review_core(
    project_path: str,
    graph_path: str | None = None,
    diff_text: str | None = None,
    max_depth: int = 6,
    min_confidence: float = 0.0,
    max_results: int = 10,
    include_full_evidence: bool = False,
) -> dict[str, Any]:
    """Create a bounded PR report, with full evidence only on explicit opt-in.

    ``impact_query`` intentionally returns the complete transitive closure for
    investigation.  That is useful evidence, but it is not a useful default
    review payload.  Keep the concise PR contract aligned with ``review`` and
    let callers request the expensive/noisy closure explicitly.
    """

    root = Path(project_path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Project path does not exist: {project_path}")

    graph = _load_or_analyze_graph(root, graph_path)
    diff = diff_text if diff_text is not None else _git_diff(root)
    # Import lazily: review imports a few legacy helpers from this module.
    # At call time this module is fully initialized, so this avoids an import
    # cycle while sharing the single, tested projection implementation.
    from impact_engine.review import build_review_report

    concise = build_review_report(
        str(root), graph=graph, diff_text=diff, refresh="never",
        max_results=max(0, min(int(max_results), 10)), run_tests="suggested",
    )
    parsed_changed_files = parse_git_diff(diff)
    generated_changes = [item.path for item in parsed_changed_files if is_codeslicer_artifact_path(item.path)]
    changed_files = [item for item in parsed_changed_files if not is_codeslicer_artifact_path(item.path)]
    changed_symbols = list(concise.get("changed", {}).get("symbols") or _changed_symbols(graph, changed_files))
    visible = list(concise.get("top_impacts") or [])[:10]
    chains = list(concise.get("chains") or [])[:3]
    recommendations = list(concise.get("test_recommendations") or [])[:10]
    required_categories = {"direct_changed_symbol", "symbol_call", "route_controller_integration", "frontend_backend_contract"}
    tests = {
        "required": [item for item in recommendations if item.get("category") in required_categories],
        "recommended": [item for item in recommendations if item.get("category") not in required_categories],
    }
    result: dict[str, Any] = {
        "schema_version": "PRReview/v2",
        "status": "ok",
        "project_path": str(root),
        "changed_files": [item.to_dict() for item in changed_files],
        "changed_symbols": changed_symbols,
        "risk": concise.get("risk", {}),
        "suggested_tests": tests,
        "top_impacts": visible,
        "test_recommendations": recommendations,
        "chains": chains,
        "review_projection": concise.get("review_projection", {}),
        "warnings": list(concise.get("warnings") or []),
        "full_evidence": {
            "status": "not_requested",
            "hint": "Pass include_full_evidence=true (or --full-evidence) for the complete impact closure.",
            "max_depth": max_depth,
            "min_confidence": min_confidence,
        },
        "summary": {
            "changed_files": len(changed_files),
            "changed_symbols": len(changed_symbols),
            "top_impacts": len(visible),
            "test_recommendations": len(recommendations),
            "evidence_chains": len(chains),
            "risk_level": concise.get("risk", {}).get("level", "UNKNOWN"),
        },
    }
    if generated_changes:
        result["warnings"].append(
            f"{len(generated_changes)} generated CodeSlicer artifact changes excluded from PR review"
        )
    if include_full_evidence:
        impact_results = []
        seen_edges: dict[str, dict[str, Any]] = {}
        seen_nodes: dict[str, dict[str, Any]] = {}
        for symbol in changed_symbols:
            impact = impact_query(
                graph, target=symbol["id"], direction="both",
                max_depth=max_depth, min_confidence=min_confidence,
            )
            impact_results.append({"changed_symbol": symbol, "impact": impact})
            for node in impact.get("affected_nodes", []):
                seen_nodes.setdefault(node["id"], node)
            for edge in impact.get("edges", []):
                seen_edges.setdefault(edge["id"], edge)
        result["full_evidence"] = {
            "status": "included_on_explicit_request",
            "affected_nodes": len(seen_nodes),
            "affected_edges": len(seen_edges),
            "impact_sections": _output_sections(list(seen_edges.values())),
            "impact_results": impact_results,
            "max_depth": max_depth,
            "min_confidence": min_confidence,
        }
    return result


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
            current.additions += 1
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            current.deletions += 1
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
    declarations: dict[str, list[tuple[Any, ChangedFile]]] = {}
    for node in graph.nodes:
        file_name = str(node.properties.get("file") or node.properties.get("path") or "")
        if not file_name:
            continue
        matched = next((cf for path, cf in changed_by_path.items() if _path_matches(file_name, path)), None)
        if matched is None:
            continue
        line = node.properties.get("line")
        is_csharp = str(node.properties.get("language") or "").lower() == "csharp" or file_name.lower().endswith(".cs")
        allowed_kinds = {"METHOD", "FUNCTION", "CLASS", "FILE", "MODULE"}
        if not is_csharp:
            allowed_kinds.add("ROUTE")
        if node.kind not in allowed_kinds:
            continue
        declarations.setdefault(file_name, []).append((node, matched))

    # Resolve each changed hunk to the most specific declaration that contains
    # it.  The previous broad +/-80-line window promoted neighbouring methods
    # such as __init__ into independent anchors, crowding the actual changed
    # method and its causal downstream calls out of concise Review.
    specificity = {"METHOD": 0, "FUNCTION": 0, "ROUTE": 1, "CLASS": 2, "MODULE": 3, "FILE": 4}
    for file_name, items in declarations.items():
        matched = items[0][1]
        line_items = [(node, line) for node, _ in items if isinstance((line := node.properties.get("line")), int)]
        line_items.sort(key=lambda item: (item[1], specificity.get(item[0].kind, 9), item[0].id))
        if not matched.lines or not line_items:
            continue
        for changed_line in sorted(matched.lines):
            preceding = [item for item in line_items if item[1] <= changed_line]
            if not preceding:
                exact = [item for item in line_items if item[1] == changed_line]
                preceding = exact
            if not preceding:
                continue
            nearest_line = max(item[1] for item in preceding)
            nearest = [item for item in preceding if item[1] == nearest_line]
            node = min(nearest, key=lambda item: (specificity.get(item[0].kind, 9), item[0].id))[0]
            if node.id in seen:
                continue
            seen.add(node.id)
            symbols.append({
                "id": node.id, "kind": node.kind, "file": file_name,
                "line": node.properties.get("line"), "changed_lines": sorted(matched.lines),
            })

    if not symbols:
        for item in changed_files:
            symbols.append({"id": item.path, "kind": "FILE", "file": item.path, "line": None, "changed_lines": sorted(item.lines)})
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
