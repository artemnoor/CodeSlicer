"""Confidence/status classification and false-positive guards."""

from __future__ import annotations

from .models import EdgeStatus


def clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, value))


def status_for_confidence(confidence: float, *, suspicious: bool = False, rejected: bool = False) -> EdgeStatus:
    if rejected:
        return "rejected"
    if suspicious:
        return "suspicious"
    confidence = clamp_confidence(confidence)
    if confidence >= 0.84:
        return "confirmed"
    if confidence >= 0.75:
        return "likely"
    if confidence >= 0.55:
        return "weak"
    return "suspicious"


def combine_confidence(*values: float) -> float:
    if not values:
        return 0.0
    result = 1.0
    for value in values:
        result = min(result, value)
    return clamp_confidence(result)


def frontend_http_confidence(wrapper_confidence: float, eval_confidence: float, *, has_dynamic_param: bool, unresolved: bool) -> tuple[float, EdgeStatus, list[str]]:
    warnings: list[str] = []
    confidence = combine_confidence(wrapper_confidence, eval_confidence)
    if has_dynamic_param:
        confidence = min(confidence, 0.90)
    if unresolved:
        confidence = min(confidence, 0.62)
        warnings.append("path contains unresolved expression")
    status = status_for_confidence(confidence)
    return confidence, status, warnings


def backend_match_confidence(frontend_conf: float, backend_conf: float, *, multiple: bool = False) -> tuple[float, EdgeStatus, list[str]]:
    warnings: list[str] = []
    confidence = combine_confidence(frontend_conf, backend_conf, 0.95)
    if multiple:
        confidence = min(confidence, 0.78)
        warnings.append("multiple backend routes match this frontend endpoint")
    return confidence, status_for_confidence(confidence), warnings
