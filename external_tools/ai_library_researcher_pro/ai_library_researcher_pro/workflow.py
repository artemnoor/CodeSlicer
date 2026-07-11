from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .extractor import ExampleExtractor
from .fetcher import SafeHTTPFetcher
from .generator import SupportPackGenerator, build_research_input_pack
from .models import ExtractedExample, ResearchRequest, ResearchSource, ResearchWorkflow, ValidationResult, to_jsonable
from .report import build_report
from .safety import SafetyLimits, SafetyPolicy
from .search import discover_sources
from .storage import WorkflowStorage
from .validator import SupportPackValidator


class ResearchWorkflowService:
    def __init__(self, storage: WorkflowStorage | None = None) -> None:
        self.storage = storage or WorkflowStorage()
        self.extractor = ExampleExtractor()
        self.generator = SupportPackGenerator()
        self.validator = SupportPackValidator()

    def create_workflow(self, request: ResearchRequest) -> ResearchWorkflow:
        workflow_id = make_workflow_id(request)
        workflow = ResearchWorkflow(
            workflow_id=workflow_id,
            request=request,
            storage_path=str(self.storage.workflow_dir(workflow_id)),
        )
        self.storage.save_workflow(workflow)
        return workflow

    def discover(self, workflow_id: str) -> List[ResearchSource]:
        request = self.storage.load_request(workflow_id)
        sources = discover_sources(request)
        self.storage.save_sources(workflow_id, sources)
        return sources

    def fetch(self, workflow_id: str, allow_network: bool = False, include_remote_when_offline: bool = False) -> List[Any]:
        request = self.storage.load_request(workflow_id)
        sources = self._load_or_discover_sources(workflow_id)
        if not allow_network and not include_remote_when_offline:
            sources = [s for s in sources if s.local_path or s.url.startswith("local://")]
        limits = SafetyLimits(
            max_url_count=max(request.max_pages, 1),
            max_page_size_bytes=request.max_page_size_bytes,
            max_total_bytes=request.max_total_bytes,
            timeout_seconds=request.timeout_seconds,
        )
        policy = SafetyPolicy(allow_network=allow_network, limits=limits)
        fetcher = SafeHTTPFetcher(policy)
        limited_sources = sources[: request.max_pages]
        pages = fetcher.fetch_many(limited_sources, project_root=request.project_path)
        self.storage.save_fetched_pages(workflow_id, pages)
        return pages

    def extract(self, workflow_id: str) -> List[ExtractedExample]:
        pages = self.storage.load_fetched_pages(workflow_id)
        examples = self.extractor.extract_many(pages)
        self.storage.write_json(workflow_id, "extracted_examples.json", examples)
        return examples

    def build_input(self, workflow_id: str) -> Dict[str, Any]:
        request = self.storage.load_request(workflow_id)
        pages = self._load_pages_or_empty(workflow_id)
        examples = self._load_examples_or_empty(workflow_id)
        diagnostics = []
        if not pages:
            diagnostics.append("No fetched pages available; input pack is based on discovery only.")
        if not examples:
            diagnostics.append("No extracted examples available; support-pack generation will be weak.")
        input_pack = build_research_input_pack(request, pages, examples, diagnostics=diagnostics)
        self.storage.write_json(workflow_id, "ai_input.json", input_pack)
        prompt = self.generator.build_ai_prompt(input_pack)
        self.storage.write_text(workflow_id, "ai_prompt.md", prompt)
        return to_jsonable(input_pack)

    def generate_draft(self, workflow_id: str) -> Dict[str, Any]:
        request = self.storage.load_request(workflow_id)
        try:
            input_data = self.storage.read_json(workflow_id, "ai_input.json")
        except FileNotFoundError:
            input_data = self.build_input(workflow_id)
        # Recreate minimal input pack object without depending on private dataclass layout.
        from .models import ResearchInputPack

        input_pack = ResearchInputPack(
            library=input_data["library"],
            ecosystem=input_data["ecosystem"],
            version_range=input_data.get("version_range", request.version_range),
            detected_imports=input_data.get("detected_imports", []),
            fetched_source_excerpts=input_data.get("fetched_source_excerpts", []),
            extracted_examples=input_data.get("extracted_examples", []),
            diagnostics=input_data.get("diagnostics", []),
        )
        pack = self.generator.generate_heuristic_draft(input_pack)
        self.storage.write_json(workflow_id, "support_pack_draft.json", pack)
        return pack

    def validate(self, workflow_id: str, pack_path: Optional[str] = None) -> ValidationResult:
        if pack_path:
            pack = json.loads(Path(pack_path).read_text(encoding="utf-8"))
        else:
            pack = self.storage.read_json(workflow_id, "support_pack_draft.json")
        result = self.validator.validate(pack)
        self.storage.write_json(workflow_id, "validation_result.json", result)
        return result

    def write_report(self, workflow_id: str) -> str:
        request = self.storage.load_request(workflow_id)
        sources = self._load_or_discover_sources(workflow_id)
        pages = self._load_pages_or_empty(workflow_id)
        examples = self._load_examples_or_empty(workflow_id)
        try:
            pack = self.storage.read_json(workflow_id, "support_pack_draft.json")
        except FileNotFoundError:
            pack = None
        try:
            validation = ValidationResult.from_dict(self.storage.read_json(workflow_id, "validation_result.json"))
        except FileNotFoundError:
            validation = None
        report = build_report(request.library, request.ecosystem, sources, pages, examples, pack, validation)
        self.storage.write_text(workflow_id, "report.md", report)
        return report

    def run(self, request: ResearchRequest) -> Dict[str, Any]:
        workflow = self.create_workflow(request)
        sources = self.discover(workflow.workflow_id)
        pages = self.fetch(workflow.workflow_id, allow_network=request.allow_network, include_remote_when_offline=False)
        examples = self.extract(workflow.workflow_id)
        input_pack = self.build_input(workflow.workflow_id)
        draft = self.generate_draft(workflow.workflow_id)
        validation = self.validate(workflow.workflow_id)
        report = self.write_report(workflow.workflow_id)
        return {
            "ok": validation.valid,
            "workflow_id": workflow.workflow_id,
            "storage_path": str(self.storage.workflow_dir(workflow.workflow_id)),
            "sources": len(sources),
            "fetched_pages": len(pages),
            "extracted_examples": len(examples),
            "support_pack_path": str(self.storage.workflow_dir(workflow.workflow_id) / "support_pack_draft.json"),
            "validation": to_jsonable(validation),
            "report_path": str(self.storage.workflow_dir(workflow.workflow_id) / "report.md"),
        }

    def _load_or_discover_sources(self, workflow_id: str) -> List[ResearchSource]:
        try:
            return self.storage.load_sources(workflow_id)
        except FileNotFoundError:
            return self.discover(workflow_id)

    def _load_pages_or_empty(self, workflow_id: str) -> List[Any]:
        try:
            return self.storage.load_fetched_pages(workflow_id)
        except FileNotFoundError:
            return []

    def _load_examples_or_empty(self, workflow_id: str) -> List[ExtractedExample]:
        try:
            return [ExtractedExample.from_dict(x) for x in self.storage.read_json(workflow_id, "extracted_examples.json")]
        except FileNotFoundError:
            return []


def make_workflow_id(request: ResearchRequest) -> str:
    base = {
        "library": request.library.strip().lower(),
        "ecosystem": request.ecosystem.strip().lower(),
        "version_range": request.version_range,
        "project_path": str(Path(request.project_path).resolve()),
    }
    digest = hashlib.sha1(json.dumps(base, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    safe_library = re.sub(r"[^a-z0-9]+", "_", base["library"]).strip("_") or "library"
    safe_ecosystem = re.sub(r"[^a-z0-9]+", "_", base["ecosystem"]).strip("_") or "eco"
    return f"{safe_ecosystem}_{safe_library}_{digest}"
