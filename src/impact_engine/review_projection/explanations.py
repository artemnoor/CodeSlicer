"""Human-readable, evidence-backed explanations."""
from __future__ import annotations

from typing import Any

from .contracts import ReviewCandidate, ReviewChain, ReviewEvidence


def build_chain(chain_id: str, labels: list[str], evidence: list[ReviewEvidence], confidence: str, status: str, impact_class: str) -> ReviewChain:
    if len(labels) >= 3:
        summary = f"{labels[-1]} is affected through {labels[-2]}, which is connected to the changed {labels[0]}."
    elif len(labels) == 2:
        summary = f"{labels[-1]} is directly connected to changed {labels[0]}."
    else:
        summary = "no_cross_file_impact_proven"
    return ReviewChain(
        id=chain_id,
        nodes=tuple(labels),
        evidence_ids=tuple(item.id for item in evidence),
        status=status,
        confidence=confidence,
        summary=summary,
        impact_class=impact_class,
    )


def explanation(candidate: ReviewCandidate, chain: ReviewChain | None, evidence: list[ReviewEvidence]) -> dict[str, Any]:
    if chain is None:
        return {
            "summary": "no_cross_file_impact_proven" if candidate.impact_class != "direct" else "changed symbol is directly present in the diff",
            "impact_class": candidate.impact_class,
            "confidence": candidate.confidence,
            "evidence": [item.to_dict() for item in evidence],
            "chain": list(chain.nodes) if chain else [candidate.symbol],
        }
    return {
        "summary": chain.summary,
        "impact_class": candidate.impact_class,
        "confidence": candidate.confidence,
        "evidence": [item.to_dict() for item in evidence],
        "chain": list(chain.nodes),
    }
