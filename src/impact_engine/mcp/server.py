"""MCP server implementation. Stage 8 complete.

Exposes a robust local MCP stdio runtime wrapper on top of core tools.
"""
import json
import ast
import sys
import concurrent.futures
from pathlib import Path
from typing import Dict, Any, List

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from impact_engine.models import GraphDocument
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.precision import resolve_precision
from impact_engine.impact import impact_query as impact_query_core, explain_edge as explain_edge_core
from impact_engine.support_packs.registry import list_local_support_packs, validate_support_pack_file, import_support_pack_file
from impact_engine.contracts import build_mode_response
from impact_engine.tool_runtime import ToolRuntime
from impact_engine.approvals import ApprovalStore


def _verify_path_exists(p_str: str) -> None:
    if not p_str:
        raise ValueError("Path argument cannot be empty")
    p = Path(p_str).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Path does not exist: {p_str}")


def _approval_payload(**values: Any) -> dict[str, Any]:
    """Create a stable, deliberately small record of an action request."""
    return values


def request_action_approval(
    project_path: str,
    action: str,
    payload: dict[str, Any],
    ttl_seconds: int = 300,
) -> Dict[str, Any]:
    """Create a pending local-host approval; this tool cannot approve it."""
    _verify_path_exists(project_path)
    if action not in {
        "managed_tool.connect", "managed_tool.run", "managed_tool.help",
        "runtime_trace", "investigate.runtime_validate", "ci.run_tests", "project.onboard", "research.fetch_pages",
    }:
        raise ValueError("unsupported approval action")
    approval = ApprovalStore(project_path).request(action, payload, ttl_seconds=ttl_seconds)
    return {
        "tool": "request_action_approval",
        "status": "pending_approval",
        "project_path": str(Path(project_path).resolve()),
        "approval": approval,
        "next_step": (
            "A project owner must approve this request locally. Run "
            f"`impact-engine --json approvals approve \"{Path(project_path).resolve()}\" "
            f"\"{approval['approval_id']}\"`, then supply the returned one-time "
            "approval_id and approval_token to the original action."
        ),
    }


def approve_action_locally(project_path: str, approval_id: str) -> Dict[str, Any]:
    """Host-facing helper. It is intentionally not exposed as an MCP tool."""
    _verify_path_exists(project_path)
    return ApprovalStore(project_path).approve(approval_id)


def _consume_approval(project_path: str, approval_id: str | None, approval_token: str | None, action: str, payload: dict[str, Any]) -> None:
    if not approval_id or not approval_token:
        raise ValueError("a one-time local-host approval_id and approval_token are required")
    ApprovalStore(project_path).consume(approval_id, approval_token, action, payload)


def health_check() -> Dict[str, Any]:
    return {
        "tool": "health_check",
        "status": "ok",
        "health": "healthy"
    }


def server_info() -> Dict[str, Any]:
    return {
        "tool": "server_info",
        "status": "ok",
        "name": "impact-engine",
        "version": "0.5.0",
        "protocol_version": "2024-11-05"
    }


def _mode_response(mode: str, project_path: str, result: dict[str, Any] | None) -> dict[str, Any]:
    report = result or {}
    return build_mode_response(
        mode,
        project=project_path,
        freshness=report.get("graph_freshness"),
        coverage=report.get("coverage"),
        warnings=report.get("warnings", []),
        adapters=report.get("adapters", []),
        result=report,
    )


def analyze_project(
    project_path: str,
    out_path: str | None = None,
    timeout_seconds: int | None = None,
    enable_remote_registry: bool = False,
    create_research_requests: bool = True,
    include_graph: bool = False,
    scope: str | None = None,
    memory_budget_mb: int | None = None,
    time_budget_seconds: float | None = None,
    cancellation=None,
) -> Dict[str, Any]:
    from impact_engine.analysis.pipeline import analyze_project_core
    try:
        _verify_path_exists(project_path)
        res = analyze_project_core(
            project_path,
            out_path=out_path,
            enable_remote_registry=enable_remote_registry,
            create_research_requests=create_research_requests,
            scope=scope,
            memory_budget_mb=memory_budget_mb,
            time_budget_seconds=time_budget_seconds or timeout_seconds,
            cancellation=cancellation,
        )
        return {
            "tool": "analyze_project",
            "status": res["status"],
            "path": project_path,
            "graph_path": res.get("graph_path") or out_path or None,
            "nodes": res["nodes"],
            "edges": res["edges"],
            "inventory": res.get("inventory", {}),
            "languages": res.get("languages", []),
            "extractors_used": res.get("extractors_used", []),
            "diagnostics": res.get("diagnostics", {}),
            "support_pack_load_errors": res.get("support_pack_load_errors", []),
            "progress": res.get("progress", {}),
            # A full graph can contain thousands of nodes. MCP agents get a
            # compact contract first and use inspect/review/investigate for a
            # bounded slice. The raw graph remains at graph_path.
            **({"graph": res.get("graph", {})} if include_graph else {}),
        }
    except Exception as e:
        return {
            "tool": "analyze_project",
            "status": "error",
            "path": project_path,
            "error": str(e)
        }


def scan_plan(project_path: str, scope: str | None = None) -> Dict[str, Any]:
    """Return a no-write preflight so an MCP-only agent can plan analysis."""
    from impact_engine.inventory.scanner import scan_project_inventory
    from impact_engine.languages.registry import detect_languages
    try:
        _verify_path_exists(project_path)
        root = Path(project_path).resolve()
        scan_root = (root / scope).resolve() if scope else root
        if root not in scan_root.parents and scan_root != root:
            raise ValueError("scope must stay inside project_path")
        if not scan_root.is_dir():
            raise FileNotFoundError(f"scope does not exist: {scope}")
        inventory = scan_project_inventory(str(scan_root))
        return {
            "tool": "scan_plan", "status": "ok", "project_path": str(root), "scope": scope or ".",
            "inventory": {"files": inventory.files_count, "loc": inventory.loc, "languages": inventory.languages, "manifests": inventory.package_manifests},
            "detected_languages": detect_languages(str(root)),
            "estimated_action": "Run analyze_project with an optional scope and explicit budgets; no network is required.",
            "privacy": {"mode": "local-only", "network_used": False},
        }
    except Exception as exc:
        return {"tool": "scan_plan", "status": "error", "project_path": project_path, "error": str(exc)}


def project_status(project_path: str) -> Dict[str, Any]:
    """Give an MCP client the same concise status it needs after onboarding."""
    try:
        _verify_path_exists(project_path)
        root = Path(project_path).resolve()
        graph = root / ".impact_engine" / "graph.json"
        onboarding = root / ".codeslicer" / "artifacts" / "onboarding" / "last.json"
        report = json.loads(onboarding.read_text(encoding="utf-8")) if onboarding.is_file() else None
        return {
            "tool": "project_status", "status": "ok", "project_path": str(root),
            "canonical_graph": {"path": str(graph), "exists": graph.is_file()},
            "onboarding": report,
            "next_action": "review" if graph.is_file() else "scan_plan",
            "privacy": {"mode": "local-only", "network_used": False},
        }
    except Exception as exc:
        return {"tool": "project_status", "status": "error", "project_path": project_path, "error": str(exc)}


def onboard(
    source: str,
    allow_network: bool = False,
    workspace: str | None = None,
    branch: str | None = None,
    graphify_mode: str = "off",
    graphify_timeout_seconds: int = 120,
    approval_id: str | None = None,
    approval_token: str | None = None,
) -> Dict[str, Any]:
    """MCP-safe entry point for a local folder or explicitly approved Git URL."""
    from impact_engine.project_onboarding import onboard_project
    try:
        if allow_network or graphify_mode != "off":
            approval_root = source if Path(source).is_dir() else (workspace or Path.cwd())
            _consume_approval(
                str(approval_root), approval_id, approval_token, "project.onboard",
                _approval_payload(
                    executable="git" if allow_network else "graphify",
                    argv=["clone", source] if allow_network else ["extract", source, "--code-only"],
                    cwd=str(Path(workspace or Path.cwd()).resolve()), timeout_seconds=graphify_timeout_seconds,
                    network_expected=allow_network, source=source, branch=branch or "", graphify_mode=graphify_mode,
                ),
            )
        result = onboard_project(source, allow_network=allow_network, workspace=workspace, branch=branch, graphify_mode=graphify_mode, graphify_timeout_seconds=graphify_timeout_seconds)
        return {"tool": "onboard", "status": result.get("status", "ok"), "result": result}
    except Exception as exc:
        return {"tool": "onboard", "status": "error", "source": source, "error": str(exc)}


def impact_query(
    graph_path: str,
    target: str = "",
    symbol: str | None = None,
    file_path: str | None = None,
    direction: str = "both",
    max_depth: int | None = None,
    min_confidence: float = 0.0,
    include_evidence: bool = True
) -> Dict[str, Any]:
    try:
        _verify_path_exists(graph_path)
        graph_text = Path(graph_path).read_text(encoding="utf-8")
        graph = GraphDocument.from_json(graph_text)
        if symbol:
            exact = [node for node in graph.nodes if node.id == symbol or node.name == symbol]
            partial = [node for node in graph.nodes if symbol.lower() in node.id.lower() or symbol.lower() in str(node.name or "").lower()]
            candidates = exact or partial
            unique = {node.id: node for node in candidates}
            if len(unique) > 1:
                return {
                    "tool": "impact_query", "status": "needs_selection", "graph_path": graph_path,
                    "query": symbol,
                    "candidates": [{"id": node.id, "name": node.name, "kind": node.kind, "file": node.properties.get("file")} for node in list(unique.values())[:20]],
                    "result": None,
                }
            if len(unique) == 1:
                target = next(iter(unique))
                symbol = None
        result = impact_query_core(
            graph,
            target=target,
            symbol=symbol,
            file_path=file_path,
            direction=direction,
            max_depth=max_depth,
            min_confidence=min_confidence,
            include_evidence=include_evidence
        )
        return {
            "tool": "impact_query",
            "status": "ok",
            "graph_path": graph_path,
            "result": result
        }
    except Exception as e:
        return {
            "tool": "impact_query",
            "status": "error",
            "graph_path": graph_path,
            "error": str(e),
            "result": None
        }


def explain_edge(graph_path: str, from_symbol: str, to_symbol: str, kind: str | None = None) -> Dict[str, Any]:
    try:
        _verify_path_exists(graph_path)
        graph_text = Path(graph_path).read_text(encoding="utf-8")
        graph = GraphDocument.from_json(graph_text)
        result = explain_edge_core(graph, from_symbol, to_symbol, kind)
        return {
            "tool": "explain_edge",
            "status": "ok",
            "graph_path": graph_path,
            "result": result
        }
    except Exception as e:
        return {
            "tool": "explain_edge",
            "status": "error",
            "graph_path": graph_path,
            "error": str(e),
            "result": None
        }


def graph_quality(graph_path: str) -> Dict[str, Any]:
    from impact_engine.graph_quality import graph_quality_report
    try:
        _verify_path_exists(graph_path)
        graph = GraphDocument.from_json(Path(graph_path).read_text(encoding="utf-8"))
        return {"tool": "graph_quality", "status": "ok", "graph_path": graph_path, "result": graph_quality_report(graph)}
    except Exception as e:
        return {"tool": "graph_quality", "status": "error", "graph_path": graph_path, "error": str(e)}


def impact_path(graph_path: str, from_symbol: str, to_symbol: str, max_depth: int = 20) -> Dict[str, Any]:
    from impact_engine.impact import impact_path as impact_path_core
    try:
        _verify_path_exists(graph_path)
        graph = GraphDocument.from_json(Path(graph_path).read_text(encoding="utf-8"))
        return {"tool": "impact_path", "status": "ok", "graph_path": graph_path, "result": impact_path_core(graph, from_symbol, to_symbol, max_depth)}
    except Exception as e:
        return {"tool": "impact_path", "status": "error", "graph_path": graph_path, "error": str(e)}


def pr_review(
    project_path: str,
    graph_path: str | None = None,
    diff_text: str | None = None,
    max_depth: int = 6,
    min_confidence: float = 0.0,
    max_results: int = 10,
    include_full_evidence: bool = False,
) -> Dict[str, Any]:
    from impact_engine.pr_review import pr_review_core
    try:
        _verify_path_exists(project_path)
        if graph_path:
            _verify_path_exists(graph_path)
        result = pr_review_core(
            project_path,
            graph_path=graph_path,
            diff_text=diff_text,
            max_depth=max_depth,
            min_confidence=min_confidence,
            max_results=max_results,
            include_full_evidence=include_full_evidence,
        )
        return {"tool": "pr_review", "status": "ok", "project_path": project_path, "result": result}
    except Exception as e:
        return {"tool": "pr_review", "status": "error", "project_path": project_path, "error": str(e), "result": None}


def review(
    project_path: str,
    graph_path: str | None = None,
    diff_text: str | None = None,
    base: str | None = None,
    refresh: str = "auto",
    max_results: int = 10,
    run_tests: str = "suggested",
    deep: bool = False,
    entity: str | None = None,
) -> Dict[str, Any]:
    from impact_engine.review import build_review_report
    try:
        _verify_path_exists(project_path)
        graph = GraphDocument.from_json(Path(graph_path).read_text(encoding="utf-8")) if graph_path else None
        result = build_review_report(project_path, graph=graph, graph_path=graph_path, diff_text=diff_text, base=base, refresh=refresh, max_results=max_results, run_tests=run_tests, deep=deep, entity=entity)
        return {"tool": "review", "status": "ok", "project_path": project_path, "result": result, "mode_response": _mode_response("review", project_path, result)}
    except Exception as e:
        return {"tool": "review", "status": "error", "project_path": project_path, "error": str(e), "result": None}


def inspect(
    project_path: str,
    entity: str,
    graph_path: str | None = None,
    refresh: str = "never",
    max_context: int = 12,
) -> Dict[str, Any]:
    from impact_engine.modes import build_inspect_report
    try:
        _verify_path_exists(project_path)
        if graph_path:
            _verify_path_exists(graph_path)
        result = build_inspect_report(project_path, entity=entity, graph_path=graph_path, refresh=refresh, max_context=max_context)
        return {"tool": "inspect", "status": "ok", "project_path": project_path, "result": result, "mode_response": _mode_response("inspect", project_path, result)}
    except Exception as e:
        return {"tool": "inspect", "status": "error", "project_path": project_path, "error": str(e), "result": None}


def investigate(
    project_path: str,
    entity: str,
    graph_path: str | None = None,
    direction: str = "both",
    depth: int = 8,
    runtime_validate: bool = False,
    max_nodes: int = 500,
    max_edges: int = 1000,
    refresh: str = "never",
    approval_id: str | None = None,
    approval_token: str | None = None,
) -> Dict[str, Any]:
    from impact_engine.modes import build_investigate_report
    try:
        _verify_path_exists(project_path)
        if graph_path:
            _verify_path_exists(graph_path)
        if runtime_validate:
            _consume_approval(
                project_path, approval_id, approval_token, "investigate.runtime_validate",
                _approval_payload(executable="python", argv=["-m", "pytest"], cwd=str(Path(project_path).resolve()), timeout_seconds=60, network_expected=False, entity=entity, graph_path=graph_path or ""),
            )
        result = build_investigate_report(project_path, entity=entity, graph_path=graph_path, direction=direction, depth=depth, runtime_validate=runtime_validate, max_nodes=max_nodes, max_edges=max_edges, refresh=refresh)
        return {"tool": "investigate", "status": "ok", "project_path": project_path, "result": result, "mode_response": _mode_response("investigate", project_path, result)}
    except Exception as e:
        return {"tool": "investigate", "status": "error", "project_path": project_path, "error": str(e), "result": None}


def ci(
    project_path: str,
    base: str | None = None,
    policy_path: str | None = None,
    graph_path: str | None = None,
    diff_text: str | None = None,
    refresh: str = "auto",
    run_tests: bool = False,
    test_command: list[str] | None = None,
    approval_id: str | None = None,
    approval_token: str | None = None,
) -> Dict[str, Any]:
    from impact_engine.modes import build_ci_report
    try:
        _verify_path_exists(project_path)
        for candidate in (policy_path, graph_path):
            if candidate:
                _verify_path_exists(candidate)
        if run_tests:
            payload = _approval_payload(test_command=test_command or [], base=base or "", refresh=refresh)
            _consume_approval(project_path, approval_id, approval_token, "ci.run_tests", payload)
        result = build_ci_report(project_path, base=base, policy_path=policy_path, graph_path=graph_path, diff_text=diff_text, refresh=refresh, run_tests=run_tests, test_command=test_command)
        return {"tool": "ci", "status": "ok", "project_path": project_path, "result": result, "mode_response": _mode_response("ci", project_path, result)}
    except Exception as e:
        return {"tool": "ci", "status": "error", "project_path": project_path, "error": str(e), "result": None}


def runtime_trace(
    project_path: str,
    graph_path: str | None = None,
    out_path: str | None = None,
    test_command: list[str] | None = None,
    timeout_seconds: int = 60,
    approval_id: str | None = None,
    approval_token: str | None = None,
) -> Dict[str, Any]:
    from impact_engine.runtime_trace import runtime_trace_project_core
    try:
        _verify_path_exists(project_path)
        if graph_path:
            _verify_path_exists(graph_path)
        payload = _approval_payload(test_command=test_command or [], timeout_seconds=timeout_seconds, graph_path=graph_path or "")
        _consume_approval(project_path, approval_id, approval_token, "runtime_trace", payload)
        result = runtime_trace_project_core(
            project_path,
            graph_path=graph_path,
            out_path=out_path,
            test_command=test_command,
            timeout_seconds=timeout_seconds,
        )
        return {"tool": "runtime_trace", "status": result.get("status"), "project_path": project_path, "result": result}
    except Exception as e:
        return {"tool": "runtime_trace", "status": "error", "project_path": project_path, "error": str(e), "result": None}


def detect_unknown_libraries(project_path: str) -> Dict[str, Any]:
    from impact_engine.support_packs.detection import detect_unknown_libraries_core
    try:
        _verify_path_exists(project_path)
        unknown = detect_unknown_libraries_core(project_path)
        return {
            "tool": "detect_unknown_libraries",
            "status": "ok",
            "path": project_path,
            "unknown_libraries": unknown
        }
    except Exception as e:
        return {
            "tool": "detect_unknown_libraries",
            "status": "error",
            "path": project_path,
            "error": str(e),
            "unknown_libraries": []
        }


def detect_languages(project_path: str) -> Dict[str, Any]:
    from impact_engine.languages.registry import detect_languages as detect_langs
    try:
        _verify_path_exists(project_path)
        langs = detect_langs(project_path)
        return {
            "tool": "detect_languages",
            "status": "ok",
            "project_path": project_path,
            "languages": langs
        }
    except Exception as e:
        return {
            "tool": "detect_languages",
            "status": "error",
            "project_path": project_path,
            "error": str(e),
            "languages": []
        }


def project_inventory(project_path: str) -> Dict[str, Any]:
    from impact_engine.inventory.scanner import scan_project_inventory
    try:
        _verify_path_exists(project_path)
        inv = scan_project_inventory(project_path)
        return {
            "tool": "project_inventory",
            "status": "ok",
            "project_path": project_path,
            "inventory": inv.to_dict()
        }
    except Exception as e:
        return {
            "tool": "project_inventory",
            "status": "error",
            "project_path": project_path,
            "error": str(e)
        }


def list_support_packs(root: str = "support_packs") -> Dict[str, Any]:
    paths = list_local_support_packs(root)
    return {
        "tool": "list_support_packs",
        "status": "ok",
        "packs": [str(p.as_posix()) for p in paths]
    }


def validate_support_pack(path: str) -> Dict[str, Any]:
    try:
        _verify_path_exists(path)
        res = validate_support_pack_file(path)
        return {
            "tool": "validate_support_pack",
            "status": "ok" if res["valid"] else "error",
            "pack_path": path,
            "valid": res["valid"],
            "errors": res["errors"]
        }
    except Exception as e:
        return {
            "tool": "validate_support_pack",
            "status": "error",
            "pack_path": path,
            "valid": False,
            "errors": [str(e)]
        }


def import_support_pack(pack_path: str, registry_root: str = "support_packs") -> Dict[str, Any]:
    try:
        _verify_path_exists(pack_path)
        res = import_support_pack_file(pack_path, registry_root)
        return {
            "tool": "import_support_pack",
            "status": res["status"],
            "pack_path": pack_path,
            "registry_root": registry_root,
            "message": res.get("message", ""),
            "errors": res.get("errors", [])
        }
    except Exception as e:
        return {
            "tool": "import_support_pack",
            "status": "error",
            "pack_path": pack_path,
            "registry_root": registry_root,
            "errors": [str(e)]
        }


def install_support_pack(pack_path: str, registry_root: str = "support_packs") -> Dict[str, Any]:
    try:
        _verify_path_exists(pack_path)
        res = import_support_pack_file(pack_path, registry_root)
        return {
            "tool": "install_support_pack",
            "status": res["status"],
            "pack_path": pack_path,
            "registry_root": registry_root,
            "message": res.get("message", ""),
            "errors": res.get("errors", [])
        }
    except Exception as e:
        return {
            "tool": "install_support_pack",
            "status": "error",
            "pack_path": pack_path,
            "registry_root": registry_root,
            "errors": [str(e)]
        }


def create_library_research_request(library_name: str, version: str = "unknown", package_manager: str = "unknown") -> Dict[str, Any]:
    from impact_engine.support_packs.research import create_research_request
    res = create_research_request(library_name, version, package_manager)
    return {
        "tool": "create_library_research_request",
        "status": "ok",
        "library_name": res["library_name"],
        "version": res["version"],
        "package_manager": res["package_manager"],
        "prompt": res["instructions"],
        "output_path": res["output_path"]
    }


def create_library_research_workflow(project_path: str, library_name: str, ecosystem: str) -> Dict[str, Any]:
    from impact_engine.research.workflow import init_workflow
    try:
        _verify_path_exists(project_path)
        wf_id = init_workflow(project_path, library_name, ecosystem)
        return {
            "tool": "create_library_research_workflow",
            "status": "ok",
            "workflow_id": wf_id
        }
    except Exception as e:
        return {
            "tool": "create_library_research_workflow",
            "status": "error",
            "error": str(e)
        }


def prepare_library_research_input(
    workflow_id: str,
    allow_network: bool = False,
    approval_project_path: str | None = None,
    approval_id: str | None = None,
    approval_token: str | None = None,
) -> Dict[str, Any]:
    from impact_engine.research.workflow import fetch_pages, build_input_pack
    try:
        if allow_network:
            approval_root = approval_project_path or str(Path.cwd())
            _verify_path_exists(approval_root)
            _consume_approval(
                approval_root, approval_id, approval_token, "research.fetch_pages",
                _approval_payload(executable="research-fetcher", argv=["fetch-pages", workflow_id], cwd=str(Path(approval_root).resolve()), timeout_seconds=120, network_expected=True, workflow_id=workflow_id),
            )
            fetch_pages(workflow_id)
        input_pack = build_input_pack(workflow_id)
        return {
            "tool": "prepare_library_research_input",
            "status": "ok",
            "workflow_id": workflow_id,
            "input_pack": input_pack,
            "agent_task_path": str((Path('.impact_engine/research_workflows') / workflow_id / 'agent_task.json').as_posix()),
        }
    except Exception as e:
        return {
            "tool": "prepare_library_research_input",
            "status": "error",
            "workflow_id": workflow_id,
            "error": str(e)
        }


def validate_library_research_candidate(workflow_id: str, candidate_support_pack: Dict[str, Any]) -> Dict[str, Any]:
    from impact_engine.research.workflow import validate_candidate
    try:
        res = validate_candidate(workflow_id, candidate_support_pack)
        return {
            "tool": "validate_library_research_candidate",
            "status": "ok",
            "workflow_id": workflow_id,
            "valid": res["valid"],
            "errors": res["errors"]
        }
    except Exception as e:
        return {
            "tool": "validate_library_research_candidate",
            "status": "error",
            "workflow_id": workflow_id,
            "valid": False,
            "errors": [str(e)]
        }


def install_library_support_pack(workflow_id: str, candidate_support_pack: Dict[str, Any]) -> Dict[str, Any]:
    from impact_engine.research.workflow import install_candidate
    try:
        res = install_candidate(workflow_id, candidate_support_pack)
        return {
            "tool": "install_library_support_pack",
            "status": res["status"],
            "workflow_id": workflow_id,
            "path": res.get("path"),
            "library": res.get("library"),
            "version": res.get("version"),
            "errors": res.get("errors", [])
        }
    except Exception as e:
        return {
            "tool": "install_library_support_pack",
            "status": "error",
            "workflow_id": workflow_id,
            "errors": [str(e)]
        }


def registry_status() -> Dict[str, Any]:
    from impact_engine.remote_registry import RegistryClient

    res = RegistryClient().connection_status()
    return {"tool": "registry_status", **res}


def registry_pull_support_pack(ecosystem: str, library: str) -> Dict[str, Any]:
    from impact_engine.remote_registry import RegistryClient

    return {"tool": "registry_pull_support_pack", **RegistryClient().pull_support_pack(ecosystem, library)}


def registry_create_research_request(ecosystem: str, library: str, package_name: str | None = None) -> Dict[str, Any]:
    from impact_engine.remote_registry import RegistryClient, ResearchRequestRecord

    request = ResearchRequestRecord(ecosystem=ecosystem, library_name=library, package_name=package_name)
    return {"tool": "registry_create_research_request", **RegistryClient().create_research_request(request)}


def registry_process_research_queue(
    project_path: str,
    limit: int = 20,
    allow_network: bool = False,
    approval_id: str | None = None,
    approval_token: str | None = None,
) -> Dict[str, Any]:
    from impact_engine.remote_registry.worker import process_local_research_queue

    _verify_path_exists(project_path)
    if allow_network:
        _consume_approval(
            project_path, approval_id, approval_token, "research.fetch_pages",
            _approval_payload(executable="research-fetcher", argv=["process-queue", str(limit)], cwd=str(Path(project_path).resolve()), timeout_seconds=120, network_expected=True, limit=limit),
        )
    return {
        "tool": "registry_process_research_queue",
        **process_local_research_queue(project_path=project_path, limit=limit, allow_network=allow_network),
    }


def registry_library_status(ecosystem: str, library: str) -> Dict[str, Any]:
    from impact_engine.remote_registry import RegistryClient
    return {"tool": "registry_library_status", **RegistryClient().library_status(ecosystem, library)}


def registry_approve_support_pack(pack_id: str, trust_level: str, reviewer: str, note: str | None = None) -> Dict[str, Any]:
    from impact_engine.remote_registry import RegistryClient
    return {"tool": "registry_approve_support_pack", **RegistryClient().approve_support_pack(pack_id, trust_level, reviewer, note)}


def registry_check_documentation(ecosystem: str, library: str, url: str, content_hash: str, source_type: str = "docs") -> Dict[str, Any]:
    from impact_engine.remote_registry import RegistryClient
    return {"tool": "registry_check_documentation", **RegistryClient().record_documentation_check(ecosystem, library, url, content_hash, source_type)}


def registry_simulate_lifecycle(ecosystem: str, library: str, source_url: str) -> Dict[str, Any]:
    from impact_engine.remote_registry import RegistryClient
    return {"tool": "registry_simulate_lifecycle", **RegistryClient().simulate_library_lifecycle(ecosystem, library, source_url)}


# Managed upstream tools deliberately have a separate lifecycle from graph
# adapters.  These MCP entry points let an agent inspect the exact local
# checkout and use its real CLI, while the canonical CodeSlicer graph remains
# unchanged unless an adapter is explicitly imported by the user.
def list_managed_tools(project_path: str) -> Dict[str, Any]:
    _verify_path_exists(project_path)
    runtime = ToolRuntime(project_path)
    return {
        "tool": "list_managed_tools",
        "status": "ok",
        "project_path": str(Path(project_path).resolve()),
        "tools": runtime.catalog(),
        "privacy": {"mode": "local-only", "network_used": False},
    }


def connect_managed_tool(
    project_path: str,
    tool_id: str,
    ref: str | None = None,
    approval_id: str | None = None,
    approval_token: str | None = None,
) -> Dict[str, Any]:
    _verify_path_exists(project_path)
    _consume_approval(project_path, approval_id, approval_token, "managed_tool.connect", _approval_payload(tool_id=tool_id, ref=ref or ""))
    status = ToolRuntime(project_path).connect(tool_id, confirmed=True, ref=ref)
    return {
        "tool": "connect_managed_tool",
        "status": "ok",
        "managed_tool": status,
        "privacy": {
            "mode": "local-only",
            "network_used": bool(status.get("repository", {}).get("cloned")),
            "network_action": "explicit-git-clone",
        },
    }


def read_managed_tool_docs(project_path: str, tool_id: str, query: str = "", limit: int = 40) -> Dict[str, Any]:
    _verify_path_exists(project_path)
    result = ToolRuntime(project_path).docs(tool_id, query=query, limit=limit)
    return {"tool": "read_managed_tool_docs", "status": "ok", **result}


def read_managed_tool_document(project_path: str, tool_id: str, path: str, offset: int = 0, limit_bytes: int = 128 * 1024) -> Dict[str, Any]:
    _verify_path_exists(project_path)
    result = ToolRuntime(project_path).read_document(tool_id, path, offset=offset, limit_bytes=limit_bytes)
    return {"tool": "read_managed_tool_document", "status": "ok", **result}


def configure_managed_tool_executable(project_path: str, tool_id: str, executable: str) -> Dict[str, Any]:
    _verify_path_exists(project_path)
    status = ToolRuntime(project_path).configure_executable(tool_id, executable)
    return {"tool": "configure_managed_tool_executable", "status": "ok", "managed_tool": status}


def managed_tool_help(
    project_path: str,
    tool_id: str,
    approval_id: str | None = None,
    approval_token: str | None = None,
) -> Dict[str, Any]:
    _verify_path_exists(project_path)
    runtime = ToolRuntime(project_path)
    executable = runtime.status(tool_id).get("executable")
    _consume_approval(
        project_path, approval_id, approval_token, "managed_tool.help",
        _approval_payload(executable=executable or "", argv=["--help"], cwd=str(Path(project_path).resolve()), timeout_seconds=30, network_expected=False, tool_id=tool_id),
    )
    result = runtime.help(tool_id)
    return {"tool": "managed_tool_help", "status": "ok", **result}


def run_managed_tool(
    project_path: str,
    tool_id: str,
    argv: List[str],
    workspace: str = "project",
    timeout_seconds: int = 60,
    approval_id: str | None = None,
    approval_token: str | None = None,
) -> Dict[str, Any]:
    _verify_path_exists(project_path)
    _consume_approval(
        project_path, approval_id, approval_token, "managed_tool.run",
        _approval_payload(tool_id=tool_id, argv=argv, workspace=workspace, timeout_seconds=timeout_seconds),
    )
    result = ToolRuntime(project_path).run(
        tool_id,
        argv=argv,
        confirmed=True,
        workspace=workspace,
        timeout_seconds=timeout_seconds,
    )
    return {"tool": "run_managed_tool", "status": "ok", **result}


# Stable MCP tool registry
TOOLS = [
    {
        "name": "health_check",
        "description": "Check the health of the MCP server.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "server_info",
        "description": "Get server metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "scan_plan",
        "description": "Inspect a local project without writing a graph, then return a bounded plan for analysis.",
        "inputSchema": {
            "type": "object", "properties": {"project_path": {"type": "string"}, "scope": {"type": "string", "maxLength": 4096}},
            "required": ["project_path"],
        },
    },
    {
        "name": "project_status",
        "description": "Return concise local graph/onboarding status for one project.",
        "inputSchema": {"type": "object", "properties": {"project_path": {"type": "string"}}, "required": ["project_path"]},
    },
    {
        "name": "onboard",
        "description": "Onboard a local project. Git clone or optional Graphify execution requires a matching one-time local-host approval.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string"}, "allow_network": {"type": "boolean", "default": False},
                "workspace": {"type": "string"}, "branch": {"type": "string"},
                "graphify_mode": {"type": "string", "enum": ["auto", "off", "required"], "default": "off"},
                "graphify_timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 300, "default": 120},
                "approval_id": {"type": "string"}, "approval_token": {"type": "string"},
            },
            "required": ["source"],
        },
    },
    {
        "name": "analyze_project",
        "description": "Analyze a project codebase and produce an impact graph.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Absolute path to the project directory"},
                "out_path": {"type": "string", "description": "Optional custom path to save output JSON graph"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600, "description": "Optional timeout limit in seconds"},
                "include_graph": {"type": "boolean", "default": False, "description": "Opt in to full graph payload; false returns only a compact summary."},
                "scope": {"type": "string", "maxLength": 4096},
                "memory_budget_mb": {"type": "integer", "minimum": 64, "maximum": 16384},
                "time_budget_seconds": {"type": "number", "minimum": 1, "maximum": 3600}
,"enable_remote_registry": {"type": "boolean", "default": False, "description": "Use the local SQLite/cache registry before resolution"}
,"create_research_requests": {"type": "boolean", "default": True, "description": "Create local research requests for missing support packs"}
            },
            "required": ["project_path"]
        }
    },
    {
        "name": "impact_query",
        "description": "Query the impact of changes starting from a target symbol or file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_path": {"type": "string", "description": "Path to the JSON impact graph file"},
                "target": {"type": "string", "description": "Target symbol or node ID to query"},
                "symbol": {"type": "string", "description": "Optional substring match filter for symbol"},
                "file_path": {"type": "string", "description": "Optional substring match filter for file path"},
                "direction": {"type": "string", "enum": ["upstream", "downstream", "both"], "default": "both"},
                "max_depth": {"type": "integer", "description": "Optional maximum depth of traversal"},
                "min_confidence": {"type": "number", "default": 0.0, "description": "Minimum confidence threshold"},
                "include_evidence": {"type": "boolean", "default": True}
            },
            "required": ["graph_path"]
        }
    },
    {
        "name": "explain_edge",
        "description": "Explain the reasoning and evidence behind an impact graph edge.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_path": {"type": "string", "description": "Path to the JSON impact graph file"},
                "from_symbol": {"type": "string", "description": "Source node or symbol ID"},
                "to_symbol": {"type": "string", "description": "Target node or symbol ID"},
                "kind": {"type": "string", "description": "Optional edge kind filter"}
            },
            "required": ["graph_path", "from_symbol", "to_symbol"]
        }
    },
    {
        "name": "graph_quality",
        "description": "Validate graph integrity and report dangling edges, orphans, and stable fingerprint.",
        "inputSchema": {
            "type": "object",
            "properties": {"graph_path": {"type": "string"}},
            "required": ["graph_path"]
        }
    },
    {
        "name": "impact_path",
        "description": "Find a directed evidence-bearing path between two graph nodes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_path": {"type": "string"},
                "from_symbol": {"type": "string"},
                "to_symbol": {"type": "string"},
                "max_depth": {"type": "integer", "default": 20}
            },
            "required": ["graph_path", "from_symbol", "to_symbol"]
        }
    },
    {
        "name": "pr_review",
        "description": "Create a PR impact report from git diff or provided diff text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Absolute path to the project directory"},
                "graph_path": {"type": "string", "description": "Optional path to an existing JSON impact graph"},
                "diff_text": {"type": "string", "description": "Optional unified git diff text; current git diff is used when omitted"},
                "max_depth": {"type": "integer", "default": 6},
                "min_confidence": {"type": "number", "default": 0.0},
                "max_results": {"type": "integer", "default": 10, "maximum": 10},
                "include_full_evidence": {"type": "boolean", "default": False, "description": "Explicitly return the complete impact closure for investigation."}
            },
            "required": ["project_path"]
        }
    },
    {
        "name": "review",
        "description": "Build a bounded local-first daily review report from the working-tree diff.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string"},
                "graph_path": {"type": "string"},
                "diff_text": {"type": "string"},
                "base": {"type": "string"},
                "refresh": {"type": "string", "enum": ["auto", "never", "force"]},
                "max_results": {"type": "integer", "default": 10},
                "run_tests": {"type": "string", "enum": ["none", "suggested"]},
                "deep": {"type": "boolean", "default": False},
                "entity": {"type": "string"}
            },
            "required": ["project_path"]
        }
    },
    {
        "name": "inspect",
        "description": "Explain one exact local GraphDocument entity with bounded evidence and coverage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string"},
                "entity": {"type": "string"},
                "graph_path": {"type": "string"},
                "refresh": {"type": "string", "enum": ["auto", "never", "force"], "default": "never"},
                "max_context": {"type": "integer", "default": 12}
            },
            "required": ["project_path", "entity"]
        }
    },
    {
        "name": "investigate",
        "description": "Run an explicit bounded deep impact traversal with graph diagnostics and unresolved regions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string"},
                "entity": {"type": "string"},
                "graph_path": {"type": "string"},
                "direction": {"type": "string", "enum": ["upstream", "downstream", "both"], "default": "both"},
                "depth": {"type": "integer", "default": 8},
                "runtime_validate": {"type": "boolean", "default": False},
                "approval_id": {"type": "string"}, "approval_token": {"type": "string"},
                "max_nodes": {"type": "integer", "default": 500},
                "max_edges": {"type": "integer", "default": 1000},
                "refresh": {"type": "string", "enum": ["auto", "never", "force"], "default": "never"}
            },
            "required": ["project_path", "entity"]
        }
    },
    {
        "name": "ci",
        "description": "Evaluate the shared review projection with a local CI policy; no tests or network by default. Running tests needs a one-time local-host approval.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string"},
                "base": {"type": "string"},
                "policy_path": {"type": "string"},
                "graph_path": {"type": "string"},
                "diff_text": {"type": "string"},
                "refresh": {"type": "string", "enum": ["auto", "never", "force"], "default": "auto"},
                "run_tests": {"type": "boolean", "default": False},
                "test_command": {"type": "array", "items": {"type": "string"}},
                "approval_id": {"type": "string"},
                "approval_token": {"type": "string"}
            },
            "required": ["project_path"]
        }
    },
    {
        "name": "runtime_trace",
        "description": "Run Python tests under runtime tracing and boost matched graph edges. Requires a one-time local-host approval because it starts a process.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Absolute path to the project directory"},
                "graph_path": {"type": "string", "description": "Optional path to existing JSON impact graph"},
                "out_path": {"type": "string", "description": "Optional output path for patched graph JSON"},
                "test_command": {"type": "array", "description": "Optional test command argv, e.g. ['python','-m','pytest','-q']"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600, "default": 60},
                "approval_id": {"type": "string"},
                "approval_token": {"type": "string"}
            },
            "required": ["project_path", "approval_id", "approval_token"]
        }
    },
    {
        "name": "detect_unknown_libraries",
        "description": "Scan project imports to identify third-party libraries without local support packs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Absolute path to the project directory"}
            },
            "required": ["project_path"]
        }
    },
    {
        "name": "detect_languages",
        "description": "Detect the primary languages used in the project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Absolute path to the project directory"}
            },
            "required": ["project_path"]
        }
    },
    {
        "name": "project_inventory",
        "description": "Scan project to produce an inventory of files, classes, methods, and loc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Absolute path to the project directory"}
            },
            "required": ["project_path"]
        }
    },
    {
        "name": "list_support_packs",
        "description": "List all installed local support packs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root": {"type": "string", "default": "support_packs", "description": "Optional support pack registry root"}
            }
        }
    },
    {
        "name": "validate_support_pack",
        "description": "Validate a support pack JSON file against its schema and rules.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the support pack JSON file"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "import_support_pack",
        "description": "Import a support pack file into the local registry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pack_path": {"type": "string", "description": "Path to the support pack file to import"},
                "registry_root": {"type": "string", "default": "support_packs", "description": "Local registry root"}
            },
            "required": ["pack_path"]
        }
    },
    {
        "name": "install_support_pack",
        "description": "Install a support pack file into a local registry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pack_path": {"type": "string", "description": "Path to the support pack file to install"},
                "registry_root": {"type": "string", "default": "support_packs", "description": "Local registry root"}
            },
            "required": ["pack_path"]
        }
    },
    {
        "name": "create_library_research_request",
        "description": "Generate an AI research prompt for an unknown library.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "library_name": {"type": "string", "description": "Name of the library"},
                "version": {"type": "string", "default": "unknown"},
                "package_manager": {"type": "string", "default": "unknown"}
            },
            "required": ["library_name"]
        }
    },
    {
        "name": "create_library_research_workflow",
        "description": "Initialize a workflow to research and generate a support pack.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Absolute path to the project directory"},
                "library_name": {"type": "string", "description": "Name of the library"},
                "ecosystem": {"type": "string", "description": "Target ecosystem (e.g. python, javascript)"}
            },
            "required": ["project_path", "library_name", "ecosystem"]
        }
    },
    {
        "name": "prepare_library_research_input",
        "description": "Execute web queries and prepare context for the library research AI agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Research workflow ID"},
                "allow_network": {"type": "boolean", "default": False, "description": "Requires one-time local approval"},
                "approval_project_path": {"type": "string", "description": "Existing project path that owns the approval (defaults to the MCP host cwd)"},
                "approval_id": {"type": "string"}, "approval_token": {"type": "string"}
            },
            "required": ["workflow_id"]
        }
    },
    {
        "name": "validate_library_research_candidate",
        "description": "Validate an AI-generated support pack candidate against schema/rules.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Research workflow ID"},
                "candidate_support_pack": {"type": "object", "description": "Support pack candidate dict data"}
            },
            "required": ["workflow_id", "candidate_support_pack"]
        }
    },
    {
        "name": "install_library_support_pack",
        "description": "Install verified AI support pack into the registry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Research workflow ID"},
                "candidate_support_pack": {"type": "object", "description": "Support pack candidate dict data"}
            },
            "required": ["workflow_id", "candidate_support_pack"]
        }
    },
    {
        "name": "registry_status",
"description": "Report local SQLite registry and cache status.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "registry_pull_support_pack",
"description": "Load a support pack from the local SQLite registry or cache.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ecosystem": {"type": "string"},
                "library": {"type": "string"}
            },
            "required": ["ecosystem", "library"]
        }
    },
    {
        "name": "registry_create_research_request",
        "description": "Create a registry research request for a missing library support pack.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ecosystem": {"type": "string"},
                "library": {"type": "string"},
                "package_name": {"type": "string"}
            },
            "required": ["ecosystem", "library"]
        }
    },
    {
        "name": "registry_process_research_queue",
        "description": "Prepare AI input packs for queued local registry research requests.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "allow_network": {"type": "boolean", "default": False},
                "approval_id": {"type": "string"}, "approval_token": {"type": "string"}
            },
            "required": ["project_path"]
        }
    },
    {
        "name": "registry_library_status",
        "description": "Get lifecycle status and metadata for a library.",
        "inputSchema": {"type": "object", "properties": {"ecosystem": {"type": "string"}, "library": {"type": "string"}}, "required": ["ecosystem", "library"]}
    },
    {
        "name": "registry_approve_support_pack",
        "description": "Move a support pack version to a reviewed trust level.",
        "inputSchema": {"type": "object", "properties": {"pack_id": {"type": "string"}, "trust_level": {"type": "string", "enum": ["draft", "staged", "experimental", "verified_on_fixture", "verified_on_real_project", "trusted"]}, "reviewer": {"type": "string"}, "note": {"type": "string"}}, "required": ["pack_id", "trust_level", "reviewer"]}
    },
    {
        "name": "registry_check_documentation",
        "description": "Record a documentation content hash and detect a changed source.",
        "inputSchema": {"type": "object", "properties": {"ecosystem": {"type": "string"}, "library": {"type": "string"}, "url": {"type": "string"}, "content_hash": {"type": "string"}, "source_type": {"type": "string"}}, "required": ["ecosystem", "library", "url", "content_hash"]}
    },
    {
        "name": "registry_simulate_lifecycle",
        "description": "Simulate local library registration and research request creation.",
        "inputSchema": {"type": "object", "properties": {"ecosystem": {"type": "string"}, "library": {"type": "string"}, "source_url": {"type": "string"}}, "required": ["ecosystem", "library", "source_url"]}
    }
]


# This surface is intentionally explicit.  An agent may discover and read a
# connected upstream checkout freely, but cloning and every arbitrary command
# require a separately minted one-time local-host approval.
TOOLS.extend([
    {
        "name": "request_action_approval",
        "description": "Create a pending approval for a process or network action. This MCP call cannot approve it; a local CodeSlicer host must do that separately.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string"},
                "action": {"type": "string", "enum": ["managed_tool.connect", "managed_tool.run", "managed_tool.help", "runtime_trace", "investigate.runtime_validate", "ci.run_tests", "project.onboard"]},
                "payload": {"type": "object"},
                "ttl_seconds": {"type": "integer", "minimum": 30, "maximum": 900, "default": 300},
            },
            "required": ["project_path", "action", "payload"],
        },
    },
    {
        "name": "list_managed_tools",
        "description": "List the local upstream-tool catalog and connection state for a project. No network or process is started.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_path": {"type": "string"}},
            "required": ["project_path"],
        },
    },
    {
        "name": "connect_managed_tool",
        "description": "Clone the complete upstream Git repository into private CodeSlicer storage after a matching one-time local-host approval. Does not build, install, or start it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string"},
                "tool_id": {"type": "string"},
                "ref": {"type": "string", "description": "Optional upstream Git ref to check out after cloning."},
                "approval_id": {"type": "string"},
                "approval_token": {"type": "string"},
            },
            "required": ["project_path", "tool_id", "approval_id", "approval_token"],
        },
    },
    {
        "name": "read_managed_tool_docs",
        "description": "Search documentation indexed from an already connected local upstream repository. No network access.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string"}, "tool_id": {"type": "string"},
                "query": {"type": "string"}, "limit": {"type": "integer", "default": 40},
            },
            "required": ["project_path", "tool_id"],
        },
    },
    {
        "name": "read_managed_tool_document",
        "description": "Read a page of one documentation file from an already connected local upstream repository. Continue with next_offset to read the complete file. The path must stay inside that checkout.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string"}, "tool_id": {"type": "string"}, "path": {"type": "string"},
                "offset": {"type": "integer", "default": 0}, "limit_bytes": {"type": "integer", "default": 131072},
            },
            "required": ["project_path", "tool_id", "path"],
        },
    },
    {
        "name": "configure_managed_tool_executable",
        "description": "Associate a managed tool with an existing absolute local executable. This does not execute it.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_path": {"type": "string"}, "tool_id": {"type": "string"}, "executable": {"type": "string"}},
            "required": ["project_path", "tool_id", "executable"],
        },
    },
    {
        "name": "managed_tool_help",
        "description": "Run the configured local upstream executable with --help after a matching one-time local-host approval.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_path": {"type": "string"}, "tool_id": {"type": "string"}, "approval_id": {"type": "string"}, "approval_token": {"type": "string"}},
            "required": ["project_path", "tool_id", "approval_id", "approval_token"],
        },
    },
    {
        "name": "run_managed_tool",
        "description": "Run a complete raw argv command on a configured local upstream executable. It never uses a shell and requires a matching one-time local-host approval for each invocation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string"}, "tool_id": {"type": "string"},
                "argv": {"type": "array", "items": {"type": "string"}, "description": "Arguments after the configured executable, as an argv list."},
                "workspace": {"type": "string", "enum": ["project", "tool"], "default": "project"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600, "default": 60},
                "approval_id": {"type": "string"},
                "approval_token": {"type": "string"},
            },
            "required": ["project_path", "tool_id", "argv", "approval_id", "approval_token"],
        },
    },
])


def validate_arguments(schema: dict, arguments: dict) -> str | None:
    try:
        strict_schema = dict(schema)
        # MCP tools are closed contracts: silently accepting typoed fields is
        # dangerous for action-bearing operations.
        strict_schema.setdefault("additionalProperties", False)
        Draft202012Validator(strict_schema).validate(arguments)
        return None
    except ValidationError as exc:
        location = ".".join(str(item) for item in exc.absolute_path)
        return f"{location + ': ' if location else ''}{exc.message}"


def main():
    import sys
    
    # Determine input stream
    if hasattr(sys.stdin, "buffer"):
        stdin_stream = sys.stdin.buffer
    else:
        stdin_stream = sys.stdin

    # Determine output stream
    if hasattr(sys.stdout, "buffer"):
        stdout_stream = sys.stdout.buffer
    else:
        stdout_stream = sys.stdout

    def write_response(resp_dict: dict) -> None:
        json_str = json.dumps(resp_dict) + "\n"
        try:
            stdout_stream.write(json_str.encode("utf-8"))
        except (TypeError, AttributeError):
            stdout_stream.write(json_str)
        if hasattr(stdout_stream, "flush"):
            stdout_stream.flush()
            
    # Read from buffer line by line
    for line_item in stdin_stream:
        if not line_item:
            continue
        if isinstance(line_item, bytes):
            line = line_item.decode("utf-8")
        else:
            line = line_item
            
        if not line.strip():
            continue
            
        # Parse JSON
        try:
            req = json.loads(line)
        except Exception:
            # Parse error
            resp = {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32700,
                    "message": "Parse error: Invalid JSON"
                },
                "id": None
            }
            write_response(resp)
            continue

        if not isinstance(req, dict):
            # Invalid Request
            resp = {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32600,
                    "message": "Invalid Request: Message must be a JSON object"
                },
                "id": None
            }
            write_response(resp)
            continue

        rpc_id = req.get("id")
        is_notification = ("id" not in req)
        method = req.get("method")
        params = req.get("params", {})

        if not method:
            if is_notification:
                continue
            resp = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {
                    "code": -32600,
                    "message": "Invalid Request: Missing method name"
                }
            }
            write_response(resp)
            continue

        if method == "initialize":
            if is_notification:
                continue
            resp = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "impact-engine",
                        "version": "0.5.0"
                    }
                }
            }
        elif method == "initialized":
            # initialized is a notification and must not trigger a response
            continue
        elif method == "tools/list":
            if is_notification:
                continue
            resp = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "tools": TOOLS
                }
            }
        elif method == "tools/call":
            if is_notification:
                continue
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            tool_schema = next((t for t in TOOLS if t["name"] == tool_name), None)
            if not tool_schema:
                resp = {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: Unknown tool {tool_name}"
                    }
                }
            else:
                val_err = validate_arguments(tool_schema.get("inputSchema", {}), arguments)
                if val_err:
                    resp = {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "error": {
                            "code": -32602,
                            "message": f"Invalid params: {val_err}"
                        }
                    }
                else:
                    try:
                        if tool_name == "health_check":
                            res = health_check()
                        elif tool_name == "server_info":
                            res = server_info()
                        elif tool_name == "scan_plan":
                            res = scan_plan(**arguments)
                        elif tool_name == "project_status":
                            res = project_status(**arguments)
                        elif tool_name == "onboard":
                            res = onboard(**arguments)
                        elif tool_name == "analyze_project":
                            timeout_seconds = arguments.get("timeout_seconds")
                            from impact_engine.persistence import CancellationToken
                            cancellation = CancellationToken()
                            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                            future = executor.submit(analyze_project, **arguments, cancellation=cancellation)
                            try:
                                res = future.result(timeout=timeout_seconds)
                            except concurrent.futures.TimeoutError:
                                cancellation.cancel()
                                future.cancel()
                                res = {
                                    "tool": "analyze_project", "status": "error",
                                    "path": arguments.get("project_path"),
                                    "error": f"Analysis timed out after {timeout_seconds} seconds; cancellation requested",
                                }
                            finally:
                                # Do not wait for a timed-out worker. Pipeline cancellation is
                                # cooperative and avoids the old context-manager join.
                                executor.shutdown(wait=False, cancel_futures=True)
                        elif tool_name == "impact_query":
                            if "max_depth" in arguments and arguments["max_depth"] is not None:
                                arguments["max_depth"] = min(arguments["max_depth"], 100)
                            else:
                                arguments["max_depth"] = 100
                            res = impact_query(**arguments)
                        elif tool_name == "explain_edge":
                            res = explain_edge(**arguments)
                        elif tool_name == "graph_quality":
                            res = graph_quality(**arguments)
                        elif tool_name == "impact_path":
                            res = impact_path(**arguments)
                        elif tool_name == "pr_review":
                            res = pr_review(**arguments)
                        elif tool_name == "review":
                            res = review(**arguments)
                        elif tool_name == "inspect":
                            res = inspect(**arguments)
                        elif tool_name == "investigate":
                            res = investigate(**arguments)
                        elif tool_name == "ci":
                            res = ci(**arguments)
                        elif tool_name == "runtime_trace":
                            res = runtime_trace(**arguments)
                        elif tool_name == "detect_unknown_libraries":
                            res = detect_unknown_libraries(**arguments)
                        elif tool_name == "detect_languages":
                            res = detect_languages(**arguments)
                        elif tool_name == "project_inventory":
                            res = project_inventory(**arguments)
                        elif tool_name == "list_support_packs":
                            res = list_support_packs(**arguments)
                        elif tool_name == "validate_support_pack":
                            res = validate_support_pack(**arguments)
                        elif tool_name == "import_support_pack":
                            res = import_support_pack(**arguments)
                        elif tool_name == "install_support_pack":
                            res = install_support_pack(**arguments)
                        elif tool_name == "create_library_research_request":
                            res = create_library_research_request(**arguments)
                        elif tool_name == "create_library_research_workflow":
                            res = create_library_research_workflow(**arguments)
                        elif tool_name == "prepare_library_research_input":
                            res = prepare_library_research_input(**arguments)
                        elif tool_name == "validate_library_research_candidate":
                            res = validate_library_research_candidate(**arguments)
                        elif tool_name == "install_library_support_pack":
                            res = install_library_support_pack(**arguments)
                        elif tool_name == "registry_status":
                            res = registry_status()
                        elif tool_name == "registry_pull_support_pack":
                            res = registry_pull_support_pack(**arguments)
                        elif tool_name == "registry_create_research_request":
                            res = registry_create_research_request(**arguments)
                        elif tool_name == "registry_process_research_queue":
                            res = registry_process_research_queue(**arguments)
                        elif tool_name == "registry_library_status":
                            res = registry_library_status(**arguments)
                        elif tool_name == "registry_approve_support_pack":
                            res = registry_approve_support_pack(**arguments)
                        elif tool_name == "registry_check_documentation":
                            res = registry_check_documentation(**arguments)
                        elif tool_name == "registry_simulate_lifecycle":
                            res = registry_simulate_lifecycle(**arguments)
                        elif tool_name == "request_action_approval":
                            res = request_action_approval(**arguments)
                        elif tool_name == "list_managed_tools":
                            res = list_managed_tools(**arguments)
                        elif tool_name == "connect_managed_tool":
                            res = connect_managed_tool(**arguments)
                        elif tool_name == "read_managed_tool_docs":
                            res = read_managed_tool_docs(**arguments)
                        elif tool_name == "read_managed_tool_document":
                            res = read_managed_tool_document(**arguments)
                        elif tool_name == "configure_managed_tool_executable":
                            res = configure_managed_tool_executable(**arguments)
                        elif tool_name == "managed_tool_help":
                            res = managed_tool_help(**arguments)
                        elif tool_name == "run_managed_tool":
                            res = run_managed_tool(**arguments)
                        else:
                            raise ValueError(f"Unknown tool: {tool_name}")

                        tool_error = isinstance(res, dict) and res.get("status") in {"error", "failed", "timeout", "cancelled"}
                        resp = {
                            "jsonrpc": "2.0",
                            "id": rpc_id,
                            "result": {
                                "isError": tool_error,
                                "structuredContent": res,
                                "content": [
                                    {
                                        "type": "text",
                                        "text": json.dumps(res)
                                    }
                                ]
                            }
                        }
                    except Exception as e:
                        resp = {
                            "jsonrpc": "2.0",
                            "id": rpc_id,
                            "error": {
                                "code": -32603,
                                "message": f"Internal error: {str(e)}"
                            }
                        }
        else:
            if is_notification:
                continue
            resp = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }

        write_response(resp)


if __name__ == "__main__":
    main()
