from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .models import FetchedPage, ResearchRequest, ResearchSource, ResearchWorkflow, to_jsonable


class WorkflowStorage:
    def __init__(self, base_dir: str | Path = ".") -> None:
        self.base_dir = Path(base_dir)
        self.root = self.base_dir / ".impact_engine" / "research_workflows"

    def workflow_dir(self, workflow_id: str) -> Path:
        return self.root / workflow_id

    def create_workflow_dir(self, workflow_id: str) -> Path:
        path = self.workflow_dir(workflow_id)
        path.mkdir(parents=True, exist_ok=True)
        (path / "fetched_pages").mkdir(exist_ok=True)
        return path

    def write_json(self, workflow_id: str, filename: str, data: Any) -> Path:
        path = self.workflow_dir(workflow_id) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(stable_json(data), encoding="utf-8")
        return path

    def read_json(self, workflow_id: str, filename: str) -> Any:
        path = self.workflow_dir(workflow_id) / filename
        return json.loads(path.read_text(encoding="utf-8"))

    def write_text(self, workflow_id: str, filename: str, data: str) -> Path:
        path = self.workflow_dir(workflow_id) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")
        return path

    def read_text(self, workflow_id: str, filename: str) -> str:
        return (self.workflow_dir(workflow_id) / filename).read_text(encoding="utf-8")

    def save_workflow(self, workflow: ResearchWorkflow) -> None:
        self.create_workflow_dir(workflow.workflow_id)
        self.write_json(workflow.workflow_id, "research_request.json", workflow.request)
        self.write_json(workflow.workflow_id, "workflow.json", workflow)

    def load_request(self, workflow_id: str) -> ResearchRequest:
        return ResearchRequest.from_dict(self.read_json(workflow_id, "research_request.json"))

    def save_sources(self, workflow_id: str, sources: Iterable[ResearchSource]) -> None:
        self.write_json(workflow_id, "discovered_sources.json", list(sources))

    def load_sources(self, workflow_id: str) -> List[ResearchSource]:
        return [ResearchSource.from_dict(x) for x in self.read_json(workflow_id, "discovered_sources.json")]

    def save_fetched_pages(self, workflow_id: str, pages: Iterable[FetchedPage]) -> None:
        page_dir = self.workflow_dir(workflow_id) / "fetched_pages"
        if page_dir.exists():
            for item in page_dir.iterdir():
                if item.is_file():
                    item.unlink()
        page_dir.mkdir(parents=True, exist_ok=True)
        index: List[Dict[str, Any]] = []
        for idx, page in enumerate(pages):
            filename = f"page_{idx:03d}.txt"
            (page_dir / filename).write_text(page.text_excerpt or "", encoding="utf-8")
            data = to_jsonable(page)
            data["artifact_file"] = f"fetched_pages/{filename}"
            data.pop("text_excerpt", None)
            index.append(data)
        self.write_json(workflow_id, "fetched_pages/index.json", index)

    def load_fetched_pages(self, workflow_id: str) -> List[FetchedPage]:
        index = self.read_json(workflow_id, "fetched_pages/index.json")
        pages: List[FetchedPage] = []
        for item in index:
            text = (self.workflow_dir(workflow_id) / item["artifact_file"]).read_text(encoding="utf-8")
            data = dict(item)
            data.pop("artifact_file", None)
            data["text_excerpt"] = text
            pages.append(FetchedPage.from_dict(data))
        return pages


def stable_json(data: Any) -> str:
    return json.dumps(to_jsonable(data), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
