"""Feature extraction and deterministic candidate scoring."""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from impact_engine.edge_quality import classify_edge_quality
from impact_engine.ranking_policy import DEFAULT_RANKING_POLICY, RankingPolicy
from .filters import is_boundary_node, is_test_node, node_file, semantic_cluster, suppression_reason


# Impact traversal is intentionally asymmetric.  For a changed dependency we
# follow consumers (incoming edges), not every graph neighbour.  Boundary
# edges that represent a request/event can be traversed in both directions.
_INCOMING_IMPACT_KINDS = {
    "CALLS", "IMPORTS", "EXPORTS", "RESOLVES_TO", "DEPENDS_ON", "ROUTE_HANDLES",
    "TESTS", "READS", "WRITES", "SUBSCRIBES_TO", "CONSUMES",
}
_OUTGOING_IMPACT_KINDS = {"CONTAINS", "DECLARES"}
_BIDIRECTIONAL_IMPACT_KINDS = {
    "HTTP_CALLS", "MATCHES_ENDPOINT", "AFFECTS", "USES_COMPONENT", "EMITS", "PRODUCES",
}


def _same_path(left: Any, right: Any) -> bool:
    left_value = str(left or "").replace("\\", "/").lstrip("./")
    right_value = str(right or "").replace("\\", "/").lstrip("./")
    return bool(left_value and right_value and (left_value == right_value or left_value.endswith("/" + right_value) or right_value.endswith("/" + left_value)))


def is_changed_downstream_edge(edge: Any, changed: dict[str, Any]) -> bool:
    """Allow only hunk-local outgoing calls from the changed declaration.

    Normal CALLS traversal is consumer-oriented (incoming edges).  A changed
    callable also needs its proven direct calls in Review, but arbitrary
    outgoing edges can be reversed/noisy.  Hunk-local evidence is the explicit
    guard that distinguishes the two cases.
    """
    kind = str(getattr(edge, "kind", "")).upper()
    if kind not in {"CALLS", "HTTP_CALLS", "MATCHES_ENDPOINT", "AFFECTS", "USES_COMPONENT", "EMITS", "PRODUCES"}:
        return False
    changed_lines = {int(value) for value in (changed.get("changed_lines") or []) if isinstance(value, int)}
    changed_file = changed.get("file")
    if not changed_file:
        return False
    entity_scope = bool(changed.get("entity_scope"))
    if not changed_lines and not entity_scope:
        return False
    for evidence in getattr(edge, "evidence", []) or []:
        if _same_path(getattr(evidence, "file", None), changed_file) and (entity_scope or getattr(evidence, "line", None) in changed_lines):
            return True
    return False


def traversal_directions(edge: Any) -> tuple[str, ...]:
    """Return legal traversal directions for an impact edge.

    The direction is a property of the edge semantics, not of the current
    node.  Unknown edge kinds are not traversed in concise review; their facts
    remain available through deep graph inspection and explain-edge.
    """
    kind = str(getattr(edge, "kind", "")).upper()
    if kind in _BIDIRECTIONAL_IMPACT_KINDS:
        return ("outgoing", "incoming")
    if kind in _OUTGOING_IMPACT_KINDS:
        return ("outgoing",)
    if kind in _INCOMING_IMPACT_KINDS:
        return ("incoming",)
    return ()


def _edge_properties(edge: Any) -> dict[str, Any]:
    return getattr(edge, "properties", {}) or {}


def edge_features(edge: Any, source_node: Any, target_node: Any, depth: int) -> list[str]:
    props = _edge_properties(edge)
    kind = str(getattr(edge, "kind", "")).upper()
    source = str(getattr(edge, "source", "")).upper()
    features: list[str] = []
    if kind in {"IMPORTS", "RESOLVES_TO", "DECLARES"} and source in {"EXTRACTED", "INFERRED", "RUNTIME_CONFIRMED", "MANUAL"}:
        features.append("direct_import_export")
    if kind == "CONTAINS" and depth == 1 and source in {"EXTRACTED", "INFERRED", "RUNTIME_CONFIRMED", "MANUAL"}:
        features.append("direct_container")
    if kind == "CALLS" and source in {"EXTRACTED", "INFERRED", "RUNTIME_CONFIRMED", "MANUAL"}:
        features.append("direct_resolved_call")
    # A test file being connected by an import/call is not proof that it
    # covers the changed symbol.  Only an explicit TESTS edge earns test
    # evidence in the impact score; nearby tests are selected separately.
    if kind == "TESTS":
        features.append("test_direct")
    boundary = str(props.get("boundary_category") or props.get("semantic_role") or props.get("role") or "").lower()
    if kind in {"ROUTE_HANDLES", "MATCHES_ENDPOINT"} or boundary in {"route", "api", "public_api"}:
        features.append("route_handler_boundary")
    if kind in {"HTTP_CALLS", "MATCHES_ENDPOINT"} or boundary in {"http", "rpc", "frontend_backend", "contract"}:
        features.append("frontend_backend_boundary")
    if boundary in {"schema", "entity", "database", "db", "persistence"} or kind in {"READS", "WRITES"} and props.get("database"):
        features.append("schema_database_boundary")
    if boundary in {"queue", "producer", "consumer", "async"} or kind in {"AFFECTS", "USES_COMPONENT"} and props.get("queue"):
        features.append("queue_boundary")
    if is_boundary_node(source_node) or is_boundary_node(target_node):
        features.append("public_api_boundary")
    source_file = str(node_file(source_node) or "").replace("\\", "/").split("/")
    target_file = str(node_file(target_node) or "").replace("\\", "/").split("/")
    if source_file and target_file and source_file[0] != target_file[0] and len(source_file) > 1 and len(target_file) > 1:
        features.append("cross_package")
    if props.get("critical") or props.get("critical_path") or getattr(target_node, "properties", {}).get("critical_path"):
        features.append("critical_path")
    if kind in {"ASSIGNS", "WRITES"} and str(getattr(target_node, "kind", "")).upper() == "ASSIGNMENT":
        features.append("assignment_only")
    target_props = getattr(target_node, "properties", {}) or {}
    if target_props.get("is_hub") and int(target_props.get("graph_degree", 0) or 0) >= 20:
        features.append("high_fanout_hub")
    target_name = str(getattr(target_node, "name", "")).lower()
    if target_props.get("builtin") or target_name in {"len", "str", "int", "float", "bool", "dict", "list", "set", "tuple", "print", "range"}:
        features.append("builtin")
    if str(getattr(target_node, "kind", "")).upper() in {"EXTERNAL_LIBRARY", "SUPPORT_PACK", "LIBRARY"}:
        features.append("external_library")
    if suppression_reason(target_node) == "generated/vendor dependency":
        features.append("generated_or_vendor")
    status = classify_edge_quality(edge).status
    resolution = str(props.get("resolution_status") or props.get("status") or "").lower()
    if status in {"suspicious", "weak"} or resolution in {"ambiguous", "unresolved", "name_only"} or source in {"AI_PROPOSED", "SUPPORT_PACK"}:
        features.append("weak_name_inference")
    if resolution in {"ambiguous", "suspicious"} or "ambiguous" in " ".join(str(x) for x in props.get("warnings", []) or []).lower():
        features.append("ambiguous")
    if props.get("unresolved_endpoint") or resolution == "unresolved" or not getattr(edge, "evidence", None):
        features.append("unresolved_endpoint")
    if depth > 1:
        features.append("transitive_depth")
    return list(dict.fromkeys(features))


def score_path(edges: Iterable[Any], nodes: list[Any], depth: int, policy: RankingPolicy = DEFAULT_RANKING_POLICY) -> tuple[float, list[str], dict[str, float]]:
    edges = list(edges)
    breakdown: Counter[str] = Counter()
    factors: list[str] = []
    seen_features: set[str] = set()
    for index, edge in enumerate(edges):
        source_node = nodes[index] if index < len(nodes) else nodes[0]
        target_node = nodes[index + 1] if index + 1 < len(nodes) else nodes[-1]
        for feature in edge_features(edge, source_node, target_node, depth):
            if feature not in factors:
                factors.append(feature)
            # A repeated CALLS edge is one kind of evidence path, not a reason
            # for a deep chain to beat a direct boundary.  Independent paths
            # are rewarded explicitly below.
            if feature not in seen_features:
                breakdown[feature] += policy.weights().get(feature, 0.0)
                seen_features.add(feature)
    if len(edges) > 1:
        independent = len({str(getattr(edge, "source", "")) + ":" + str(getattr(edge, "kind", "")) for edge in edges})
        if independent > 1:
            factors.append("independent_evidence_path")
            breakdown["independent_evidence_path"] += policy.weights()["independent_evidence_path"]
    if depth > 1:
        breakdown["transitive_depth"] += policy.weights()["transitive_depth"] * (depth - 1)
    return round(sum(breakdown.values()), 6), tuple(dict.fromkeys(factors)), dict(sorted(breakdown.items()))
