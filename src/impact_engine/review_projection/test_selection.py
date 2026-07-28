"""Targeted test selection, independent from impact candidate ranking."""
from __future__ import annotations

from collections import deque
from typing import Any

from impact_engine.edge_quality import classify_edge_quality
from .contracts import ReviewEvidence, TestRecommendation
from .filters import is_test_node, node_file


CATEGORY_SCORES = {
    "direct_changed_symbol": 100.0,
    "direct_impacted_symbol": 82.0,
    "route_controller_integration": 72.0,
    "frontend_backend_contract": 68.0,
    "service_repository_integration": 62.0,
    "fallback_suite": 20.0,
}


def _confidence(edge: Any) -> str:
    quality = classify_edge_quality(edge).status
    if quality == "confirmed":
        return "confirmed"
    if quality in {"likely", "weak"}:
        return "likely"
    if quality == "suspicious":
        return "unresolved"
    return "speculative"


def _node_label(node: Any) -> str:
    return str(getattr(node, "name", "") or getattr(node, "id", ""))


def _test_file(node: Any) -> str | None:
    """Resolve a test file even when the extractor materialized only a module id."""
    file_name = node_file(node)
    if file_name:
        return file_name
    raw = str(getattr(node, "name", "") or getattr(node, "id", ""))
    if raw.startswith("module:"):
        raw = raw[len("module:"):]
    if raw.count(".") >= 2 and ".test_" in raw:
        raw = raw.rsplit(".test_", 1)[0]
    if raw.startswith(("tests.", "test.", "spec.")):
        return raw.replace(".", "/") + ".py"
    return None


def _path_confidence(edges: list[Any]) -> str:
    values = [_confidence(edge) for edge in edges]
    if "speculative" in values:
        return "speculative"
    if "unresolved" in values:
        return "unresolved"
    if "likely" in values:
        return "likely"
    return "confirmed"


def _path_category(path_edges: list[Any], path_nodes: list[Any], changed_ids: set[str], impacted_ids: set[str]) -> str | None:
    if not path_edges or not path_nodes:
        return None
    terminal = path_nodes[-1]
    terminal_id = str(getattr(terminal, "id", ""))
    first_kind = str(getattr(path_edges[0], "kind", "")).upper()
    terminal_role = str((getattr(terminal, "properties", {}) or {}).get("role") or (getattr(terminal, "properties", {}) or {}).get("boundary_category") or "").lower()
    terminal_kind = str(getattr(terminal, "kind", "")).upper()
    is_route = terminal_role in {"route", "controller", "api"} or terminal_kind in {"ROUTE", "HTTP_ROUTE", "CONTROLLER"}
    is_contract = terminal_role in {"http", "rpc", "frontend_backend", "contract"}
    if terminal_id in changed_ids and len(path_edges) == 1 and first_kind in {"TESTS", "CALLS", "IMPORTS"}:
        return "direct_changed_symbol"
    if terminal_id in impacted_ids and len(path_edges) == 1 and first_kind in {"TESTS", "CALLS", "IMPORTS"} and not is_route and not is_contract:
        return "direct_impacted_symbol"
    roles = {
        str((getattr(node, "properties", {}) or {}).get("role") or "").lower()
        for node in path_nodes
    }
    kinds = {str(getattr(node, "kind", "")).upper() for node in path_nodes}
    edge_kinds = {str(getattr(edge, "kind", "")).upper() for edge in path_edges}
    if edge_kinds & {"HTTP_CALLS", "MATCHES_ENDPOINT"} or roles & {"http", "rpc", "frontend_backend", "contract"}:
        return "frontend_backend_contract"
    if roles & {"route", "controller", "api"} or kinds & {"ROUTE", "HTTP_ROUTE", "CONTROLLER"} or "ROUTE_HANDLES" in edge_kinds:
        return "route_controller_integration"
    if terminal_id in impacted_ids or any(str(getattr(node, "id", "")) in impacted_ids for node in path_nodes[1:]):
        return "service_repository_integration"
    return None


def _build_test_path_index(graph: Any) -> tuple[dict[str, Any], dict[str, list[Any]], dict[str, Any]]:
    nodes = {node.id: node for node in graph.nodes}
    outgoing: dict[str, list[Any]] = {}
    edge_by_id: dict[str, Any] = {}
    allowed = {"TESTS", "CALLS", "IMPORTS", "RESOLVES_TO", "CONTAINS", "DECLARES", "HTTP_CALLS", "MATCHES_ENDPOINT", "ROUTE_HANDLES", "DEPENDS_ON", "READS", "WRITES", "USES_COMPONENT", "AFFECTS"}
    for edge in graph.edges:
        if edge.from_node in nodes and edge.to_node in nodes and str(edge.kind).upper() in allowed:
            outgoing.setdefault(edge.from_node, []).append(edge)
            edge_by_id[edge.id] = edge
    for edges in outgoing.values():
        edges.sort(key=lambda edge: (-float(getattr(edge, "confidence", 0.0) or 0.0), str(edge.kind), str(edge.id)))
    return nodes, outgoing, edge_by_id


def _path_has_boundary(path_edges: list[Any], path_nodes: list[Any]) -> bool:
    edge_kinds = {str(getattr(edge, "kind", "")).upper() for edge in path_edges}
    if edge_kinds & {"HTTP_CALLS", "MATCHES_ENDPOINT", "ROUTE_HANDLES"}:
        return True
    for node in path_nodes:
        properties = getattr(node, "properties", {}) or {}
        role = str(properties.get("role") or properties.get("boundary_category") or "").lower()
        kind = str(getattr(node, "kind", "")).upper()
        if role in {"route", "controller", "api", "http", "rpc", "frontend_backend", "contract"} or kind in {"ROUTE", "HTTP_ROUTE", "CONTROLLER"}:
            return True
    return False


def _test_paths(
    graph: Any,
    test_node: Any,
    targets: set[str],
    max_depth: int = 4,
    *,
    nodes: dict[str, Any] | None = None,
    outgoing: dict[str, list[Any]] | None = None,
    edge_by_id: dict[str, Any] | None = None,
) -> list[tuple[list[Any], list[Any]]]:
    """Find short, source-backed paths starting at a test node.

    This is intentionally separate from impact traversal: a test's outgoing
    TESTS/CALLS/IMPORTS edge is proof of what the test exercises, whereas the
    impact projection walks consumers of a changed node.
    """
    if nodes is None or outgoing is None or edge_by_id is None:
        nodes, outgoing, edge_by_id = _build_test_path_index(graph)
    result: list[tuple[list[Any], list[Any]]] = []
    queue = deque([(test_node.id, [], [test_node.id])])
    visited: set[tuple[str, tuple[str, ...]]] = set()
    while queue and len(visited) < 300:
        current, edge_ids, node_ids = queue.popleft()
        if len(edge_ids) >= max_depth:
            continue
        for edge in outgoing.get(current, [])[:12]:
            if edge.id in edge_ids or edge.to_node in node_ids:
                continue
            next_edges = edge_ids + [edge.id]
            next_nodes = node_ids + [edge.to_node]
            state = (edge.to_node, tuple(next_edges))
            if state in visited:
                continue
            visited.add(state)
            next_properties = getattr(nodes[edge.to_node], "properties", {}) or {}
            next_role = str(next_properties.get("role") or next_properties.get("boundary_category") or "").lower()
            next_kind = str(getattr(nodes[edge.to_node], "kind", "")).upper()
            next_is_boundary = next_role in {"route", "controller", "api", "http", "rpc", "frontend_backend", "contract"} or next_kind in {"ROUTE", "HTTP_ROUTE", "CONTROLLER"}
            # A boundary alone is not proof that this test covers the
            # changed area. Continue through the boundary and emit a path only
            # once it reaches a changed or selected impacted target. This
            # prevents every HTTP test in a large corpus from becoming a
            # recommendation for an unrelated controller.
            if edge.to_node in targets:
                node_path = [nodes[item] for item in next_nodes]
                edge_path = [edge_by_id[item_id] for item_id in next_edges]
                result.append((edge_path, node_path))
            queue.append((edge.to_node, next_edges, next_nodes))
    return result


def select_targeted_tests(graph: Any, changed_ids: set[str], impacted_ids: set[str], evidence_by_id: dict[str, ReviewEvidence], changed_files: set[str], max_results: int = 10) -> list[TestRecommendation]:
    nodes, outgoing, edge_by_id = _build_test_path_index(graph)
    recommendations: dict[str, TestRecommendation] = {}
    targets = set(changed_ids) | set(impacted_ids)
    for test_node in nodes.values():
        # Most large graphs contain unresolved names beginning with ``test``.
        # Without an outgoing semantic edge they cannot prove test coverage.
        if str(getattr(test_node, "kind", "")).upper() in {"EXTERNAL_LIBRARY", "PROJECT", "FILE", "MODULE"}:
            continue
        if not is_test_node(test_node) or test_node.id not in outgoing:
            continue
        for path_edges, path_nodes in _test_paths(graph, test_node, targets, nodes=nodes, outgoing=outgoing, edge_by_id=edge_by_id):
            category = _path_category(path_edges, path_nodes, changed_ids, impacted_ids)
            if category is None:
                continue
            evidence_ids: list[str] = []
            for index, edge in enumerate(path_edges):
                location = next((item for item in getattr(edge, "evidence", []) if getattr(item, "file", None) or getattr(item, "line", None)), None)
                evidence_id = f"test-path:{test_node.id}:{edge.id}:{index}"
                ev = ReviewEvidence(
                    id=evidence_id,
                    file=getattr(location, "file", None),
                    line=getattr(location, "line", None),
                    kind=edge.kind,
                    description=f"{_node_label(test_node)} reaches {_node_label(path_nodes[-1])} through {_node_label(path_nodes[-2]) if len(path_nodes) > 1 else _node_label(path_nodes[-1])}",
                    source=getattr(location, "source", None) or getattr(edge, "source", None),
                    confidence=getattr(edge, "confidence", None),
                )
                evidence_by_id.setdefault(evidence_id, ev)
                evidence_ids.append(evidence_id)
            confidence = _path_confidence(path_edges)
            file_name = _test_file(test_node)
            properties = getattr(test_node, "properties", {}) or {}
            command = properties.get("test_command") or properties.get("command")
            labels = " -> ".join(_node_label(node) for node in path_nodes)
            recommendation = TestRecommendation(
                file=file_name, symbol=test_node.id, category=category,
                score=CATEGORY_SCORES[category] + sum(float(getattr(edge, "confidence", 0.0) or 0.0) for edge in path_edges) / max(1, len(path_edges)),
                confidence=confidence, evidence_ids=tuple(evidence_ids),
                reason=f"{category.replace('_', ' ')} is proven by {labels}", command=command,
                fallback_status="primary",
            )
            recommendation_key = _recommendation_key(test_node, file_name, command)
            old = recommendations.get(recommendation_key)
            if old is None or (recommendation.score, recommendation.category) > (old.score, old.category):
                recommendations[recommendation_key] = recommendation

    if not recommendations:
        for node in nodes.values():
            if str(getattr(node, "kind", "")).upper() in {"EXTERNAL_LIBRARY", "PROJECT", "FILE", "MODULE"}:
                continue
            if not is_test_node(node):
                continue
            file_name = _test_file(node)
            if not file_name or not any(_same_area(file_name, changed) for changed in changed_files):
                continue
            ev = ReviewEvidence(id=f"test:fallback:{node.id}", file=file_name, kind="NEARBY_TEST", description="test is near a changed file", source="EXTRACTED")
            evidence_by_id.setdefault(ev.id, ev)
            recommendation = TestRecommendation(
                file=file_name, symbol=node.id, category="fallback_suite", score=CATEGORY_SCORES["fallback_suite"],
                confidence="likely", evidence_ids=(ev.id,), reason="no exact targeted test was found", fallback_status="fallback",
                command=(getattr(node, "properties", {}) or {}).get("test_command"),
            )
            recommendations.setdefault(_recommendation_key(node, file_name, recommendation.command), recommendation)
    ranked = sorted(recommendations.values(), key=lambda item: (-item.score, item.file or "", item.symbol))
    return ranked[:max(1, min(max_results, 5))]


def _same_area(test_file: str, changed_file: str) -> bool:
    test_parts = test_file.replace("\\", "/").split("/")
    changed_parts = changed_file.replace("\\", "/").split("/")
    return bool(set(test_parts[:-1]) & set(changed_parts[:-1])) or test_parts[-1].replace("test_", "").replace(".test", "") in changed_parts[-1]


def _recommendation_key(test_node: Any, file_name: str | None, command: Any) -> str:
    """Key recommendations by what the UI can actually execute.

    A single test can be represented by a ``call:`` node and a ``method:``
    node. The runner executes the file/command, so those representations must
    share one recommendation rather than produce duplicate checkboxes.
    """
    if file_name:
        normalized_file = file_name.replace("\\", "/").lower()
        return f"file:{normalized_file}"
    if command:
        return f"command:{' '.join(str(command).split()).lower()}"
    symbol = str(getattr(test_node, "id", "") or getattr(test_node, "name", ""))
    for prefix in ("call:", "method:", "function:"):
        if symbol.lower().startswith(prefix):
            symbol = symbol[len(prefix):]
            break
    return f"symbol:{symbol.lower()}"
