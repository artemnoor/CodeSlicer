"""Deterministic support pack rule engine wrapper.

Support packs are active machine-readable rule inputs for the resolver. This
module provides the explicit architecture boundary shown in the workflow docs.
"""
from __future__ import annotations

from typing import Any

from impact_engine.models import GraphDocument
from impact_engine.support_packs.resolution import apply_support_pack_rules
from impact_engine.support_packs.schema import (
    SUPPORT_PACK_CONFIDENCE_CAPS,
    SUPPORT_PACK_INACTIVE_TRUST_LEVELS,
    normalize_support_pack_trust_level,
)


TRUST_LEVELS = {
    "draft": 0.0,
    "staged": 0.0,
    "experimental": SUPPORT_PACK_CONFIDENCE_CAPS["experimental"],
    "verified_on_fixture": SUPPORT_PACK_CONFIDENCE_CAPS["verified_on_fixture"],
    "verified_on_real_project": SUPPORT_PACK_CONFIDENCE_CAPS["verified_on_real_project"],
    "trusted": SUPPORT_PACK_CONFIDENCE_CAPS["trusted"],
}


def apply_support_pack_rule_engine(graph: GraphDocument, packs: list[Any] | None = None) -> GraphDocument:
    packs = list(packs or [])
    graph.metadata["support_pack_rule_engine"] = {
        "status": "active",
        "packs_loaded": len(packs),
        "active_packs": sum(1 for pack in packs if _is_pack_active(pack)),
        "inactive_packs": sum(1 for pack in packs if not _is_pack_active(pack)),
        "inactive_levels": sorted(SUPPORT_PACK_INACTIVE_TRUST_LEVELS),
        "confidence_caps": SUPPORT_PACK_CONFIDENCE_CAPS,
        "trust_levels": _pack_trust_summary(packs),
    }
    return apply_support_pack_rules(graph, packs)


def _get_status_and_trust(pack: Any) -> tuple[str, str]:
    if isinstance(pack, dict):
        status = pack.get("status", "")
        trust_level = pack.get("trust_level", "")
    else:
        status = getattr(pack, "status", "")
        trust_level = getattr(pack, "trust_level", "")
    return str(status or ""), str(trust_level or "")


def _is_pack_active(pack: Any) -> bool:
    status, trust_level = _get_status_and_trust(pack)
    return normalize_support_pack_trust_level(status, trust_level) not in SUPPORT_PACK_INACTIVE_TRUST_LEVELS


def _pack_trust_summary(packs: list[Any]) -> list[dict[str, Any]]:
    summary = []
    for pack in packs:
        if isinstance(pack, dict):
            library = pack.get("library", "unknown")
            language = pack.get("language") or pack.get("ecosystem") or ""
            status = pack.get("status", "")
            trust_level = pack.get("trust_level", "")
        else:
            library = getattr(pack, "library", "unknown")
            language = getattr(pack, "language", "") or getattr(pack, "ecosystem", "")
            status = getattr(pack, "status", "")
            trust_level = getattr(pack, "trust_level", "")
        effective_trust_level = normalize_support_pack_trust_level(status, trust_level)
        summary.append(
            {
                "library": library,
                "language": language,
                "status": status,
                "trust_level": effective_trust_level,
                "active": effective_trust_level not in SUPPORT_PACK_INACTIVE_TRUST_LEVELS,
                "confidence_cap": SUPPORT_PACK_CONFIDENCE_CAPS.get(effective_trust_level, 0.0),
                "trust_score": TRUST_LEVELS.get(effective_trust_level, 0.50),
            }
        )
    return summary
