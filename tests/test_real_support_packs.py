import pytest
import json
from pathlib import Path
from impact_engine.support_packs.registry import validate_support_pack_file


def validate_resolver_rules(pack_path: Path):
    data = json.loads(pack_path.read_text(encoding="utf-8"))
    errors = []
    edge_rules = data.get("edge_rules", [])
    for rule in edge_rules:
        rule_id = rule.get("id", "default")
        rule_type = rule.get("type", "standard")
        match = rule.get("match", {})
        emit = rule.get("emit", {})
        
        if not match:
            errors.append(f"Rule {rule_id}: Missing 'match' configuration")
        if not emit:
            errors.append(f"Rule {rule_id}: Missing 'emit' configuration")
        else:
            if not emit.get("to") and rule_type not in ("decorator_entrypoint", "fastapi_router_resolver", "fastapi_depends_resolver", "dependency_injector_resolver", "react_resolver"):
                errors.append(f"Rule {rule_id}: Emit missing 'to' field")
            if not emit.get("kind"):
                errors.append(f"Rule {rule_id}: Emit missing 'kind' field")
    return errors


def test_real_support_packs_valid():
    packs_dir = Path("support_packs")
    
    # 1. fastapi
    fastapi_path = packs_dir / "python" / "fastapi" / "support_pack.json"
    assert fastapi_path.exists()
    res_fastapi = validate_support_pack_file(str(fastapi_path))
    assert res_fastapi["valid"] is True, f"FastAPI support pack schema invalid: {res_fastapi.get('errors')}"
    rule_errors_fastapi = validate_resolver_rules(fastapi_path)
    assert not rule_errors_fastapi, f"FastAPI resolver rule errors: {rule_errors_fastapi}"
    
    # 2. dependency_injector
    di_path = packs_dir / "python" / "dependency_injector" / "support_pack.json"
    assert di_path.exists()
    res_di = validate_support_pack_file(str(di_path))
    assert res_di["valid"] is True, f"DI support pack schema invalid: {res_di.get('errors')}"
    rule_errors_di = validate_resolver_rules(di_path)
    assert not rule_errors_di, f"DI resolver rule errors: {rule_errors_di}"
    
    # 3. react
    react_path = packs_dir / "javascript" / "react" / "support_pack.json"
    assert react_path.exists()
    res_react = validate_support_pack_file(str(react_path))
    assert res_react["valid"] is True, f"React support pack schema invalid: {res_react.get('errors')}"
    rule_errors_react = validate_resolver_rules(react_path)
    assert not rule_errors_react, f"React resolver rule errors: {rule_errors_react}"
