import pytest
import json
import shutil
from pathlib import Path
from impact_engine.research.workflow import (
    init_workflow, fetch_pages, build_input_pack, validate_candidate, install_candidate, get_workflow_dir
)
from impact_engine.research.fetcher import WebFetcher, FetchResult

PROJECT_PATH = Path(__file__).parent.parent / "examples" / "golden_cases" / "python_di_basic"


@pytest.fixture(autouse=True)
def clean_research_dir():
    # Setup
    research_dir = Path(".impact_engine/research_workflows")
    if research_dir.exists():
        shutil.rmtree(research_dir)
        
    yield
    
    # Teardown
    if research_dir.exists():
        shutil.rmtree(research_dir)


class MockFetcher:
    def fetch_url(self, url: str, timeout_seconds: int = 10) -> FetchResult:
        return FetchResult(
            url=url,
            status_code=200,
            content_type="text/html",
            text_excerpt=f"Mock content of {url}"
        )

    def fetch(self, url: str) -> FetchResult:
        return self.fetch_url(url)

    def fetch_many(self, urls: list[str], max_pages: int = 5) -> list[FetchResult]:
        return [self.fetch_url(u) for u in urls[:max_pages]]


def test_research_workflow_lifecycle():
    # 1. Initialize
    wf_id = init_workflow(str(PROJECT_PATH), "pytest", "python")
    assert wf_id is not None
    
    wf_dir = get_workflow_dir(wf_id)
    assert wf_dir.exists()
    assert (wf_dir / "research_request.json").exists()
    
    # 2. Fetch pages
    fetcher = MockFetcher()
    results = fetch_pages(wf_id, fetcher=fetcher)
    assert len(results) > 0
    assert (wf_dir / "fetched_pages" / "page_0.json").exists()
    
    # 3. Build input pack (no synthetic examples)
    input_pack = build_input_pack(wf_id)
    assert (wf_dir / "ai_input.json").exists()
    assert len(input_pack["fetched_pages"]) == len(results)
    
    # 4. Valid candidate
    candidate = {
        "library": "pytest",
        "version_range": ">=7.0.0",
        "language": "python",
        "status": "experimental",
        "sources": [{"type": "documentation", "url": results[0]["url"]}],
        "patterns": [],
        "edge_rules": [
            {
                "id": "pytest-rule",
                "type": "standard",
                "match": {
                    "call_name": "pytest.main"
                },
                "emit": {
                    "to": "TEST_RUNNER",
                    "kind": "CALLS",
                    "confidence": 0.90,
                    "evidence_ref": results[0]["url"]
                }
            }
        ],
        "confidence_rules": [],
        "playground_cases": []
    }
    
    val_res = validate_candidate(wf_id, candidate)
    assert val_res["valid"] is True
    
    # 5. Install valid candidate
    inst_res = install_candidate(wf_id, candidate)
    assert inst_res["status"] == "installed"
    
    installed_path = Path(inst_res["path"])
    # Expected layout: support_packs/<ecosystem>/<library>/support_pack.json
    assert installed_path.name == "support_pack.json"
    assert installed_path.parent.name == "pytest"
    assert installed_path.parent.parent.name == "python"
    assert installed_path.exists()
    
    # Teardown the installed pack
    if installed_path.parent.exists():
        shutil.rmtree(installed_path.parent)


def test_research_workflow_rejects_invalid_install():
    wf_id = init_workflow(str(PROJECT_PATH), "pytest", "python")
    
    # Invalid candidate (missing fields)
    invalid_candidate = {
        "library": "pytest",
        "version_range": ">=7.0.0",
        "language": "python"
    }
    
    inst_res = install_candidate(wf_id, invalid_candidate)
    assert inst_res["status"] == "error"
    assert "errors" in inst_res
