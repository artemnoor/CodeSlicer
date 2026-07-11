"""Workflow lifecycle and storage manager. Stage 14."""
import json
import os
import uuid
from pathlib import Path
from typing import Dict, Any, List
import re

from impact_engine.research.sources import get_candidate_urls
from impact_engine.research.fetcher import WebFetcher
from impact_engine.research.input_pack import ResearchRequest, ResearchInputPack
from impact_engine.research.validation import validate_ai_generated_support_pack
from impact_engine.inventory.scanner import scan_project_inventory


def get_workflow_dir(workflow_id: str) -> Path:
    return Path(".impact_engine/research_workflows") / workflow_id


def init_workflow(project_path: str, library: str, ecosystem: str) -> str:
    workflow_id = str(uuid.uuid4())
    wf_dir = get_workflow_dir(workflow_id)
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "fetched_pages").mkdir(parents=True, exist_ok=True)
    
    # 1. Scan project inventory to extract imports/usages
    detected_imports = []
    detected_usages = []
    
    try:
        inv = scan_project_inventory(project_path)
        detected_imports = [imp for imp in inv.external_imports if library in imp or imp in library]
        
        # Scan files for usages code snippets
        root = Path(project_path).resolve()
        for rel_f in inv.files[:50]:  # Limit file scan count
            f_path = root / rel_f
            if f_path.exists() and f_path.is_file():
                try:
                    content = f_path.read_text(encoding="utf-8")
                    if library in content:
                        # Extract matching lines as examples
                        for line in content.splitlines():
                            if library in line and len(line) < 200:
                                detected_usages.append(line.strip())
                                if len(detected_usages) >= 10:
                                    break
                except Exception:
                    pass
            if len(detected_usages) >= 10:
                break
    except Exception:
        pass

    # 2. Get candidate URLs
    urls_dict = get_candidate_urls(library, ecosystem)
    
    # 3. Create Research Request
    req = ResearchRequest(
        ecosystem=ecosystem,
        library_name=library,
        detected_imports=detected_imports,
        detected_project_usage_examples=detected_usages,
        candidate_docs_urls=urls_dict["docs_urls"],
        candidate_github_urls=urls_dict["github_urls"],
        candidate_registry_urls=urls_dict["registry_urls"],
        source_plan=urls_dict.get("source_plan", []),
        examples_needed=[f"Constructor injection of {library}", f"Method calls on {library}"]
    )
    
    # 4. Save research request
    (wf_dir / "research_request.json").write_text(json.dumps(req.to_dict(), indent=2), encoding="utf-8")
    
    # Save empty placeholder files to avoid FileNotFoundError
    (wf_dir / "ai_input.json").write_text("{}", encoding="utf-8")
    (wf_dir / "candidate_support_pack.json").write_text("{}", encoding="utf-8")
    (wf_dir / "validation_result.json").write_text("{}", encoding="utf-8")
    
    return workflow_id


def fetch_pages(workflow_id: str, fetcher: WebFetcher | None = None) -> List[Dict[str, Any]]:
    wf_dir = get_workflow_dir(workflow_id)
    req_path = wf_dir / "research_request.json"
    if not req_path.exists():
        raise FileNotFoundError(f"Workflow {workflow_id} not found")
        
    req = json.loads(req_path.read_text(encoding="utf-8"))
    
    # Fetch a bounded primary-source corpus. Registry pages are metadata only;
    # official docs and repository tests/examples carry the useful semantics.
    candidates = []
    candidates.extend(req.get("candidate_docs_urls", []))
    candidates.extend(req.get("candidate_github_urls", []))
    candidates.extend(req.get("candidate_registry_urls", []))
    
    # Unique order-preserving list of first 5 HTTPS URLs
    urls_to_fetch = []
    for url in candidates:
        if url.lower().startswith("https://") and url not in urls_to_fetch:
            urls_to_fetch.append(url)
        if len(urls_to_fetch) >= 12:
            break
            
    if fetcher is None:
        fetcher = WebFetcher()
        
    fetched_results = []
    for i, url in enumerate(urls_to_fetch):
        res = fetcher.fetch(url)
        result_dict = {
            "url": res.url,
            "status_code": res.status_code,
            "content_type": res.content_type,
            "text_excerpt": res.text_excerpt,
            "error": res.error,
            "source_type": _source_type(url, req),
            "usable_evidence": bool(res.status_code and 200 <= res.status_code < 300 and res.text_excerpt),
        }
        fetched_results.append(result_dict)
        
        # Save individually to fetched_pages dir
        page_file = wf_dir / "fetched_pages" / f"page_{i}.json"
        page_file.write_text(json.dumps(result_dict, indent=2), encoding="utf-8")
        
    return fetched_results


def build_input_pack(workflow_id: str) -> Dict[str, Any]:
    wf_dir = get_workflow_dir(workflow_id)
    req_path = wf_dir / "research_request.json"
    if not req_path.exists():
        raise FileNotFoundError(f"Workflow {workflow_id} not found")
        
    req = json.loads(req_path.read_text(encoding="utf-8"))
    
    # Load all fetched pages
    fetched_pages = []
    pages_dir = wf_dir / "fetched_pages"
    if pages_dir.exists():
        for page_file in sorted(pages_dir.glob("page_*.json")):
            try:
                fetched_pages.append(json.loads(page_file.read_text(encoding="utf-8")))
            except Exception:
                pass
                
    detected_project_usage_examples = req.get("detected_project_usage_examples", [])
    
    input_pack = ResearchInputPack(
        research_request=req,
        fetched_pages=fetched_pages,
        source_plan=_source_plan_from_request(req),
        source_coverage=_source_coverage(fetched_pages),
        detected_project_usage_examples=detected_project_usage_examples
    )
    
    input_pack_dict = input_pack.to_dict()
    (wf_dir / "ai_input.json").write_text(json.dumps(input_pack_dict, indent=2), encoding="utf-8")
    from impact_engine.research.agent_task import write_agent_task

    write_agent_task(wf_dir, input_pack_dict, workflow_id)
    
    return input_pack_dict


def _source_type(url: str, request: dict[str, Any]) -> str:
    if url in request.get("candidate_docs_urls", []):
        return "official_docs"
    if url in request.get("candidate_github_urls", []):
        return "official_repository"
    return "package_registry"


def _source_plan_from_request(request: dict[str, Any]) -> list[dict[str, str]]:
    return (
        [{"url": url, "source_type": "official_docs"} for url in request.get("candidate_docs_urls", [])]
        + [{"url": url, "source_type": "official_repository"} for url in request.get("candidate_github_urls", [])]
        + [{"url": url, "source_type": "package_registry"} for url in request.get("candidate_registry_urls", [])]
    )


def _source_coverage(pages: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, dict[str, int]] = {}
    for page in pages:
        source_type = str(page.get("source_type") or "unknown")
        bucket = by_type.setdefault(source_type, {"fetched": 0, "usable": 0, "failed": 0})
        bucket["fetched"] += 1
        if page.get("usable_evidence"):
            bucket["usable"] += 1
        else:
            bucket["failed"] += 1
    return {
        "by_source_type": by_type,
        "total_fetched": len(pages),
        "total_usable": sum(item["usable"] for item in by_type.values()),
        "warnings": [
            "Research must declare coverage limitations when a primary source failed to fetch.",
            "A package registry page is metadata evidence, not semantic evidence.",
        ],
    }


def validate_candidate(workflow_id: str, candidate_pack_dict: Dict[str, Any]) -> Dict[str, Any]:
    wf_dir = get_workflow_dir(workflow_id)
    input_path = wf_dir / "ai_input.json"
    if not input_path.exists():
        # Build first if missing
        build_input_pack(workflow_id)
        
    input_pack = json.loads(input_path.read_text(encoding="utf-8"))
    
    res = validate_ai_generated_support_pack(candidate_pack_dict, input_pack)
    
    # Save candidate and validation result
    (wf_dir / "candidate_support_pack.json").write_text(json.dumps(candidate_pack_dict, indent=2), encoding="utf-8")
    (wf_dir / "validation_result.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    
    return res


def install_candidate(workflow_id: str, candidate_pack_dict: Dict[str, Any]) -> Dict[str, Any]:
    wf_dir = get_workflow_dir(workflow_id)
    
    # 1. Validate first
    val_res = validate_candidate(workflow_id, candidate_pack_dict)
    if not val_res["valid"]:
        return {
            "status": "error",
            "message": "Candidate support pack is invalid",
            "errors": val_res["errors"]
        }
        
    from impact_engine.support_packs.store import SupportPackStore
    store = SupportPackStore()
    inst_res = store.validate_and_save_pack(candidate_pack_dict)
    
    if not inst_res["valid"]:
        return {
            "status": "error",
            "message": "Candidate support pack is invalid",
            "errors": inst_res["errors"]
        }
        
    from impact_engine.remote_registry import RegistryClient

    registry_result = RegistryClient().cache_support_pack(candidate_pack_dict)
    return {
        "status": "installed",
        "path": inst_res["path"],
        "library": candidate_pack_dict.get("library", "unknown"),
        "version": candidate_pack_dict.get("version_range", "unknown"),
        "registry": registry_result,
    }
