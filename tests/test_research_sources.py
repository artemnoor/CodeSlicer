import pytest
from impact_engine.research.sources import get_candidate_urls


def test_get_candidate_urls_python():
    urls = get_candidate_urls("requests", "python")
    assert "https://pypi.org/project/requests/" in urls["registry_urls"]
    assert any("github.com" in u for u in urls["github_urls"])
    assert any("requests.readthedocs.io" in u for u in urls["docs_urls"])


def test_get_candidate_urls_npm():
    urls = get_candidate_urls("lodash", "javascript")
    assert "https://www.npmjs.com/package/lodash" in urls["registry_urls"]


def test_get_candidate_urls_go():
    urls = get_candidate_urls("github.com/gin-gonic/gin", "go")
    assert "https://pkg.go.dev/github.com/gin-gonic/gin" in urls["registry_urls"]


def test_fastapi_sources_are_primary_and_typed():
    urls = get_candidate_urls("fastapi", "python")
    assert "https://fastapi.tiangolo.com/tutorial/dependencies/" in urls["docs_urls"]
    assert "https://github.com/fastapi/fastapi" in urls["github_urls"]
    assert not any("github.com/search" in u for u in urls["github_urls"])
    assert {item["source_type"] for item in urls["source_plan"]} == {
        "official_docs", "official_repository", "package_registry"
    }
