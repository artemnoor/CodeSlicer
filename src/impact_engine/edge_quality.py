"""Edge quality classification for impact output discipline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


QUALITY_ORDER = {
    "rejected": 0,
    "suspicious": 1,
    "weak": 2,
    "likely": 3,
    "confirmed": 4,
}

ACTIVE_IMPACT_QUALITIES = {"confirmed", "likely", "weak"}


@dataclass
class EdgeQuality:
    status: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
        }


def classify_edge_quality(edge: Any) -> EdgeQuality:
    """Classify one graph edge into confirmed/likely/weak/suspicious/rejected.

    The classifier is intentionally conservative. Explicit resolver status wins
    first, then confidence/source/evidence signals refine the result.
    """

    props = getattr(edge, "properties", {}) or {}
    confidence = float(getattr(edge, "confidence", 0.0) or 0.0)
    explicit = str(props.get("status") or "").lower()
    warnings = [str(item) for item in props.get("warnings", []) or []]
    reasons: list[str] = []

    if explicit in QUALITY_ORDER:
        status = explicit
        reasons.append(f"explicit resolver status: {explicit}")
    elif confidence >= 0.84:
        status = "confirmed"
        reasons.append("confidence >= 0.84")
    elif confidence >= 0.70:
        status = "likely"
        reasons.append("confidence >= 0.70")
    elif confidence >= 0.55:
        status = "weak"
        reasons.append("confidence >= 0.55")
    else:
        status = "suspicious"
        reasons.append("confidence < 0.55")

    if not getattr(edge, "evidence", None):
        status = _downgrade(status, "weak")
        warnings.append("edge has no evidence")
        reasons.append("downgraded because evidence is missing")

    warning_text = " ".join(warnings).lower()
    suspicious_markers = (
        "method mismatch",
        "prefix differs",
        "suffix",
        "ambiguous",
        "unresolved",
        "name similarity",
        "missing receiver",
        "route/module mismatch",
        "dangling",
        "missing endpoint",
    )
    if any(marker in warning_text for marker in suspicious_markers):
        status = _downgrade(status, "suspicious")
        reasons.append("downgraded by false-positive guard warning")

    if confidence <= 0.0 or explicit == "rejected":
        status = "rejected"
        reasons.append("rejected or zero confidence")

    if status == "confirmed" and confidence < 0.84:
        status = "likely"
        reasons.append("confirmed requires confidence >= 0.84")

    return EdgeQuality(status=status, confidence=confidence, reasons=reasons, warnings=warnings)


def edge_is_active_for_impact(edge: Any) -> bool:
    return classify_edge_quality(edge).status in ACTIVE_IMPACT_QUALITIES


def bucket_edge_dicts(edge_dicts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets = {name: [] for name in ["confirmed", "likely", "weak", "suspicious", "rejected", "not_resolved"]}
    for item in edge_dicts:
        quality = item.get("quality") or {}
        status = str(quality.get("status") or item.get("properties", {}).get("status") or "weak")
        if status not in buckets:
            status = "suspicious"
        buckets[status].append(item)
    return buckets


def _downgrade(status: str, cap: str) -> str:
    return status if QUALITY_ORDER.get(status, 0) <= QUALITY_ORDER[cap] else cap
