from __future__ import annotations

import json
from pathlib import Path

from ai_library_researcher_pro.models import ResearchRequest
from ai_library_researcher_pro.storage import WorkflowStorage
from ai_library_researcher_pro.workflow import ResearchWorkflowService


FIXTURE_PROJECT = Path(__file__).resolve().parents[1] / "fixtures" / "sample_project"


def test_workflow_creation_writes_correct_files(tmp_path: Path):
    service = ResearchWorkflowService(WorkflowStorage(tmp_path))
    workflow = service.create_workflow(ResearchRequest(library="fastapi", ecosystem="python", project_path=str(FIXTURE_PROJECT)))
    root = tmp_path / ".impact_engine" / "research_workflows" / workflow.workflow_id

    assert root.is_dir()
    assert (root / "research_request.json").is_file()
    assert (root / "workflow.json").is_file()
    assert (root / "fetched_pages").is_dir()
    saved = json.loads((root / "research_request.json").read_text())
    assert saved["library"] == "fastapi"
    assert saved["ecosystem"] == "python"


def test_ai_input_pack_includes_required_data(tmp_path: Path):
    service = ResearchWorkflowService(WorkflowStorage(tmp_path))
    workflow = service.create_workflow(ResearchRequest(library="fastapi", ecosystem="python", project_path=str(FIXTURE_PROJECT)))
    service.discover(workflow.workflow_id)
    service.fetch(workflow.workflow_id, allow_network=False)
    service.extract(workflow.workflow_id)
    ai_input = service.build_input(workflow.workflow_id)

    assert ai_input["library"] == "fastapi"
    assert ai_input["ecosystem"] == "python"
    assert any("fastapi" in item for item in ai_input["detected_imports"])
    assert ai_input["fetched_source_excerpts"]
    assert ai_input["extracted_examples"]
    assert (tmp_path / ".impact_engine" / "research_workflows" / workflow.workflow_id / "ai_prompt.md").is_file()


def test_full_offline_run_works_with_fixtures(tmp_path: Path):
    service = ResearchWorkflowService(WorkflowStorage(tmp_path))
    result = service.run(ResearchRequest(library="fastapi", ecosystem="python", project_path=str(FIXTURE_PROJECT)))

    assert result["workflow_id"].startswith("python_fastapi_")
    assert result["fetched_pages"] >= 1
    assert result["extracted_examples"] >= 1
    root = tmp_path / ".impact_engine" / "research_workflows" / result["workflow_id"]
    for name in [
        "research_request.json",
        "discovered_sources.json",
        "extracted_examples.json",
        "ai_input.json",
        "ai_prompt.md",
        "support_pack_draft.json",
        "validation_result.json",
        "report.md",
    ]:
        assert (root / name).is_file()
    validation = json.loads((root / "validation_result.json").read_text())
    assert validation["valid"] is True


def test_full_network_mode_can_be_mocked(tmp_path: Path, monkeypatch):
    from ai_library_researcher_pro.fetcher import SafeHTTPFetcher
    from ai_library_researcher_pro.models import FetchedPage

    def fake_fetch_source(self, source, project_root="."):
        return FetchedPage(
            source_url=source.url,
            source_type=source.source_type,
            title=source.title,
            content_type="text/markdown",
            text_excerpt="""
```python
from fastapi import APIRouter
router = APIRouter(prefix='/x')
@router.get('/')
def read_x():
    return {}
```
""",
            status_code=200,
            bytes_read=120,
        )

    monkeypatch.setattr(SafeHTTPFetcher, "fetch_source", fake_fetch_source)
    service = ResearchWorkflowService(WorkflowStorage(tmp_path))
    result = service.run(ResearchRequest(library="fastapi", ecosystem="python", project_path=str(tmp_path), allow_network=True, max_pages=2))

    assert result["fetched_pages"] == 2
    assert result["validation"]["valid"] is True
