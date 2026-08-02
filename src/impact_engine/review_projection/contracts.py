"""Stable JSON contracts for the compact review projection."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReviewEvidence:
    id: str
    file: str | None = None
    line: int | None = None
    kind: str = "UNKNOWN"
    description: str = ""
    source: str | None = None
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class ReviewChain:
    id: str
    nodes: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    status: str
    confidence: str
    summary: str
    impact_class: str = "transitive"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "nodes": list(self.nodes), "evidence_ids": list(self.evidence_ids)}


@dataclass(frozen=True)
class ReviewRank:
    score: float
    factors: tuple[str, ...] = ()
    breakdown: dict[str, float] = field(default_factory=dict)
    policy_version: str = "review-ranking/v1"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "factors": list(self.factors)}


@dataclass(frozen=True)
class ReviewCandidate:
    entity_id: str
    kind: str
    file: str | None
    symbol: str
    impact_class: str
    confidence: str
    rank: ReviewRank
    evidence_ids: tuple[str, ...] = ()
    why_affected: dict[str, Any] = field(default_factory=dict)
    chain_ids: tuple[str, ...] = ()
    suppression_reason: str | None = None
    cluster: str | None = None
    discovery_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "kind": self.kind,
            "file": self.file,
            "symbol": self.symbol,
            "impact_class": self.impact_class,
            "confidence": self.confidence,
            "rank": self.rank.to_dict(),
            "rank_score": self.rank.score,
            "score_factors": list(self.rank.factors),
            "score_breakdown": dict(self.rank.breakdown),
            "evidence_ids": list(self.evidence_ids),
            "why_affected": self.why_affected,
            "chain_ids": list(self.chain_ids),
            "suppression_reason": self.suppression_reason,
            "cluster": self.cluster,
            "discovery_reason": self.discovery_reason,
        }


@dataclass(frozen=True)
class TestRecommendation:
    file: str | None
    symbol: str
    category: str
    score: float
    confidence: str
    evidence_ids: tuple[str, ...] = ()
    reason: str = ""
    command: Any = None
    fallback_status: str = "primary"

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "symbol": self.symbol,
            "node": self.symbol,
            "category": self.category,
            "score": self.score,
            "confidence": self.confidence,
            "evidence_ids": list(self.evidence_ids),
            "reason": self.reason,
            "command": self.command,
            "fallback_status": self.fallback_status,
        }


@dataclass(frozen=True)
class ReviewProjection:
    changed_entities: tuple[str, ...]
    candidates: tuple[ReviewCandidate, ...]
    evidence: tuple[ReviewEvidence, ...]
    chains: tuple[ReviewChain, ...]
    tests: tuple[TestRecommendation, ...]
    risk: dict[str, Any]
    possible_candidates: tuple[ReviewCandidate, ...] = ()
    suppressed_candidates: tuple[ReviewCandidate, ...] = ()
    coverage: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    policy_version: str = "review-ranking/v1"
    test_selection_policy_version: str = "review-tests/v1"
    schema_version: str = "ReviewProjection/v1"
    mode: str = "concise"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "changed_entities": list(self.changed_entities),
            "candidates": [item.to_dict() for item in self.candidates],
            "possible_candidates": [item.to_dict() for item in self.possible_candidates],
            "suppressed_candidates": [item.to_dict() for item in self.suppressed_candidates],
            "evidence": [item.to_dict() for item in self.evidence],
            "chains": [item.to_dict() for item in self.chains],
            "tests": [item.to_dict() for item in self.tests],
            "risk": self.risk,
            "coverage": list(self.coverage),
            "warnings": list(self.warnings),
            "policy_version": self.policy_version,
            "test_selection_policy_version": self.test_selection_policy_version,
        }
