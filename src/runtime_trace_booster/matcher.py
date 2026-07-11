"""Runtime call to static graph edge matching."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

CALL_KIND = "CALLS"
METHOD_PREFIX = "method:"
FUNCTION_PREFIX = "function:"
CLASS_PREFIX = "class:"


def normalize_symbol_id(symbol: str | None) -> str:
    """Normalize graph node IDs for runtime call matching."""

    if symbol is None:
        return ""
    value = str(symbol).strip()
    for prefix in (METHOD_PREFIX, FUNCTION_PREFIX, CLASS_PREFIX):
        if value.startswith(prefix):
            return value[len(prefix) :]
    return value


def _edge_from(edge: dict[str, Any]) -> str:
    return str(edge.get("from", edge.get("source", "")))


def _edge_to(edge: dict[str, Any]) -> str:
    return str(edge.get("to", edge.get("target", "")))


def _edge_id(edge: dict[str, Any], index: int) -> str:
    return str(edge.get("id") or edge.get("edge_id") or f"edge:{index}")


def _method_name(symbol: str) -> str:
    normalized = normalize_symbol_id(symbol)
    return normalized.rsplit(".", 1)[-1] if normalized else ""


def _suffix_compatible(runtime_symbol: str, graph_symbol: str) -> bool:
    runtime = normalize_symbol_id(runtime_symbol)
    graph = normalize_symbol_id(graph_symbol)
    if not runtime or not graph:
        return False
    if _method_name(runtime) != _method_name(graph):
        return False
    return runtime == graph or runtime.endswith("." + graph) or graph.endswith("." + runtime)


def _exact_match(runtime_symbol: str, graph_symbol: str) -> bool:
    return normalize_symbol_id(runtime_symbol) == normalize_symbol_id(graph_symbol)


def _build_matched_edge(edge: dict[str, Any], index: int, call: dict[str, Any]) -> dict[str, Any]:
    return {
        "edge_id": _edge_id(edge, index),
        "from": _edge_from(edge),
        "to": _edge_to(edge),
        "kind": str(edge.get("kind", "")),
        "runtime_confidence": float(call.get("confidence", 0.98)),
        "test_id": str(call.get("test_id", "")),
        "evidence": {
            "caller_file": call.get("caller_file"),
            "caller_line": call.get("caller_line"),
            "callee_file": call.get("callee_file"),
            "callee_line": call.get("callee_line"),
        },
    }


def _calls_edges(graph: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    return [
        (index, edge)
        for index, edge in enumerate(graph.get("edges", []) or [])
        if str(edge.get("kind", "")).upper() == CALL_KIND
    ]


def match_runtime_calls_to_graph(graph: dict[str, Any], runtime_calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Match runtime calls to ``CALLS`` edges in *graph*.

    Matching order:
    1. exact symbol match after accepting common prefixes such as ``method:``;
    2. unique suffix match, useful when a graph stores fully-qualified package
       IDs but runtime symbols are project-relative.

    Ambiguous suffix matches are intentionally left unmatched.
    """

    matched_edges: list[dict[str, Any]] = []
    unmatched_calls: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    seen_match_keys: set[tuple[str, str]] = set()
    edges = _calls_edges(graph)

    for call in runtime_calls:
        caller = str(call.get("caller", ""))
        callee = str(call.get("callee", ""))
        exact_candidates: list[tuple[int, dict[str, Any]]] = []
        suffix_candidates: list[tuple[int, dict[str, Any]]] = []

        for index, edge in edges:
            graph_from = _edge_from(edge)
            graph_to = _edge_to(edge)
            if _exact_match(caller, graph_from) and _exact_match(callee, graph_to):
                exact_candidates.append((index, edge))
            elif _suffix_compatible(caller, graph_from) and _suffix_compatible(callee, graph_to):
                suffix_candidates.append((index, edge))

        selected: tuple[int, dict[str, Any]] | None = None
        if len(exact_candidates) == 1:
            selected = exact_candidates[0]
        elif len(exact_candidates) > 1:
            diagnostics.append(
                {
                    "level": "warning",
                    "message": "Runtime call matched multiple exact CALLS edges and was left unmatched.",
                    "details": {"caller": caller, "callee": callee, "matches": len(exact_candidates)},
                }
            )
        elif len(suffix_candidates) == 1:
            selected = suffix_candidates[0]
        elif len(suffix_candidates) > 1:
            diagnostics.append(
                {
                    "level": "info",
                    "message": "Runtime call had ambiguous suffix matches and was left unmatched.",
                    "details": {"caller": caller, "callee": callee, "matches": len(suffix_candidates)},
                }
            )

        if selected is None:
            unmatched_calls.append(call)
            continue

        index, edge = selected
        match_key = (_edge_id(edge, index), str(call.get("test_id", "")))
        if match_key in seen_match_keys:
            continue
        seen_match_keys.add(match_key)
        matched_edges.append(_build_matched_edge(edge, index, call))

    return {
        "matched_edges": matched_edges,
        "unmatched_calls": unmatched_calls,
        "diagnostics": diagnostics,
    }


def group_matches_by_edge(matches: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for match in matches:
        grouped[str(match.get("edge_id", ""))].append(match)
    return dict(grouped)
