"""Public resolver entry point."""

from __future__ import annotations

from typing import Any

from .bindings import ObjectBindingResolver
from .index import FactIndex, normalize_path, validate_input
from .models import Edge, path_to_string
from .quality import split_edges, status_for_resolution

_OUTPUT_LIST_KEYS = (
    "bindings",
    "resolved_calls",
    "edges",
    "confirmed",
    "likely",
    "weak",
    "suspicious",
    "rejected",
    "diagnostics",
    "unresolved",
)


def resolve_nested_object_graph(input_data: dict[str, Any]) -> dict[str, Any]:
    """Resolve nested object calls from language-neutral facts.

    Parameters
    ----------
    input_data:
        JSON-compatible dictionary containing extracted facts. The resolver does
        not parse source files; it consumes normalized facts and returns another
        JSON-compatible dictionary.
    """

    ok, errors = validate_input(input_data)
    if not ok:
        return {"status": "error", "errors": errors}

    index = FactIndex.build(input_data)
    chain_resolver = ObjectBindingResolver(index)
    edges: list[Edge] = []
    unresolved: list[dict[str, Any]] = []

    for call in input_data.get("calls", []):
        if not isinstance(call, dict):
            unresolved.append({"reason": "call fact is not a dict", "call": call})
            continue
        scope = str(call.get("scope") or "")
        method_name = call.get("method")
        receiver_chain = call.get("receiver_chain")
        if not scope or not method_name or receiver_chain is None:
            unresolved.append(
                {"reason": "call requires scope, receiver_chain and method", "call": call}
            )
            continue

        resolution = chain_resolver.resolve_receiver(
            scope=scope,
            receiver_chain=receiver_chain,
            call_result=bool(call.get("call_result")),
            provider_call=bool(call.get("provider_call")),
        )
        method_name = str(method_name)
        receiver_path = normalize_path(receiver_chain)
        chain_length = sum(1 for part in receiver_path if not isinstance(part, tuple))

        candidate_types = sorted(resolution.types)
        matched_types = [class_id for class_id in candidate_types if index.class_has_method(class_id, method_name)]
        missing_types = [class_id for class_id in candidate_types if class_id not in matched_types]

        if not candidate_types:
            unresolved.append(
                {
                    "scope": scope,
                    "receiver_chain": path_to_string(receiver_path),
                    "method": method_name,
                    "reason": "receiver type unresolved",
                    "evidence": resolution.evidence,
                    "warnings": resolution.warnings,
                    "status": resolution.status,
                }
            )
            continue

        if not matched_types:
            unresolved.append(
                {
                    "scope": scope,
                    "receiver_chain": path_to_string(receiver_path),
                    "method": method_name,
                    "candidate_types": candidate_types,
                    "reason": "method missing on resolved receiver type",
                    "evidence": resolution.evidence
                    + [f"method lookup failed: {class_id}.{method_name}" for class_id in candidate_types],
                    "warnings": resolution.warnings + ["method missing"],
                    "status": "unresolved",
                }
            )
            continue

        if missing_types:
            index.diagnostics.append(
                {
                    "code": "partial_method_lookup",
                    "message": f"Some resolved receiver types do not expose method {method_name}",
                    "scope": scope,
                    "receiver_chain": path_to_string(receiver_path),
                    "missing_types": missing_types,
                    "matched_types": matched_types,
                }
            )

        for target_type in matched_types:
            method_exists = index.class_has_method(target_type, method_name)
            status, confidence, warnings = status_for_resolution(
                resolution=resolution,
                matched_candidate_count=len(matched_types),
                method_exists=method_exists,
                chain_length=chain_length,
            )
            to_id = f"{target_type}.{method_name}"
            evidence = list(resolution.evidence)
            evidence.append(f"method lookup: {to_id}")
            if not evidence:
                evidence.append(f"resolved call: {scope} -> {to_id}")
            edges.append(
                Edge(
                    from_id=scope,
                    to_id=to_id,
                    confidence=confidence,
                    status=status,
                    evidence=evidence,
                    warnings=warnings,
                )
            )

    buckets = split_edges(edges)
    edge_dicts = [edge.to_dict() for edge in edges]
    output: dict[str, Any] = {key: [] for key in _OUTPUT_LIST_KEYS}
    output.update(
        {
            "status": "ok",
            "bindings": index.all_bindings_as_dicts(),
            "resolved_calls": edge_dicts,
            "edges": edge_dicts,
            "diagnostics": index.diagnostics,
            "unresolved": unresolved,
        }
    )
    output.update(buckets)
    return output
