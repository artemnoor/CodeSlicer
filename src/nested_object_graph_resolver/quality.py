"""Confidence and status classification for resolved call edges."""

from __future__ import annotations

from .models import Edge, PathResolution


_BUCKETS = ("confirmed", "likely", "weak", "suspicious", "rejected")


def status_for_resolution(
    *,
    resolution: PathResolution,
    matched_candidate_count: int,
    method_exists: bool,
    chain_length: int,
) -> tuple[str, float, list[str]]:
    """Return (status, adjusted_confidence, warnings)."""

    warnings = list(resolution.warnings)
    confidence = max(0.0, min(1.0, resolution.confidence))

    if resolution.rejected:
        return "rejected", min(confidence, 0.2), warnings or ["resolution rejected"]
    if not resolution.types:
        return "suspicious", min(confidence, 0.5), warnings or ["receiver type unresolved"]
    if not method_exists:
        return "suspicious", min(confidence, 0.5), warnings or ["target method missing"]
    if matched_candidate_count > 1:
        warnings.append("ambiguous receiver type: multiple candidate target classes expose this method")
        if confidence >= 0.72:
            return "likely", min(confidence, 0.74), warnings
        return "weak", min(confidence, 0.64), warnings

    # Penalize long chains lightly. The resolver remains deterministic but a
    # deeper object graph usually has more extraction uncertainty.
    if chain_length >= 4:
        confidence = min(confidence, 0.80)
    elif chain_length == 3:
        confidence = min(confidence, 0.85)
    elif chain_length == 2:
        confidence = min(confidence, 0.90)

    if confidence >= 0.78:
        return "confirmed", confidence, warnings
    if confidence >= 0.62:
        return "likely", confidence, warnings
    if confidence >= 0.40:
        return "weak", confidence, warnings
    return "suspicious", confidence, warnings


def split_edges(edges: list[Edge]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {name: [] for name in _BUCKETS}
    for edge in edges:
        status = edge.status if edge.status in buckets else "suspicious"
        item = edge.to_dict()
        buckets[status].append(item)
    return buckets
