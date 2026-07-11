import pytest
from impact_engine.research.input_pack import ResearchRequest, ResearchInputPack


def test_research_request_serialization():
    req = ResearchRequest(
        ecosystem="python",
        library_name="requests",
        detected_imports=["requests"],
        candidate_docs_urls=["https://requests.readthedocs.io"]
    )
    d = req.to_dict()
    assert d["ecosystem"] == "python"
    assert d["library_name"] == "requests"
    assert "created_at" in d


def test_research_input_pack_defaults():
    req = ResearchRequest(ecosystem="python", library_name="requests")
    pack = ResearchInputPack(
        research_request=req.to_dict(),
        fetched_pages=[{"url": "https://pypi.org/project/requests/", "text_excerpt": "docs content"}],
        detected_project_usage_examples=[]
    )
    d = pack.to_dict()
    assert d["research_request"]["library_name"] == "requests"
    assert len(d["fetched_pages"]) == 1
    assert "required_output_schema" in d
    assert "validation_rules" in d
    assert "source_plan" in d
    assert "source_coverage" in d
    # No synthetic examples invented
    assert d["detected_project_usage_examples"] == []
