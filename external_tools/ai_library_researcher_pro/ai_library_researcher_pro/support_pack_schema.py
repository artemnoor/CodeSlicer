from __future__ import annotations

from typing import Any, Dict, List

SUPPORTED_RULE_TYPES = {
    "decorator_entrypoint",
    "object_graph",
    "endpoint_sink",
    "wrapper_function",
    "provider_factory",
    "constructor_injection",
    "method_call_alias",
    "test_target_pattern",
    "component_usage",
    "route_pattern",
}

REQUIRED_PACK_FIELDS = [
    "library",
    "ecosystem",
    "version_range",
    "imports",
    "rules",
    "evidence_sources",
    "generated_by",
    "confidence",
    "diagnostics",
]

REQUIRED_RULE_FIELDS = ["id", "type", "confidence", "evidence"]

SCHEMA_VERSION = "impact-engine-style-support-pack-draft/v1"


def empty_support_pack(library: str, ecosystem: str, version_range: str = "*") -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "library": library,
        "ecosystem": ecosystem,
        "version_range": version_range,
        "imports": [],
        "rules": [],
        "evidence_sources": [],
        "generated_by": {
            "tool": "ai_library_researcher_pro",
            "mode": "heuristic",
            "version": "0.1.0",
        },
        "confidence": 0.0,
        "diagnostics": [],
    }


def rule_template(rule_id: str, rule_type: str, confidence: float, evidence: List[Dict[str, str]], **config: Any) -> Dict[str, Any]:
    rule = {
        "id": rule_id,
        "type": rule_type,
        "confidence": round(float(confidence), 2),
        "evidence": evidence,
    }
    rule.update(config)
    return rule
