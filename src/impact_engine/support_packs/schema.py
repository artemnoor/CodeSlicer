"""Support pack schema validation and models. Stage 8 complete."""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


SUPPORT_PACK_TRUST_LEVELS = {
    "draft",
    "staged",
    "experimental",
    "verified_on_fixture",
    "verified_on_real_project",
    "trusted",
}

SUPPORT_PACK_CONFIDENCE_CAPS = {
    "experimental": 0.65,
    "verified_on_fixture": 0.80,
    "verified_on_real_project": 0.90,
    "trusted": 0.95,
}

SUPPORT_PACK_INACTIVE_TRUST_LEVELS = {"draft", "staged"}

SUPPORT_PACK_STATUSES = {
    *SUPPORT_PACK_TRUST_LEVELS,
    # Legacy statuses kept for backward compatibility with existing packs.
    "verified",
    "official",
}


def normalize_support_pack_trust_level(status: str | None = None, trust_level: str | None = None) -> str:
    value = (trust_level or status or "").strip()
    if value == "verified":
        return "verified_on_real_project"
    if value == "official":
        return "trusted"
    if value in SUPPORT_PACK_TRUST_LEVELS:
        return value
    if not value:
        return "experimental"
    return value


def is_support_pack_active(status: str | None = None, trust_level: str | None = None) -> bool:
    return normalize_support_pack_trust_level(status, trust_level) not in SUPPORT_PACK_INACTIVE_TRUST_LEVELS


def cap_support_pack_confidence(confidence: float, status: str | None = None, trust_level: str | None = None) -> float:
    effective = normalize_support_pack_trust_level(status, trust_level)
    cap = SUPPORT_PACK_CONFIDENCE_CAPS.get(effective)
    if cap is None:
        return float(confidence)
    return min(float(confidence), cap)


@dataclass
class SupportPack:
    library: str
    version_range: str
    language: str
    id: str = ""
    ecosystem: str = ""
    status: str = "experimental"
    trust_level: str = ""
    coverage_limitations: Any = field(default_factory=list)
    examples: Any = field(default_factory=list)
    validation_requirements: Any = field(default_factory=dict)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    patterns: List[Dict[str, Any]] = field(default_factory=list)
    edge_rules: List[Dict[str, Any]] = field(default_factory=list)
    confidence_rules: List[Dict[str, Any]] = field(default_factory=list)
    playground_cases: List[Dict[str, Any]] = field(default_factory=list)
    supported_versions: List[str] = field(default_factory=list)
    rules: List[Dict[str, Any]] = field(default_factory=list)
    resolver_hooks: List[str] = field(default_factory=list)
    evidence_requirements: Dict[str, Any] = field(default_factory=dict)
    confidence_caps: Dict[str, float] = field(default_factory=dict)
    fixtures: List[Dict[str, Any]] = field(default_factory=list)
    negative_cases: List[Dict[str, Any]] = field(default_factory=list)
    mutation_scenarios: List[Dict[str, Any]] = field(default_factory=list)


def validate_support_pack_dict(data: dict) -> List[str]:
    errors = []
    
    if not isinstance(data, dict):
        return ["Data must be a dictionary"]

    # 1. Required string fields
    string_fields = ["library", "version_range", "language", "status"]
    
    for field_name in string_fields:
        if field_name not in data:
            errors.append(f"missing field: {field_name}")
        else:
            val = data[field_name]
            if not isinstance(val, str):
                errors.append(f"field '{field_name}' must be a string")
            elif val.strip() == "":
                errors.append(f"field '{field_name}' cannot be empty or blank")
                
    if "status" in data:
        status_val = data["status"]
        if isinstance(status_val, str) and status_val not in SUPPORT_PACK_STATUSES:
            allowed = ", ".join(sorted(SUPPORT_PACK_STATUSES))
            errors.append(f"status must be one of {allowed}")

    if "trust_level" in data:
        trust_val = data["trust_level"]
        if not isinstance(trust_val, str):
            errors.append("field 'trust_level' must be a string")
        elif trust_val and trust_val not in SUPPORT_PACK_STATUSES:
            allowed = ", ".join(sorted(SUPPORT_PACK_STATUSES))
            errors.append(f"trust_level must be one of {allowed}")

    # 2. Required list/dict fields
    required_list_fields = ["sources", "patterns", "edge_rules", "confidence_rules", "playground_cases"]
    for field_name in required_list_fields:
        if field_name not in data:
            errors.append(f"missing field: {field_name}")
        else:
            if not isinstance(data[field_name], list):
                errors.append(f"field '{field_name}' must be a list")

    # 3. Optional top-level fields
    if "id" in data:
        if not isinstance(data["id"], str):
            errors.append("field 'id' must be a string")

    if "ecosystem" in data:
        if not isinstance(data["ecosystem"], str):
            errors.append("field 'ecosystem' must be a string")

    if "coverage_limitations" in data:
        if not isinstance(data["coverage_limitations"], (list, dict)):
            errors.append("field 'coverage_limitations' must be a list or object")

    if "examples" in data:
        if not isinstance(data["examples"], list):
            errors.append("field 'examples' must be a list")

    optional_types = {
        "supported_versions": list,
        "rules": list,
        "resolver_hooks": list,
        "evidence_requirements": (dict, list),
        "confidence_caps": dict,
        "fixtures": list,
        "negative_cases": list,
        "mutation_scenarios": list,
    }
    for field_name, expected_type in optional_types.items():
        if field_name in data and not isinstance(data[field_name], expected_type):
            errors.append(f"field '{field_name}' has invalid type")
    if isinstance(data.get("confidence_caps"), dict):
        for key, value in data["confidence_caps"].items():
            try:
                if not 0.0 <= float(value) <= 1.0:
                    errors.append(f"confidence_caps['{key}'] must be between 0.0 and 1.0")
            except (TypeError, ValueError):
                errors.append(f"confidence_caps['{key}'] must be numeric")

    if "validation_requirements" in data:
        if not isinstance(data["validation_requirements"], (list, dict)):
            errors.append("field 'validation_requirements' must be a list or object")

    if "sources" in data and isinstance(data["sources"], list):
        for idx, source in enumerate(data["sources"]):
            if not isinstance(source, dict):
                errors.append(f"sources[{idx}] must be a dictionary")
                continue
            if "type" not in source:
                errors.append(f"sources[{idx}] missing 'type'")
            if "url" not in source:
                errors.append(f"sources[{idx}] missing 'url'")

    # 4. Rules list validation
    if "edge_rules" in data and isinstance(data["edge_rules"], list):
        for idx, rule in enumerate(data["edge_rules"]):
            if not isinstance(rule, dict):
                errors.append(f"edge_rules[{idx}] must be a dictionary")
                continue
            rule_id = rule.get("id")
            if not rule_id:
                errors.append(f"edge_rules[{idx}] missing 'id'")
            
            # Match is required
            match = rule.get("match")
            if not isinstance(match, dict):
                errors.append(f"Rule '{rule_id or idx}' 'match' must be a dictionary")
            elif not match:
                errors.append(f"Rule '{rule_id or idx}' 'match' cannot be empty")
            
            # Emit is required
            emit = rule.get("emit")
            if not isinstance(emit, dict):
                errors.append(f"Rule '{rule_id or idx}' 'emit' must be a dictionary")
            elif not emit:
                errors.append(f"Rule '{rule_id or idx}' 'emit' cannot be empty")
            else:
                emit_kind = emit.get("kind")
                if not emit_kind:
                    errors.append(f"Rule '{rule_id or idx}' emit missing 'kind'")
                
                emit_source = emit.get("source")
                if emit_source and emit_source not in {"SUPPORT_PACK", "EXTERNAL_TOOL", "RUNTIME_CONFIRMED", "INFERRED"}:
                    errors.append(f"Rule '{rule_id or idx}' emit source must be one of: SUPPORT_PACK, EXTERNAL_TOOL, RUNTIME_CONFIRMED, INFERRED")
                    
                confidence = emit.get("confidence")
                if confidence is not None:
                    try:
                        c_val = float(confidence)
                        if not (0.0 <= c_val <= 1.0):
                            errors.append(f"Rule '{rule_id or idx}' emit confidence must be between 0.0 and 1.0")
                    except ValueError:
                        errors.append(f"Rule '{rule_id or idx}' emit confidence must be a number")
                        
                if not (emit.get("evidence_template") or emit.get("evidence_ref") or emit.get("description")):
                    errors.append(f"Rule '{rule_id or idx}' emit missing evidence metadata")

    return errors


def support_pack_from_dict(data: dict) -> SupportPack:
    errors = validate_support_pack_dict(data)
    if errors:
        raise ValueError(f"Invalid support pack: {', '.join(errors)}")
        
    return SupportPack(
        library=data["library"],
        version_range=data["version_range"],
        language=data["language"],
        id=data.get("id", ""),
        ecosystem=data.get("ecosystem", ""),
        status=data.get("status", "experimental"),
        trust_level=data.get("trust_level", ""),
        coverage_limitations=data.get("coverage_limitations", []),
        examples=data.get("examples", []),
        validation_requirements=data.get("validation_requirements", {}),
        sources=data.get("sources", []),
        patterns=data.get("patterns", []),
        edge_rules=data.get("edge_rules", []),
        confidence_rules=data.get("confidence_rules", []),
        playground_cases=data.get("playground_cases", []),
        supported_versions=data.get("supported_versions", []),
        rules=data.get("rules", []),
        resolver_hooks=data.get("resolver_hooks", []),
        evidence_requirements=data.get("evidence_requirements", {}),
        confidence_caps=data.get("confidence_caps", {}),
        fixtures=data.get("fixtures", []),
        negative_cases=data.get("negative_cases", []),
        mutation_scenarios=data.get("mutation_scenarios", [])
    )


def support_pack_to_dict(pack: SupportPack) -> dict:
    return asdict(pack)
