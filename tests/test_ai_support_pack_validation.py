import pytest
from impact_engine.research.validation import validate_ai_generated_support_pack


@pytest.fixture
def sample_input_pack():
    return {
        "research_request": {
            "library_name": "requests",
            "ecosystem": "python"
        },
        "fetched_pages": [
            {"url": "https://requests.readthedocs.io", "text_excerpt": "docs content"}
        ],
        "detected_project_usage_examples": [
            "import requests",
            "requests.get('https://example.com')"
        ]
    }


def test_validation_success(sample_input_pack):
    pack = {
        "library": "requests",
        "version_range": ">=2.0.0",
        "language": "python",
        "status": "experimental",
        "sources": [{"type": "documentation", "url": "https://requests.readthedocs.io"}],
        "patterns": [],
        "edge_rules": [
            {
                "id": "get-rule",
                "type": "standard",
                "match": {
                    "call_name": "requests.get"
                },
                "emit": {
                    "to": "HTTP_CLIENT",
                    "kind": "CALLS",
                    "confidence": 0.85,
                    "evidence_ref": "https://requests.readthedocs.io"
                }
            }
        ],
        "confidence_rules": [],
        "playground_cases": []
    }
    
    res = validate_ai_generated_support_pack(pack, sample_input_pack)
    assert res["valid"] is True
    assert len(res["errors"]) == 0


def test_validation_missing_required_fields(sample_input_pack):
    pack = {
        "library": "requests",
        "version_range": ">=2.0.0",
        "language": "python"
        # missing status, sources, patterns, edge_rules, etc.
    }
    res = validate_ai_generated_support_pack(pack, sample_input_pack)
    assert res["valid"] is False
    assert any("missing field" in err for err in res["errors"])


def test_validation_library_mismatch(sample_input_pack):
    pack = {
        "library": "wrong-library",
        "version_range": ">=2.0.0",
        "language": "python",
        "status": "experimental",
        "sources": [],
        "patterns": [],
        "edge_rules": [],
        "confidence_rules": [],
        "playground_cases": []
    }
    res = validate_ai_generated_support_pack(pack, sample_input_pack)
    assert res["valid"] is False
    assert any("does not match requested" in err for err in res["errors"])


def test_validation_missing_evidence_ref(sample_input_pack):
    pack = {
        "library": "requests",
        "version_range": ">=2.0.0",
        "language": "python",
        "status": "experimental",
        "sources": [],
        "patterns": [],
        "edge_rules": [
            {
                "id": "get-rule",
                "type": "standard",
                "match": {
                    "call_name": "requests.get"
                },
                "emit": {
                    "to": "HTTP_CLIENT",
                    "kind": "CALLS",
                    "confidence": 0.85
                }
            }
        ],
        "confidence_rules": [],
        "playground_cases": []
    }
    res = validate_ai_generated_support_pack(pack, sample_input_pack)
    assert res["valid"] is False
    assert any("missing required 'evidence_ref'" in err for err in res["errors"])
