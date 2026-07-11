from __future__ import annotations

import json
from pathlib import Path

from ai_library_researcher_pro.extractor import ExampleExtractor
from ai_library_researcher_pro.generator import SupportPackGenerator, build_research_input_pack
from ai_library_researcher_pro.models import FetchedPage, ResearchRequest
from ai_library_researcher_pro.validator import SupportPackValidator

ROOT = Path(__file__).resolve().parents[1]


def test_extractor_extracts_code_blocks_imports_and_decorators_from_html_and_markdown():
    html_text = (ROOT / "fixtures" / "pages" / "fastapi_fixture.html").read_text(encoding="utf-8")
    md_text = (ROOT / "fixtures" / "pages" / "react_fixture.md").read_text(encoding="utf-8")
    pages = [
        FetchedPage("local://html", "fixture", content_type="text/html", text_excerpt=html_text),
        FetchedPage("local://md", "fixture", content_type="text/markdown", text_excerpt=md_text),
    ]
    examples = ExampleExtractor().extract_many(pages)

    snippets = "\n".join(e.snippet for e in examples)
    kinds = {e.kind for e in examples}
    assert "from fastapi import APIRouter, Depends" in snippets
    assert "@router.get" in snippets
    assert "import React" in snippets
    assert "decorator_example" in kinds
    assert "endpoint_sink" in kinds
    assert "component_usage" in kinds


def test_draft_generator_creates_conservative_support_pack_from_fixtures():
    fixture_text = (ROOT / "fixtures" / "sample_project" / "docs" / "fastapi_offline.md").read_text(encoding="utf-8")
    page = FetchedPage("local://project/docs/fastapi_offline.md", "local_project_doc", title="fastapi_offline.md", content_type="text/markdown", text_excerpt=fixture_text, bytes_read=len(fixture_text))
    examples = ExampleExtractor().extract_many([page])
    request = ResearchRequest("fastapi", "python", project_path=str(ROOT / "fixtures" / "sample_project"))
    input_pack = build_research_input_pack(request, [page], examples)
    pack = SupportPackGenerator().generate_heuristic_draft(input_pack)

    assert pack["library"] == "fastapi"
    assert pack["ecosystem"] == "python"
    assert pack["confidence"] <= 0.9
    assert any(rule["type"] == "object_graph" for rule in pack["rules"])
    assert any(rule["evidence"] for rule in pack["rules"])
    assert SupportPackValidator().validate(pack).valid is True


def test_validator_rejects_missing_library():
    pack = json.loads((ROOT / "fixtures" / "good_support_pack.json").read_text(encoding="utf-8"))
    pack.pop("library")
    result = SupportPackValidator().validate(pack)
    assert not result.valid
    assert any("library" in err for err in result.errors)


def test_validator_rejects_missing_ecosystem():
    pack = json.loads((ROOT / "fixtures" / "good_support_pack.json").read_text(encoding="utf-8"))
    pack.pop("ecosystem")
    result = SupportPackValidator().validate(pack)
    assert not result.valid
    assert any("ecosystem" in err for err in result.errors)


def test_validator_rejects_invalid_confidence():
    pack = json.loads((ROOT / "fixtures" / "good_support_pack.json").read_text(encoding="utf-8"))
    pack["confidence"] = 1.5
    result = SupportPackValidator().validate(pack)
    assert not result.valid
    assert any("between 0 and 1" in err for err in result.errors)


def test_validator_rejects_rules_without_evidence():
    pack = json.loads((ROOT / "fixtures" / "good_support_pack.json").read_text(encoding="utf-8"))
    pack["rules"][0]["evidence"] = []
    result = SupportPackValidator().validate(pack)
    assert not result.valid
    assert any("no evidence" in err for err in result.errors)


def test_validator_rejects_unknown_rule_type():
    pack = json.loads((ROOT / "fixtures" / "good_support_pack.json").read_text(encoding="utf-8"))
    pack["rules"][0]["type"] = "made_up_rule"
    result = SupportPackValidator().validate(pack)
    assert not result.valid
    assert any("unknown rule type" in err for err in result.errors)


def test_validator_accepts_good_fixture_pack():
    pack = json.loads((ROOT / "fixtures" / "good_support_pack.json").read_text(encoding="utf-8"))
    result = SupportPackValidator().validate(pack)
    assert result.valid
    assert result.checked_rules == 1
