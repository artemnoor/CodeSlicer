from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Set

from .models import ValidationResult
from .support_pack_schema import REQUIRED_PACK_FIELDS, REQUIRED_RULE_FIELDS, SUPPORTED_RULE_TYPES


class SupportPackValidator:
    def validate(self, pack: Dict[str, Any]) -> ValidationResult:
        errors: List[str] = []
        warnings: List[str] = []

        for field in REQUIRED_PACK_FIELDS:
            if field not in pack:
                errors.append(f"missing required field: {field}")

        library = pack.get("library")
        ecosystem = pack.get("ecosystem")
        if not isinstance(library, str) or not library.strip():
            errors.append("library must be a non-empty string")
        if not isinstance(ecosystem, str) or not ecosystem.strip():
            errors.append("ecosystem must be a non-empty string")
        _check_confidence(pack.get("confidence"), "pack.confidence", errors)

        try:
            json.dumps(pack, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            errors.append(f"pack is not deterministic JSON serializable: {exc}")

        evidence_sources = pack.get("evidence_sources", [])
        if not isinstance(evidence_sources, list):
            errors.append("evidence_sources must be a list")
            evidence_urls: Set[str] = set()
        else:
            evidence_urls = {str(src.get("url", "")) for src in evidence_sources if isinstance(src, dict)}
            if not evidence_urls:
                warnings.append("no evidence source URLs recorded")

        rules = pack.get("rules", [])
        checked_rules = 0
        if not isinstance(rules, list):
            errors.append("rules must be a list")
            rules = []
        for index, rule in enumerate(rules):
            checked_rules += 1
            if not isinstance(rule, dict):
                errors.append(f"rule[{index}] must be an object")
                continue
            for field in REQUIRED_RULE_FIELDS:
                if field not in rule:
                    errors.append(f"rule[{index}] missing required field: {field}")
            rule_id = rule.get("id")
            if not isinstance(rule_id, str) or not rule_id.strip():
                errors.append(f"rule[{index}] id must be a non-empty string")
            rule_type = rule.get("type")
            if rule_type not in SUPPORTED_RULE_TYPES:
                errors.append(f"rule[{index}] unknown rule type: {rule_type}")
            _check_confidence(rule.get("confidence"), f"rule[{index}].confidence", errors)
            evidence = rule.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                errors.append(f"rule[{index}] has no evidence")
            else:
                for ev_index, ev in enumerate(evidence):
                    if not isinstance(ev, dict):
                        errors.append(f"rule[{index}].evidence[{ev_index}] must be an object")
                        continue
                    url = ev.get("source_url")
                    if not isinstance(url, str) or not url:
                        errors.append(f"rule[{index}].evidence[{ev_index}] missing source_url")
                    elif evidence_urls and url not in evidence_urls:
                        errors.append(f"rule[{index}].evidence[{ev_index}] source_url not listed in evidence_sources: {url}")
                    if not ev.get("example_id"):
                        warnings.append(f"rule[{index}].evidence[{ev_index}] has no example_id")
            if float(rule.get("confidence", 0.0) or 0.0) < 0.5:
                warnings.append(f"rule[{index}] has low confidence")
            # No empty fake rules: require at least one config field beyond generic metadata.
            config_keys = set(rule) - {"id", "type", "confidence", "evidence", "diagnostics"}
            if not config_keys:
                errors.append(f"rule[{index}] has no semantic config fields")

        if not rules:
            warnings.append("support pack contains no rules")
        if isinstance(pack.get("diagnostics", []), list) and pack.get("confidence", 0.0) and float(pack.get("confidence", 0.0)) < 0.55:
            warnings.append("pack confidence is weak; diagnostics should be reviewed")
        elif "diagnostics" in pack and not isinstance(pack.get("diagnostics"), list):
            errors.append("diagnostics must be a list")

        return ValidationResult(valid=not errors, errors=sorted(set(errors)), warnings=sorted(set(warnings)), checked_rules=checked_rules)


def _check_confidence(value: Any, label: str, errors: List[str]) -> None:
    if not isinstance(value, (int, float)):
        errors.append(f"{label} must be numeric")
        return
    number = float(value)
    if number < 0.0 or number > 1.0:
        errors.append(f"{label} must be between 0 and 1")
