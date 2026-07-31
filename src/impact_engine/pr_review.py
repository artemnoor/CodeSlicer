"""PR impact review layer built on top of the impact graph."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.impact import edge_to_dict, impact_query
from impact_engine.models import GraphDocument


RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

# A review is a decision aid, not a graph dump.  These kinds are deliberately
# language-neutral: every extractor can map a low-level expression to one of
# these owners through CONTAINS/DECLARES edges, without relying on a Python- or
# JavaScript-specific name heuristic.
_ACTIONABLE_NODE_KINDS = {
    "METHOD", "FUNCTION", "CLASS", "ROUTE", "ENDPOINT", "HANDLER",
    "CONTROLLER", "SERVICE", "COMPONENT", "MODULE", "FILE", "TEST",
}
_STRUCTURAL_EDGE_KINDS = {"CONTAINS", "DECLARES", "ASSIGNS", "ASSIGNED_TO"}
# These graph facts describe object shape or construction.  They are useful
# internally for resolution, but are not evidence that changing one endpoint
# changes the behaviour of the other endpoint in a review.
_NON_BEHAVIOURAL_EDGE_KINDS = {
    "IMPORTS", "EXPORTS", "FIELD_BINDS_TO", "INSTANCE_OF", "INHERITS",
    "IMPLEMENTS", "TYPE_OF", "ANNOTATES", "ALIAS_OF",
}
_DEFAULT_REVIEW_STATUSES = {"confirmed", "likely"}
_MAX_REVIEW_IMPACTS = 25


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
    include_technical: bool = False,
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
            # Reverse dependencies are the default review question: what can
            # observe this change?  The raw graph remains available for an
            # explicit deep investigation, while avoiding sibling declarations
            # reached through a module containment edge.
            direction="upstream",
            max_depth=max_depth,
            min_confidence=min_confidence,
        )
        impact_results.append({"changed_symbol": symbol, "impact": result})
        for node in result.get("affected_nodes", []):
            seen_nodes.setdefault(node["id"], node)
        for edge in result.get("edges", []):
            seen_edges.setdefault(edge["id"], edge)

    changed_file_paths = {item.path for item in changed_files}
    raw_nodes = list(seen_nodes.values())
    raw_edges = list(seen_edges.values())
    test_evidence_edges = _discover_test_evidence(
        graph,
        changed_symbols,
        raw_edges,
        max_depth=max_depth,
        min_confidence=min_confidence,
    )
    projection = _review_projection(graph, changed_symbols, changed_file_paths, raw_nodes, raw_edges)
    review_nodes = projection["impacted_symbols"]
    review_edges = projection["relationships"]
    risk = score_pr_risk(
        changed_symbols,
        review_nodes,
        review_edges,
        changed_file_paths,
        unresolved_changed_symbols=projection["coverage"]["unresolved_changed_symbols"],
    )
    # TESTS edges are a separate evidence channel.  They can terminate at a
    # low-level expression which the human review projection correctly hides,
    # so discover tests from the raw bounded traversal rather than losing a
    # directly linked regression test during presentation filtering.
    tests = recommend_tests(
        graph,
        raw_nodes,
        [*raw_edges, *test_evidence_edges],
        changed_file_paths,
        changed_node_ids={item["id"] for item in changed_symbols},
    )
    # Keep the old full buckets under an explicit technical name.  The primary
    # sections now obey the review contract and never present containment or
    # weak/speculative edges as user-facing impact.
    technical_sections = _output_sections(raw_edges)
    sections = _output_sections(review_edges)

    report = {
        "status": "ok",
        "project_path": str(root),
        "changed_files": [item.to_dict() for item in changed_files],
        "changed_symbols": changed_symbols,
        "risk": risk,
        "suggested_tests": tests,
        "review_projection": projection,
        "impact_sections": sections,
        "technical": {
            "available_on_request": True,
            "affected_nodes": len(raw_nodes),
            "affected_edges": len(raw_edges),
            "impact_section_counts": {name: len(items) for name, items in technical_sections.items()},
        },
        "summary": {
            "changed_files": len(changed_files),
            "changed_symbols": len(changed_symbols),
            "affected_nodes": len(review_nodes),
            "affected_edges": len(review_edges),
            "technical_affected_nodes": len(raw_nodes),
            "technical_affected_edges": len(raw_edges),
            "risk_level": risk["level"],
        },
    }
    if include_technical:
        report["technical_impact_sections"] = technical_sections
        report["impact_results"] = impact_results
    return report


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
    unresolved_changed_symbols: list[dict[str, Any]] | None = None,
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
    if unresolved_changed_symbols:
        # No graph successor is never proof that a changed public/dynamic
        # symbol is isolated.  Surface this as a bounded coverage limitation
        # instead of silently returning a reassuring LOW risk.
        score += 2
        reasons.append("no resolved behavioural dependency for one or more changed symbols")
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
    changed_node_ids: set[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    required: dict[str, dict[str, Any]] = {}
    recommended: dict[str, dict[str, Any]] = {}
    affected_ids = {node["id"] for node in affected_nodes}
    # The traversal result intentionally excludes its start node.  A direct
    # TESTS edge can therefore target the changed symbol itself and must remain
    # eligible for selection.
    affected_ids.update(changed_node_ids or set())

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
        if not _is_test_file(file_name):
            continue
        # Physical proximity is only a tie-breaker for a name-based pairing.
        # A package can contain many unrelated controller tests, so directory
        # proximity alone is not review-grade evidence.
        if any(_test_target_stem(Path(file_name).name) == _test_target_stem(Path(changed).name) for changed in changed_files):
            recommended[file_name] = {
                "node": node.id,
                "file": file_name,
                "reason": "test file is near a changed file",
            }

    # A test callable reached by the bounded, active impact traversal is
    # stronger evidence than filename proximity.  It is still ``recommended``
    # rather than ``required``: only an explicit TESTS edge asserts a declared
    # test contract, while a resolved call path says the test exercises the
    # changed implementation in this static configuration.
    for node in affected_nodes:
        if str(node.get("kind") or "") not in {"METHOD", "FUNCTION", "TEST"}:
            continue
        properties = node.get("properties") or {}
        file_name = str(properties.get("file") or properties.get("path") or "")
        if not _is_test_file(file_name):
            continue
        existing = recommended.get(file_name)
        if existing is None or existing.get("reason") == "test file is near a changed file":
            recommended[file_name] = {
                "node": node.get("id"),
                "file": file_name,
                "reason": "resolved call-graph path reaches the changed symbol",
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
    from impact_engine.analysis_lock import analysis_lock

    with analysis_lock(root, owner="pr-review"):
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
    symbols: list[dict[str, Any]] = []
    seen: set[str] = set()
    symbol_kinds = {"METHOD", "FUNCTION", "CLASS", "ROUTE"}
    for changed in changed_files:
        candidates = [
            node for node in graph.nodes
            if node.kind in symbol_kinds
            and _path_matches(str(node.properties.get("file") or node.properties.get("path") or ""), changed.path)
        ]
        selected = _symbols_for_changed_lines(candidates, changed.lines)
        # File-level fallback is deliberately used only when source ranges do
        # not identify a symbol.  This prevents an old graph from attributing a
        # hunk in one function to every earlier function in the same file.
        if not selected:
            selected = [
                node for node in graph.nodes
                if node.kind in {"FILE", "MODULE"}
                and _path_matches(str(node.properties.get("file") or node.properties.get("path") or ""), changed.path)
            ]
        for node in selected:
            if node.id in seen:
                continue
            seen.add(node.id)
            file_name = str(node.properties.get("file") or node.properties.get("path") or changed.path)
            symbols.append({"id": node.id, "kind": node.kind, "file": file_name, "line": node.properties.get("line")})

    if not symbols:
        for item in changed_files:
            symbols.append({"id": item.path, "kind": "FILE", "file": item.path, "line": None})
    return symbols


def _symbols_for_changed_lines(nodes: list[Any], changed_lines: set[int]) -> list[Any]:
    if not nodes:
        return []
    if not changed_lines:
        return nodes
    selected: dict[str, Any] = {}
    for changed_line in changed_lines:
        containing = [
            node for node in nodes
            if isinstance(node.properties.get("line"), int)
            and isinstance(node.properties.get("end_line"), int)
            and node.properties["line"] <= changed_line <= node.properties["end_line"]
        ]
        if containing:
            # A nested method is more precise than its enclosing class.
            best = min(containing, key=lambda node: node.properties["end_line"] - node.properties["line"])
            selected[best.id] = best
            continue
        prior = [node for node in nodes if isinstance(node.properties.get("line"), int) and node.properties["line"] <= changed_line]
        if prior:
            best = max(prior, key=lambda node: node.properties["line"])
            selected[best.id] = best
    return list(selected.values())


def _output_sections(edge_dicts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    sections = {name: [] for name in ["confirmed", "likely", "weak", "suspicious", "rejected", "not_resolved"]}
    for edge in edge_dicts:
        status = edge.get("quality", {}).get("status") or edge.get("properties", {}).get("status") or "weak"
        if status not in sections:
            status = "suspicious"
        sections[status].append(edge)
    return sections


def _discover_test_evidence(
    graph: GraphDocument,
    changed_symbols: list[dict[str, Any]],
    existing_edges: list[dict[str, Any]],
    *,
    max_depth: int,
    min_confidence: float,
) -> list[dict[str, Any]]:
    """Find directly connected tests without widening the review projection.

    The normal upstream review deliberately avoids walking through a changed
    implementation's local containment graph.  TESTS edges can sit behind that
    graph (test -> route -> service -> changed method), so run a bounded,
    internal-only discovery traversal when necessary and retain *only* TESTS
    evidence.  This preserves precise regression-test recommendations without
    reintroducing structural noise into the visible impact list.
    """

    selected: dict[str, dict[str, Any]] = {
        edge["id"]: edge for edge in existing_edges if edge.get("kind") == "TESTS" and edge.get("id")
    }
    if selected:
        return list(selected.values())
    # This deliberately is not ``impact_query(..., direction="both")``.
    # That query retains every path and ranking explanation, which is valuable
    # for an explicit investigation but needlessly expensive when all we need
    # is the presence of a TESTS edge.  A visited-node BFS is O(V + E) within
    # the caller's depth budget and remains bounded on large mixed-language
    # repositories.
    adjacent: dict[str, list[Any]] = {}
    for edge in graph.edges:
        if float(getattr(edge, "confidence", 0.0) or 0.0) < min_confidence:
            continue
        adjacent.setdefault(edge.from_node, []).append(edge)
        adjacent.setdefault(edge.to_node, []).append(edge)

    visited = {item["id"] for item in changed_symbols}
    frontier = list(visited)
    for _depth in range(max(0, max_depth)):
        if not frontier:
            break
        next_frontier: list[str] = []
        for node_id in frontier:
            for edge in adjacent.get(node_id, []):
                other = edge.to_node if edge.from_node == node_id else edge.from_node
                if edge.kind == "TESTS":
                    serialized = edge_to_dict(edge)
                    selected.setdefault(serialized["id"], serialized)
                if other not in visited:
                    visited.add(other)
                    next_frontier.append(other)
        frontier = next_frontier
    return list(selected.values())


def _review_projection(
    graph: GraphDocument,
    changed_symbols: list[dict[str, Any]],
    changed_files: set[str],
    affected_nodes: list[dict[str, Any]],
    affected_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Project raw traversal data into a bounded, actionable review surface.

    Extractors naturally produce dense expression/assignment graphs.  Showing
    those nodes in a PR report is misleading: a proven containment edge says
    that an expression belongs to a function, not that another subsystem is at
    risk.  This projection resolves expression endpoints to their nearest
    semantic owner, keeps confirmed/likely behavioural relationships, and
    records everything omitted as an explicit coverage limitation.
    """

    node_by_id = {node.id: node for node in graph.nodes}
    parent_ids: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.kind in {"CONTAINS", "DECLARES"}:
            parent_ids.setdefault(edge.to_node, []).append(edge.from_node)

    changed_ids = {item["id"] for item in changed_symbols}
    owner_cache: dict[str, str | None] = {}

    def owner_id(node_id: str) -> str | None:
        if node_id in owner_cache:
            return owner_cache[node_id]
        # Mark before walking parents so malformed cyclic containment cannot
        # recurse forever.
        owner_cache[node_id] = None
        node = node_by_id.get(node_id)
        if node is not None and node.kind in _ACTIONABLE_NODE_KINDS and _node_file(node):
            owner_cache[node_id] = node_id
            return node_id
        parents = parent_ids.get(node_id, [])
        # Prefer callable/route owners over a module or file when an extractor
        # gives both possible ancestors.
        ranked = sorted(
            parents,
            key=lambda parent: _owner_priority(node_by_id.get(parent)),
        )
        for parent in ranked:
            resolved = owner_id(parent)
            if resolved is not None:
                owner_cache[node_id] = resolved
                return resolved
        return None

    raw_quality_counts = {name: 0 for name in ["confirmed", "likely", "weak", "suspicious", "rejected", "not_resolved"]}
    structural_count = 0
    suppressed_count = 0
    relationships: dict[tuple[str, str, str], dict[str, Any]] = {}
    for edge in affected_edges:
        status = _edge_status(edge)
        raw_quality_counts[status] = raw_quality_counts.get(status, 0) + 1
        if edge.get("kind") in _STRUCTURAL_EDGE_KINDS | _NON_BEHAVIOURAL_EDGE_KINDS:
            structural_count += 1
            continue
        if status not in _DEFAULT_REVIEW_STATUSES:
            suppressed_count += 1
            continue
        source = owner_id(str(edge.get("from", "")))
        target = owner_id(str(edge.get("to", "")))
        if source is None or target is None or source == target:
            continue
        source_node = node_by_id.get(source)
        target_node = node_by_id.get(target)
        if source_node is None or target_node is None:
            continue
        key = (source, str(edge.get("kind", "")), target)
        candidate = {
            "from": _review_node(source_node),
            "to": _review_node(target_node),
            "kind": edge.get("kind"),
            "quality": edge.get("quality", {"status": status}),
            "evidence": edge.get("evidence", []),
        }
        relationships.setdefault(key, candidate)

    # A traversed node alone is not review evidence.  It becomes actionable
    # only when it participates in a visible, behavioural relationship.  This
    # prevents broad raw closures (for example constructor/type bookkeeping)
    # from becoming a list of alleged impacts.
    impacted: dict[str, dict[str, Any]] = {}
    changed_file_paths = {_normalise_review_path(path) for path in changed_files}
    changed_file_nodes_hidden = 0
    for relation in relationships.values():
        for endpoint in (relation["from"], relation["to"]):
            if endpoint["id"] in changed_ids:
                continue
            # A sibling method in the changed file is still actionable (for
            # example ``main`` calling a changed ``run``).  Only hide file or
            # module containers from that file; they merely restate the diff.
            if endpoint.get("kind") in {"FILE", "MODULE"} and _normalise_review_path(endpoint.get("file", "")) in changed_file_paths:
                changed_file_nodes_hidden += 1
                continue
            impacted.setdefault(endpoint["id"], endpoint)

    # If the diff resolves to a callable, FILE/MODULE nodes are merely a
    # containment artefact, even when the affected source happens to be in a
    # different file.  Keep them only for file-level diffs where no narrower
    # changed symbol could be established.
    changed_has_callable = any(item.get("kind") not in {"FILE", "MODULE"} for item in changed_symbols)
    callable_files = {
        item["file"] for item in impacted.values()
        if item["kind"] not in {"FILE", "MODULE"} and item.get("file")
    }
    container_nodes_hidden = 0
    for node_id, item in list(impacted.items()):
        if item["kind"] in {"FILE", "MODULE"} and (changed_has_callable or item.get("file") in callable_files):
            del impacted[node_id]
            container_nodes_hidden += 1

    ordered_impacts = sorted(impacted.values(), key=_review_node_sort_key)
    truncated = max(0, len(ordered_impacts) - _MAX_REVIEW_IMPACTS)
    ordered_impacts = ordered_impacts[:_MAX_REVIEW_IMPACTS]
    selected_ids = {item["id"] for item in ordered_impacts} | changed_ids
    ordered_relationships = [
        relation for relation in relationships.values()
        if relation["from"]["id"] in selected_ids and relation["to"]["id"] in selected_ids
    ]
    ordered_relationships.sort(key=lambda item: (item["kind"], item["from"]["file"], item["to"]["file"], item["from"]["id"]))

    files = sorted({item["file"] for item in ordered_impacts if item.get("file")})
    related_changed_ids = {
        endpoint["id"]
        for relation in ordered_relationships
        for endpoint in (relation["from"], relation["to"])
        if endpoint["id"] in changed_ids
    }
    unresolved_changed_symbols = [
        item for item in changed_symbols if item["id"] not in related_changed_ids
    ]
    return {
        "impacted_symbols": ordered_impacts,
        "affected_files": files,
        "relationships": ordered_relationships,
        "coverage": {
            "raw_nodes": len(affected_nodes),
            "raw_edges": len(affected_edges),
            "structural_edges_hidden": structural_count,
            "low_confidence_edges_hidden": suppressed_count,
            "changed_file_nodes_hidden": changed_file_nodes_hidden,
            "container_nodes_hidden": container_nodes_hidden,
            "unresolved_changed_symbols": unresolved_changed_symbols,
            "quality_counts": raw_quality_counts,
            "truncated_impacts": truncated,
            "default_includes": sorted(_DEFAULT_REVIEW_STATUSES),
        },
    }


def _edge_status(edge: dict[str, Any]) -> str:
    status = edge.get("quality", {}).get("status") or edge.get("properties", {}).get("status") or "weak"
    return str(status) if status in {"confirmed", "likely", "weak", "suspicious", "rejected", "not_resolved"} else "suspicious"


def _node_file(node: Any) -> str:
    properties = getattr(node, "properties", {}) or {}
    file_name = str(properties.get("file") or properties.get("path") or "")
    if file_name:
        return file_name.replace("\\", "/")
    node_id = str(getattr(node, "id", ""))
    return node_id[5:] if node_id.startswith("file:") else ""


def _normalise_review_path(path: str) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def _owner_priority(node: Any) -> tuple[int, str]:
    kind = str(getattr(node, "kind", ""))
    if kind in {"METHOD", "FUNCTION", "HANDLER", "ROUTE", "ENDPOINT", "CONTROLLER", "SERVICE", "COMPONENT"}:
        return (0, str(getattr(node, "id", "")))
    if kind == "CLASS":
        return (1, str(getattr(node, "id", "")))
    if kind == "MODULE":
        return (2, str(getattr(node, "id", "")))
    return (3, str(getattr(node, "id", "")))


def _review_node(node: Any) -> dict[str, Any]:
    properties = getattr(node, "properties", {}) or {}
    return {
        "id": node.id,
        "name": node.name,
        "kind": node.kind,
        "file": _node_file(node),
        "line": properties.get("line"),
    }


def _review_node_sort_key(node: dict[str, Any]) -> tuple[int, str, int, str]:
    file_name = str(node.get("file") or "").lower()
    test_rank = 1 if "test" in file_name else 0
    line_value = node.get("line")
    line = int(line_value) if isinstance(line_value, int) else -1
    return (test_rank, file_name, line, str(node.get("id", "")))


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
    # Directory proximity is useful only when it is a real shared area; at the
    # repository root it would make every test look related.  Filename pairing
    # handles common conventions across Python, JS/TS, Go, Java and .NET.
    test_area = _normalised_source_area(test_parts[:-1])
    changed_area = _normalised_source_area(changed_parts[:-1])
    # The directories must be equal after removing conventional source/test
    # roots.  Intersecting directory names made every Java test under
    # ``src/test/java/org/...`` look related to every production class under
    # ``src/main/java/org/...``.
    shared_area = bool(test_area) and test_area == changed_area
    return shared_area or _test_target_stem(test_parts[-1]) == _test_target_stem(changed_parts[-1])


def _normalised_source_area(parts: list[str]) -> tuple[str, ...]:
    lowered = [part.lower() for part in parts if part]
    for marker in (("src", "main"), ("src", "test"), ("src", "tests"), ("test",), ("tests",)):
        if tuple(lowered[:len(marker)]) == marker:
            lowered = lowered[len(marker):]
            break
    if lowered and lowered[0] in {"java", "kotlin", "scala", "python", "go", "js", "ts", "typescript"}:
        lowered = lowered[1:]
    return tuple(lowered)


def _test_target_stem(file_name: str) -> str:
    stem = Path(file_name).stem.lower()
    for prefix in ("test_", "test-", "test."):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    for suffix in ("_tests", "-tests", ".tests", "tests", "_test", "-test", ".test", "test", "_spec", "-spec", ".spec", "spec", "_specs", "-specs", ".specs", "specs"):
        if stem.endswith(suffix) and len(stem) > len(suffix):
            stem = stem[:-len(suffix)]
            break
    return stem


def _is_test_file(file_name: str) -> bool:
    """Recognise test conventions without treating ordinary source as a test.

    A substring test (``"test" in path``) marks production files such as
    ``createStore.ts`` as tests.  Paths and basenames are evaluated separately
    so common conventions remain portable across Python, Go, JS/TS, Java,
    .NET, PHP and Ruby projects.
    """
    path = Path(file_name.replace("\\", "/"))
    parts = {part.lower() for part in path.parts[:-1]}
    if parts & {"test", "tests", "__tests__", "spec", "specs"}:
        return True
    stem = path.stem.lower()
    return (
        stem.startswith(("test_", "test-", "test."))
        or stem.endswith(("_test", "-test", ".test", "_tests", "-tests", ".tests", "spec", "specs", "test", "tests"))
    )


def _test_file_for_node(graph: GraphDocument, node_id: str) -> str | None:
    node = next((item for item in graph.nodes if item.id == node_id), None)
    if node is None:
        return None
    return node.properties.get("file") or node.properties.get("path")
