from typing import Dict, Any
from impact_engine.support_packs.schema import validate_support_pack_dict

ALLOWED_RULE_TYPES = {
    "decorator_entrypoint",
    "task_entrypoint",
    "constructor_injection",
    "method_call_alias",
    "framework_route",
    "test_target_pattern",
    "standard"
}


def validate_ai_generated_support_pack(pack: Dict[str, Any], input_pack: Dict[str, Any]) -> Dict[str, Any]:
    errors = []
    
    if not isinstance(pack, dict):
        return {"valid": False, "errors": ["Support pack must be a JSON object (dictionary)"]}
        
    # Real schema validation call
    schema_errors = validate_support_pack_dict(pack)
    errors.extend(schema_errors)
    
    # Explicitly check required fields list
    required_fields = ["status", "sources", "patterns", "edge_rules", "confidence_rules", "playground_cases"]
    for rf in required_fields:
        if rf not in pack:
            errors.append(f"missing field: {rf}")
            
    req = input_pack.get("research_request", {})
    req_lib = req.get("library_name", "").lower().strip()
    req_eco = req.get("ecosystem", "").lower().strip()
    
    library = pack.get("library", "")
    language = pack.get("language", "")
    edge_rules = pack.get("edge_rules", [])
    
    if library and library.lower().strip() != req_lib:
        errors.append(f"Library '{library}' does not match requested '{req_lib}'")
        
    if language and language.lower().strip() != req_eco:
        errors.append(f"Language '{language}' does not match requested ecosystem '{req_eco}'")
        
    if not isinstance(edge_rules, list):
        return {"valid": False, "errors": errors}
        
    # Gather allowed evidence references
    fetched_urls = {p.get("url") for p in input_pack.get("fetched_pages", []) if p.get("url")}
    usage_examples = set(input_pack.get("detected_project_usage_examples", []))
    
    # 2. Rule validation
    for i, rule in enumerate(edge_rules):
        if not isinstance(rule, dict):
            errors.append(f"Rule at index {i} is not a valid JSON object")
            continue
            
        rule_id = rule.get("id")
        if not rule_id:
            errors.append(f"Rule at index {i} is missing 'id'")
            
        rule_type = rule.get("type", "standard")
        if rule_type not in ALLOWED_RULE_TYPES:
            errors.append(f"Rule '{rule_id}' has invalid type '{rule_type}'. Allowed: {sorted(list(ALLOWED_RULE_TYPES))}")
            
        match = rule.get("match", {})
        emit = rule.get("emit", {})
        
        if not isinstance(match, dict) or not match:
            errors.append(f"Rule '{rule_id}' has missing or invalid 'match' configuration")
        if not isinstance(emit, dict) or not emit:
            errors.append(f"Rule '{rule_id}' has missing or invalid 'emit' configuration")
            continue
            
        # Check evidence ref
        # Rule should point to evidence: either inside rule properties, the rule itself, or emit properties
        ev_ref = (
            rule.get("evidence_ref") or 
            emit.get("evidence_ref") or 
            rule.get("properties", {}).get("evidence_ref") or
            emit.get("properties", {}).get("evidence_ref")
        )
        
        if not ev_ref:
            errors.append(f"Rule '{rule_id}' is missing required 'evidence_ref'")
        else:
            # Check if ev_ref is in known fetched pages or matched as substring of usage examples
            is_valid_ref = (ev_ref in fetched_urls)
            if not is_valid_ref:
                # Check if it matches any usage example or matches partially
                is_valid_ref = any(ev_ref in ex or ex in ev_ref for ex in usage_examples)
            if not is_valid_ref:
                errors.append(f"Rule '{rule_id}' evidence_ref '{ev_ref}' does not point to any fetched page URL or project usage example")
                
        # Confidence check
        confidence = emit.get("confidence")
        if confidence is not None:
            try:
                conf_val = float(confidence)
                if not (0.0 <= conf_val <= 1.0):
                    errors.append(f"Rule '{rule_id}' confidence {conf_val} is out of allowed range [0.0, 1.0]")
            except ValueError:
                errors.append(f"Rule '{rule_id}' confidence must be a number, got '{confidence}'")
                
    return {
        "valid": len(errors) == 0,
        "errors": errors
    }
