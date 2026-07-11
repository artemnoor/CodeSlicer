"""Transparent, configurable scoring for impact explanations.

This module intentionally contains heuristics, not a learned model.  Keeping the
math here makes the values reproducible and keeps presentation code passive.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import prod
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class ImpactScoringConfig:
    """Configuration for the interpretable impact model."""

    decay: float = 0.85
    default_criticality: float = 1.0
    criticality_by_kind: Mapping[str, float] = field(default_factory=lambda: {
        "ROUTE": 1.40,
        "HTTP_ROUTE": 1.40,
        "CLASS": 1.20,
        "METHOD": 1.10,
        "FUNCTION": 1.00,
        "TEST": 0.70,
        "EXTERNAL_LIBRARY": 0.80,
    })

    def __post_init__(self) -> None:
        if not 0.0 < self.decay <= 1.0:
            raise ValueError("decay must be in (0, 1]")
        if self.default_criticality < 0.0:
            raise ValueError("default_criticality must be non-negative")

    @classmethod
    def from_dict(cls, values: Mapping[str, Any] | None) -> "ImpactScoringConfig":
        values = values or {}
        known = {"decay", "default_criticality", "criticality_by_kind"}
        unknown = set(values) - known
        if unknown:
            raise ValueError(f"Unknown scoring configuration keys: {sorted(unknown)}")
        overrides = dict(cls().criticality_by_kind)
        overrides.update(values.get("criticality_by_kind") or {})
        return cls(
            decay=float(values.get("decay", cls.decay)),
            default_criticality=float(values.get("default_criticality", cls.default_criticality)),
            criticality_by_kind=overrides,
        )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def chain_confidence(edge_confidences: Iterable[float]) -> float:
    """Return the geometric mean of edge confidence values.

    The geometric mean preserves the effect of weak evidence while avoiding the
    artificial length penalty of multiplying every edge in a long chain.
    """
    values = [_clamp(value) for value in edge_confidences]
    if not values:
        return 1.0
    return prod(values) ** (1.0 / len(values))


def impact_score(criticality: float, confidence: float, distance: int, decay: float) -> float:
    """Calculate Criticality * path confidence * Decay**distance."""
    if distance < 0:
        raise ValueError("distance must be non-negative")
    if not 0.0 < decay <= 1.0:
        raise ValueError("decay must be in (0, 1]")
    return max(0.0, float(criticality)) * _clamp(confidence) * (decay ** distance)


def criticality_for_node(node: Any, config: ImpactScoringConfig) -> float:
    properties = getattr(node, "properties", {}) or {}
    explicit = properties.get("criticality")
    if explicit is not None:
        return max(0.0, float(explicit))
    kind = str(getattr(node, "kind", "")).upper()
    return float(config.criticality_by_kind.get(kind, config.default_criticality))


def chain_status(confidence: float, *, ambiguous: bool = False, unresolved: bool = False) -> str:
    if ambiguous:
        return "Неоднозначна"
    if unresolved:
        return "Требует проверки"
    if confidence >= 0.90:
        return "Подтверждена"
    if confidence >= 0.75:
        return "Высокая вероятность"
    if confidence >= 0.55:
        return "Требует проверки"
    return "Неоднозначна"


def token_saving_report(full_tokens: int | None, selected_tokens: int | None) -> dict[str, Any]:
    """Report measured context reduction, never inventing a percentage."""
    if full_tokens is None or selected_tokens is None or full_tokens <= 0 or selected_tokens < 0:
        return {
            "status": "not_measured",
            "label": "Потенциальное сокращение передаваемого контекста",
        }
    saving = max(0.0, 1.0 - (float(selected_tokens) / float(full_tokens)))
    return {
        "status": "measured",
        "full_context_tokens": int(full_tokens),
        "selected_context_tokens": int(selected_tokens),
        "saving_ratio": saving,
        "saving_percent": round(saving * 100.0, 2),
        "formula": "TokenSaving=1-(Tokens_selected_context/Tokens_full_repository)",
    }


def scoring_explanation(config: ImpactScoringConfig) -> dict[str, str]:
    return {
        "formula": "ImpactScore(v)=Criticality(v)*Confidence(path)*Decay^distance",
        "compact": "Приоритет рассчитан по критичности, достоверности связи и расстоянию от изменения.",
        "chain_formula": "Confidence(path)=(product(Confidence(edge_i)))^(1/n)",
        "calibration_note": (
            "Текущая модель скоринга является интерпретируемой эвристикой. "
            "Коэффициенты могут калиброваться по историческим изменениям, "
            "тестовым результатам и пользовательской обратной связи."
        ),
        "decay": str(config.decay),
    }


def rank_impact_paths(
    graph: Any,
    impact_paths: Iterable[Mapping[str, Any]],
    config: ImpactScoringConfig | None = None,
) -> list[dict[str, Any]]:
    config = config or ImpactScoringConfig()
    edge_index = {edge.id: edge for edge in getattr(graph, "edges", [])}
    node_index = {node.id: node for node in getattr(graph, "nodes", [])}
    result: list[dict[str, Any]] = []
    for path in impact_paths:
        edges = [edge_index[edge_id] for edge_id in path.get("edges", []) if edge_id in edge_index]
        node = node_index.get(path.get("target"))
        confidence = chain_confidence(edge.confidence for edge in edges)
        ambiguous = any(
            str(edge.properties.get("resolution_status", "")).lower() in {"ambiguous", "unresolved"}
            or str(edge.properties.get("status", "")).lower() in {"ambiguous", "suspicious"}
            for edge in edges
        )
        unresolved = any(str(edge.properties.get("validation_status", "")).lower() in {"unresolved", "quarantined"} for edge in edges)
        distance = int(path.get("depth", len(edges)))
        criticality = criticality_for_node(node, config) if node is not None else config.default_criticality
        result.append({
            "node_id": path.get("target"),
            "distance": distance,
            "criticality": criticality,
            "path_confidence": confidence,
            "confidence_status": chain_status(confidence, ambiguous=ambiguous, unresolved=unresolved),
            "impact_score": impact_score(criticality, confidence, distance, config.decay),
            "edge_count": len(edges),
            "formula": "Criticality*Confidence(path)*Decay^distance",
        })
    return sorted(result, key=lambda item: (-item["impact_score"], str(item["node_id"])))
