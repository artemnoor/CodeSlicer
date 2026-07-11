"""Adapter from ai_library_researcher_pro drafts to Impact Engine support packs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from impact_engine.support_packs.schema import validate_support_pack_dict


def adapt_researcher_pro_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """Convert researcher-pro draft schema into the current SupportPack schema."""
    library = str(draft.get("library") or "").strip()
    ecosystem = str(draft.get("ecosystem") or draft.get("language") or "").strip().lower()
    version_range = str(draft.get("version_range") or "*")
    confidence = float(draft.get("confidence") or 0.0)
    diagnostics = list(draft.get("diagnostics") or [])

    sources = [_adapt_source(source) for source in draft.get("evidence_sources", []) if isinstance(source, dict)]
    rules = [_adapt_rule(rule, confidence) for rule in draft.get("rules", []) if isinstance(rule, dict)]

    pack = {
        "id": f"{ecosystem}_{library}_researcher_pro" if ecosystem and library else "",
        "library": library,
        "version_range": version_range,
        "language": ecosystem,
        "ecosystem": ecosystem,
        "status": "experimental",
        "coverage_limitations": diagnostics,
        "examples": [],
        "validation_requirements": {
            "generated_by": draft.get("generated_by", {}),
            "source_schema_version": draft.get("schema_version"),
            "requires_review": confidence < 0.8 or bool(diagnostics),
        },
        "sources": sources,
        "patterns": [_rule_to_pattern(rule) for rule in draft.get("rules", []) if isinstance(rule, dict)],
        "edge_rules": rules,
        "confidence_rules": [
            {
                "id": "researcher_pro_overall_confidence",
                "confidence": confidence,
                "reason": "Overall confidence reported by ai_library_researcher_pro",
            }
        ],
        "playground_cases": [],
    }

    errors = validate_support_pack_dict(pack)
    if errors:
        raise ValueError("Adapted support pack is invalid: " + "; ".join(errors))
    return pack


def adapt_researcher_pro_draft_file(path: str | Path) -> dict[str, Any]:
    import json

    draft = json.loads(Path(path).read_text(encoding="utf-8"))
    return adapt_researcher_pro_draft(draft)


def _adapt_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": str(source.get("source_type") or source.get("type") or "research"),
        "url": str(source.get("url") or ""),
        "title": source.get("title", ""),
        "bytes_read": source.get("bytes_read", 0),
        "error": source.get("error"),
    }


def _adapt_rule(rule: dict[str, Any], default_confidence: float) -> dict[str, Any]:
    rule_type = str(rule.get("type") or "research_rule")
    rule_id = str(rule.get("id") or f"researcher_pro_{rule_type}")
    confidence = float(rule.get("confidence", default_confidence))
    match = {
        "researcher_rule_type": rule_type,
        "library_pattern": {k: v for k, v in rule.items() if k not in {"id", "type", "confidence", "evidence", "diagnostics"}},
    }
    emit = {
        "kind": _emit_kind_for_rule(rule_type),
        "source": "SUPPORT_PACK",
        "confidence": confidence,
        "description": f"Researcher-pro inferred {rule_type} rule",
        "evidence_ref": _first_evidence_url(rule),
    }
    return {
        "id": rule_id,
        "type": rule_type,
        "match": match,
        "emit": emit,
        "researcher_evidence": list(rule.get("evidence") or []),
        "diagnostics": list(rule.get("diagnostics") or []),
    }


def _rule_to_pattern(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(rule.get("id") or ""),
        "type": str(rule.get("type") or ""),
        "confidence": float(rule.get("confidence", 0.0) or 0.0),
        "config": {k: v for k, v in rule.items() if k not in {"id", "type", "confidence", "evidence", "diagnostics"}},
        "evidence": list(rule.get("evidence") or []),
        "diagnostics": list(rule.get("diagnostics") or []),
    }


def _emit_kind_for_rule(rule_type: str) -> str:
    if rule_type in {"object_graph", "decorator_entrypoint", "route_pattern"}:
        return "ROUTE_HANDLES"
    if rule_type in {"endpoint_sink", "wrapper_function"}:
        return "DEPENDS_ON"
    if rule_type in {"provider_factory", "constructor_injection", "method_call_alias"}:
        return "DEPENDS_ON"
    if rule_type in {"test_target_pattern"}:
        return "TESTS"
    if rule_type in {"component_usage"}:
        return "USES_COMPONENT"
    return "DEPENDS_ON"


def _first_evidence_url(rule: dict[str, Any]) -> str:
    evidence = rule.get("evidence") or []
    if evidence and isinstance(evidence[0], dict):
        return str(evidence[0].get("source_url") or evidence[0].get("url") or "")
    return "researcher_pro"
