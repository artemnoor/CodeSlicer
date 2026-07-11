from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from .models import ResearchRequest, to_jsonable
from .safety import NetworkNotAllowed, UnsafeUrlBlocked
from .storage import WorkflowStorage, stable_json
from .workflow import ResearchWorkflowService

EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1
EXIT_VALIDATION_FAILED = 2
EXIT_NETWORK_BLOCKED = 3


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "command") or args.command is None:
        parser.print_help()
        return EXIT_SUCCESS
    storage = WorkflowStorage(base_dir=args.storage_root)
    service = ResearchWorkflowService(storage)
    try:
        result, code = dispatch(args, service)
    except (NetworkNotAllowed, UnsafeUrlBlocked) as exc:
        return emit(args, {"ok": False, "error": str(exc), "error_type": exc.__class__.__name__}, EXIT_NETWORK_BLOCKED)
    except FileNotFoundError as exc:
        return emit(args, {"ok": False, "error": str(exc), "error_type": "FileNotFoundError"}, EXIT_RUNTIME_ERROR)
    except Exception as exc:
        return emit(args, {"ok": False, "error": str(exc), "error_type": exc.__class__.__name__}, EXIT_RUNTIME_ERROR)
    return emit(args, result, code)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ai_library_researcher_pro.cli")
    parser.add_argument("--storage-root", default=".", help="directory where .impact_engine/research_workflows is stored")
    sub = parser.add_subparsers(dest="command")

    def add_json(p: argparse.ArgumentParser) -> None:
        p.add_argument("--json", action="store_true", help="print stable machine-readable JSON")

    def add_request_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--library", required=True)
        p.add_argument("--ecosystem", required=True)
        p.add_argument("--project-path", default=".")
        p.add_argument("--version-range", default="*")
        p.add_argument("--max-pages", type=int, default=8)
        p.add_argument("--max-page-size-bytes", type=int, default=250_000)
        p.add_argument("--max-total-bytes", type=int, default=1_000_000)
        p.add_argument("--timeout-seconds", type=float, default=8.0)

    p = sub.add_parser("create", help="create a research workflow")
    add_request_args(p)
    add_json(p)

    for name in ["discover", "extract", "build-input", "generate-draft", "report"]:
        p = sub.add_parser(name, help=f"{name} workflow stage")
        p.add_argument("workflow_id")
        add_json(p)

    p = sub.add_parser("fetch", help="fetch candidate sources; requires --allow-network for remote URLs")
    p.add_argument("workflow_id")
    p.add_argument("--allow-network", action="store_true")
    add_json(p)

    p = sub.add_parser("validate", help="validate a support pack draft")
    p.add_argument("workflow_id")
    p.add_argument("--pack", help="optional external support_pack.json path")
    add_json(p)

    p = sub.add_parser("run", help="run the full workflow")
    add_request_args(p)
    p.add_argument("--allow-network", action="store_true")
    add_json(p)

    return parser


def dispatch(args: argparse.Namespace, service: ResearchWorkflowService) -> tuple[Dict[str, Any], int]:
    if args.command == "create":
        request = _request_from_args(args, allow_network=False)
        workflow = service.create_workflow(request)
        return {"ok": True, "workflow_id": workflow.workflow_id, "storage_path": workflow.storage_path}, EXIT_SUCCESS
    if args.command == "discover":
        sources = service.discover(args.workflow_id)
        return {"ok": True, "workflow_id": args.workflow_id, "sources": to_jsonable(sources)}, EXIT_SUCCESS
    if args.command == "fetch":
        if not args.allow_network:
            raise NetworkNotAllowed("fetch command requires explicit --allow-network")
        pages = service.fetch(args.workflow_id, allow_network=True, include_remote_when_offline=True)
        return {"ok": True, "workflow_id": args.workflow_id, "fetched_pages": to_jsonable(pages)}, EXIT_SUCCESS
    if args.command == "extract":
        examples = service.extract(args.workflow_id)
        return {"ok": True, "workflow_id": args.workflow_id, "examples": to_jsonable(examples)}, EXIT_SUCCESS
    if args.command == "build-input":
        data = service.build_input(args.workflow_id)
        return {"ok": True, "workflow_id": args.workflow_id, "ai_input": data}, EXIT_SUCCESS
    if args.command == "generate-draft":
        pack = service.generate_draft(args.workflow_id)
        return {"ok": True, "workflow_id": args.workflow_id, "support_pack_draft": pack}, EXIT_SUCCESS
    if args.command == "validate":
        result = service.validate(args.workflow_id, pack_path=args.pack)
        return {"ok": result.valid, "workflow_id": args.workflow_id, "validation": to_jsonable(result)}, EXIT_SUCCESS if result.valid else EXIT_VALIDATION_FAILED
    if args.command == "report":
        report = service.write_report(args.workflow_id)
        return {"ok": True, "workflow_id": args.workflow_id, "report_path": str(service.storage.workflow_dir(args.workflow_id) / "report.md"), "report": report}, EXIT_SUCCESS
    if args.command == "run":
        request = _request_from_args(args, allow_network=args.allow_network)
        result = service.run(request)
        # A generated weak draft can still be valid; validation failure gets exit 2.
        code = EXIT_SUCCESS if result.get("validation", {}).get("valid") else EXIT_VALIDATION_FAILED
        return result, code
    raise ValueError(f"unknown command: {args.command}")


def _request_from_args(args: argparse.Namespace, allow_network: bool) -> ResearchRequest:
    return ResearchRequest(
        library=args.library,
        ecosystem=args.ecosystem,
        project_path=args.project_path,
        version_range=args.version_range,
        allow_network=allow_network,
        max_pages=args.max_pages,
        max_page_size_bytes=args.max_page_size_bytes,
        max_total_bytes=args.max_total_bytes,
        timeout_seconds=args.timeout_seconds,
    )


def emit(args: argparse.Namespace, result: Dict[str, Any], code: int) -> int:
    if getattr(args, "json", False):
        sys.stdout.write(stable_json(result))
    else:
        if isinstance(result, dict) and "error" in result:
            sys.stderr.write(f"Error: {result['error']}\n")
        else:
            sys.stdout.write(json.dumps(to_jsonable(result), indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
