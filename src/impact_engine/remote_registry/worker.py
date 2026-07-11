"""Local worker for registry-backed research requests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from impact_engine.research.workflow import build_input_pack, init_workflow


def process_local_research_queue(
    *,
    project_path: str,
    cache_root: str | Path = ".impact_engine/registry_cache",
    limit: int = 20,
    allow_network: bool = False,
) -> dict[str, Any]:
    """Prepare AI input packs for locally queued registry research requests.

    This worker does not call an LLM. It converts queued registry requests into
    deterministic research workflow folders and input packs that an external AI
    researcher can consume.
    """

    root = Path(cache_root) / "research_requests"
    if not root.exists():
        return {"status": "ok", "processed": 0, "items": []}

    processed: list[dict[str, Any]] = []
    for request_path in sorted(root.glob("*/*/request.json"))[: max(0, limit)]:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        ecosystem = str(request.get("ecosystem") or "")
        library = str(request.get("library_name") or "")
        if not ecosystem or not library:
            processed.append({"path": str(request_path.as_posix()), "status": "error", "error": "missing ecosystem/library_name"})
            continue
        try:
            workflow_id = init_workflow(project_path, library, ecosystem)
            if allow_network:
                from impact_engine.research.workflow import fetch_pages

                fetch_pages(workflow_id)
            input_pack = build_input_pack(workflow_id)
            request["status"] = "prepared"
            request["workflow_id"] = workflow_id
            request["ai_input_path"] = str((Path(".impact_engine/research_workflows") / workflow_id / "ai_input.json").as_posix())
            request_path.write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")
            processed.append(
                {
                    "path": str(request_path.as_posix()),
                    "status": "prepared",
                    "workflow_id": workflow_id,
                    "library": library,
                    "ecosystem": ecosystem,
                    "input_pack_keys": sorted(input_pack.keys()),
                }
            )
        except Exception as exc:
            processed.append({"path": str(request_path.as_posix()), "status": "error", "error": str(exc)})

    return {"status": "ok", "processed": len(processed), "items": processed}
