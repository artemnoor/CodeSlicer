from impact_engine.support_packs.schema import validate_support_pack_dict


def test_support_pack_schema_minimal_valid():
    data = {
        "library": "x",
        "version_range": ">=1",
        "language": "python",
        "status": "experimental",
        "sources": [],
        "patterns": [],
        "edge_rules": [],
        "confidence_rules": [],
        "playground_cases": []
    }
    assert validate_support_pack_dict(data) == []


def test_support_pack_schema_missing_fields():
    errors = validate_support_pack_dict({})
    assert "missing field: library" in errors


def test_validate_support_pack_rejects_missing_list_fields():
    errors = validate_support_pack_dict({
        "library": "x",
        "version_range": ">=1",
        "language": "python",
        "status": "experimental",
    })
    assert any("sources" in error for error in errors)
    assert any("patterns" in error for error in errors)
    assert any("edge_rules" in error for error in errors)
    assert any("confidence_rules" in error for error in errors)
    assert any("playground_cases" in error for error in errors)


def test_support_pack_schema_accepts_trust_lifecycle_statuses():
    base = {
        "library": "x",
        "version_range": ">=1",
        "language": "python",
        "sources": [],
        "patterns": [],
        "edge_rules": [],
        "confidence_rules": [],
        "playground_cases": [],
    }
    for status in ["draft", "staged", "experimental", "verified_on_fixture", "verified_on_real_project", "trusted"]:
        data = {**base, "status": status, "trust_level": status}
        assert validate_support_pack_dict(data) == []
