"""Runtime trace booster adapter for Impact Engine graphs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime_trace_booster import apply_runtime_trace_to_graph, run_runtime_trace

from impact_engine.models import GraphDocument


def run_runtime_trace_boost(
    project_path: str,
    graph: GraphDocument | dict[str, Any] | None = None,
    test_command: list[str] | None = None,
    timeout_seconds: int = 60,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> dict[str, Any]:
    """Run project tests under runtime tracing and match calls to graph edges."""

    graph_dict = _graph_to_dict(graph) if graph is not None else None
    return run_runtime_trace(
        project_path=project_path,
        test_command=test_command,
        graph=graph_dict,
        timeout_seconds=timeout_seconds,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
    )


def apply_runtime_trace_boost(
    graph: GraphDocument | dict[str, Any],
    trace_result: dict[str, Any],
) -> GraphDocument:
    """Apply runtime confirmations and return a GraphDocument."""

    patched = apply_runtime_trace_to_graph(_graph_to_dict(graph), trace_result)
    normalized = _normalize_runtime_patch_shape(patched)
    document = GraphDocument.from_dict(normalized)
    document.metadata["runtime_trace_booster"] = {
        "status": trace_result.get("status"),
        "exit_code": trace_result.get("exit_code"),
        "runtime_calls": len(trace_result.get("runtime_calls", []) or []),
        "matched_edges": len(trace_result.get("matched_edges", []) or []),
        "unmatched_calls": len(trace_result.get("unmatched_calls", []) or []),
        "tests": len(trace_result.get("tests", []) or []),
        "validation_semantics": "runtime_observed; absence is not rejection",
        "instrumentation": trace_result.get("instrumentation", "python-profile-hook"),
    }
    document.metadata["runtime_only_observations"] = [
        {
            "kind": "runtime_only_observation",
            "status": "quarantined",
            "reason": "runtime target was not mapped to a static graph edge",
            "call": call,
        }
        for call in trace_result.get("unmatched_calls", []) or []
    ]
    for edge in document.edges:
        if edge.properties.get("runtime_confirmed") or edge.properties.get("runtime_observed"):
            edge.properties["validation_status"] = "runtime_observed"
            edge.properties["runtime_observation"] = {
                "tests": edge.properties.get("confirmed_by_tests", []),
                "environment": trace_result.get("environment", "pytest"),
                "instrumentation": trace_result.get("instrumentation", "python-profile-hook"),
                "scenario_hash": trace_result.get("scenario_hash"),
            }
    return document


def runtime_trace_project_core(
    project_path: str,
    graph_path: str | None = None,
    out_path: str | None = None,
    test_command: list[str] | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Analyze or load graph, run runtime trace, optionally write patched graph."""

    project = Path(project_path).resolve()
    if not project.exists():
        raise FileNotFoundError(f"Project path does not exist: {project_path}")

    if graph_path:
        graph = GraphDocument.from_json(Path(graph_path).read_text(encoding="utf-8"))
    else:
        from impact_engine.analysis.pipeline import analyze_project_core

        analysis = analyze_project_core(str(project))
        graph = GraphDocument.from_dict(analysis["graph"])

    trace = run_runtime_trace_boost(
        project_path=str(project),
        graph=graph,
        test_command=test_command,
        timeout_seconds=timeout_seconds,
    )
    patched_graph = apply_runtime_trace_boost(graph, trace) if trace.get("status") == "ok" else graph
    graph_output_path = None
    if out_path:
        out = Path(out_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(patched_graph.to_json(), encoding="utf-8")
        graph_output_path = str(out)

    return {
        "status": trace.get("status"),
        "project_path": str(project),
        "graph_path": graph_path,
        "out_path": graph_output_path,
        "trace": trace,
        "graph": patched_graph.to_dict(),
        "summary": {
            "runtime_calls": len(trace.get("runtime_calls", []) or []),
            "matched_edges": len(trace.get("matched_edges", []) or []),
            "unmatched_calls": len(trace.get("unmatched_calls", []) or []),
            "tests": len(trace.get("tests", []) or []),
        },
    }


def _graph_to_dict(graph: GraphDocument | dict[str, Any]) -> dict[str, Any]:
    if isinstance(graph, GraphDocument):
        return graph.to_dict()
    return graph


def _normalize_runtime_patch_shape(graph: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(graph)
    edges = []
    for edge in graph.get("edges", []) or []:
        item = dict(edge)
        properties = dict(item.get("properties", {}) or {})
        for key in ("runtime_confirmed", "runtime_confidence", "confirmed_by_tests", "sources"):
            if key in item:
                properties[key] = item.pop(key)
        item["properties"] = properties
        edges.append(item)
    normalized["edges"] = edges
    return normalized
