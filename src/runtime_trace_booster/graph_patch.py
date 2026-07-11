"""Apply runtime confirmation results to graph dictionaries."""

from __future__ import annotations

import copy
from typing import Any

from .matcher import group_matches_by_edge


def _edge_id(edge: dict[str, Any], index: int) -> str:
    return str(edge.get("id") or edge.get("edge_id") or f"edge:{index}")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _append_unique(items: list[Any], value: Any) -> None:
    if value not in items:
        items.append(value)


def _test_file_lookup(trace_result: dict[str, Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for test in trace_result.get("tests", []) or []:
        test_id = str(test.get("id", ""))
        if test_id:
            lookup[test_id] = str(test.get("file", ""))
    return lookup


def apply_runtime_trace_to_graph(
    graph: dict[str, Any],
    trace_result: dict[str, Any],
    *,
    create_unmatched_edges: bool = False,
) -> dict[str, Any]:
    """Return a new graph with runtime confirmation metadata applied.

    Existing matched ``CALLS`` edges are updated. Unmatched runtime calls are not
    converted into new graph edges unless ``create_unmatched_edges=True``. The
    default is deliberately conservative because runtime observations are used as
    confirmations, not as graph invention.
    """

    patched = copy.deepcopy(graph)
    edges = patched.setdefault("edges", [])
    tests_by_id = _test_file_lookup(trace_result)
    matches = trace_result.get("matched_edges", []) or []
    grouped = group_matches_by_edge(matches)

    for index, edge in enumerate(edges):
        edge_id = _edge_id(edge, index)
        edge_matches = grouped.get(edge_id, [])
        if not edge_matches:
            continue

        best_confidence = max(_as_float(match.get("runtime_confidence"), 0.98) for match in edge_matches)
        edge["confidence"] = max(_as_float(edge.get("confidence"), 0.0), best_confidence)
        edge["runtime_confidence"] = max(_as_float(edge.get("runtime_confidence"), 0.0), best_confidence)
        edge["runtime_confirmed"] = True
        edge["runtime_observed"] = True
        edge["validation_status"] = "runtime_observed"
        edge["runtime_observation"] = {
            "test_ids": [str(match.get("test_id", "")) for match in edge_matches if match.get("test_id")],
            "instrumentation": trace_result.get("instrumentation", "python-profile-hook"),
            "environment": trace_result.get("environment", "pytest"),
            "scenario_hash": trace_result.get("scenario_hash"),
        }

        if not edge.get("source"):
            edge["source"] = "RUNTIME_CONFIRMED"
        else:
            sources = edge.setdefault("sources", [])
            if isinstance(sources, list):
                _append_unique(sources, str(edge.get("source")))
                _append_unique(sources, "RUNTIME_CONFIRMED")

        confirmed_by = edge.setdefault("confirmed_by_tests", [])
        if not isinstance(confirmed_by, list):
            confirmed_by = [confirmed_by]
            edge["confirmed_by_tests"] = confirmed_by

        evidence = edge.setdefault("evidence", [])
        if not isinstance(evidence, list):
            evidence = [evidence]
            edge["evidence"] = evidence

        for match in edge_matches:
            test_id = str(match.get("test_id", ""))
            if test_id:
                _append_unique(confirmed_by, test_id)
            item = {
                "description": f"Runtime confirmed by {test_id}" if test_id else "Runtime confirmed by tests",
                "file": tests_by_id.get(test_id, ""),
                "source": "RUNTIME_CONFIRMED",
                "runtime_confidence": _as_float(match.get("runtime_confidence"), 0.98),
                "runtime_evidence": match.get("evidence", {}),
            }
            if item not in evidence:
                evidence.append(item)

    if create_unmatched_edges:
        for call in trace_result.get("unmatched_calls", []) or []:
            edges.append(
                {
                    "id": f"runtime:{len(edges)}",
                    "from": call.get("caller"),
                    "to": call.get("callee"),
                    "kind": "CALLS",
                    "confidence": _as_float(call.get("confidence"), 0.98),
                    "runtime_confidence": _as_float(call.get("confidence"), 0.98),
                    "runtime_confirmed": True,
                    "runtime_observed": True,
                    "validation_status": "runtime_only_observation",
                    "source": "RUNTIME_CONFIRMED",
                    "confirmed_by_tests": [call.get("test_id")],
                    "evidence": [
                        {
                            "description": f"Runtime observed unmatched call by {call.get('test_id', '')}",
                            "file": "",
                            "source": "RUNTIME_CONFIRMED",
                            "runtime_evidence": {
                                "caller_file": call.get("caller_file"),
                                "caller_line": call.get("caller_line"),
                                "callee_file": call.get("callee_file"),
                                "callee_line": call.get("callee_line"),
                            },
                        }
                    ],
                }
            )

    return patched
