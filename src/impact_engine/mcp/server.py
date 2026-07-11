"""MCP server implementation. Stage 8 complete.

Exposes a robust local MCP stdio runtime wrapper on top of core tools.
"""
import json
import ast
import sys
from pathlib import Path
from typing import Dict, Any, List

from impact_engine.models import GraphDocument
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.precision import resolve_precision
from impact_engine.impact import impact_query as impact_query_core, explain_edge as explain_edge_core
from impact_engine.support_packs.registry import list_local_support_packs, validate_support_pack_file, import_support_pack_file


def _verify_path_exists(p_str: str) -> None:
    if not p_str:
        raise ValueError("Path argument cannot be empty")
    p = Path(p_str).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Path does not exist: {p_str}")


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
        "version": "0.4.0",
        "protocol_version": "2024-11-05"
    }


def analyze_project(
    project_path: str,
    out_path: str | None = None,
    timeout_seconds: int | None = None,
    enable_remote_registry: bool = False,
    create_research_requests: bool = True,
) -> Dict[str, Any]:
    from impact_engine.analysis.pipeline import analyze_project_core
    try:
        _verify_path_exists(project_path)
        res = analyze_project_core(
            project_path,
            out_path=out_path,
            enable_remote_registry=enable_remote_registry,
            create_research_requests=create_research_requests,
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
            "graph": res.get("graph", {})
        }
    except Exception as e:
        return {
            "tool": "analyze_project",
            "status": "error",
            "path": project_path,
            "error": str(e)
        }


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
        )
        return {"tool": "pr_review", "status": "ok", "project_path": project_path, "result": result}
    except Exception as e:
        return {"tool": "pr_review", "status": "error", "project_path": project_path, "error": str(e), "result": None}


def runtime_trace(
    project_path: str,
    graph_path: str | None = None,
    out_path: str | None = None,
    test_command: list[str] | None = None,
    timeout_seconds: int = 60,
) -> Dict[str, Any]:
    from impact_engine.runtime_trace import runtime_trace_project_core
    try:
        _verify_path_exists(project_path)
        if graph_path:
            _verify_path_exists(graph_path)
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


def prepare_library_research_input(workflow_id: str, allow_network: bool = False) -> Dict[str, Any]:
    from impact_engine.research.workflow import fetch_pages, build_input_pack
    try:
        if allow_network:
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
) -> Dict[str, Any]:
    from impact_engine.remote_registry.worker import process_local_research_queue

    _verify_path_exists(project_path)
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
        "name": "analyze_project",
        "description": "Analyze a project codebase and produce an impact graph.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Absolute path to the project directory"},
                "out_path": {"type": "string", "description": "Optional custom path to save output JSON graph"},
                "timeout_seconds": {"type": "integer", "description": "Optional timeout limit in seconds"}
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
                "min_confidence": {"type": "number", "default": 0.0}
            },
            "required": ["project_path"]
        }
    },
    {
        "name": "runtime_trace",
        "description": "Run Python tests under runtime tracing and boost matched graph edges.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Absolute path to the project directory"},
                "graph_path": {"type": "string", "description": "Optional path to existing JSON impact graph"},
                "out_path": {"type": "string", "description": "Optional output path for patched graph JSON"},
                "test_command": {"type": "array", "description": "Optional test command argv, e.g. ['python','-m','pytest','-q']"},
                "timeout_seconds": {"type": "integer", "default": 60}
            },
            "required": ["project_path"]
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
                "allow_network": {"type": "boolean", "default": False, "description": "Explicitly allow network fetches"}
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
                "allow_network": {"type": "boolean", "default": False}
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


def validate_arguments(schema: dict, arguments: dict) -> str | None:
    if not isinstance(arguments, dict):
        return "Arguments must be an object"
        
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    
    # Check required properties
    for req_field in required:
        if req_field not in arguments:
            return f"Missing required parameter: {req_field}"
            
    # Check for unexpected properties
    for arg_name in arguments:
        if arg_name not in properties:
            return f"Unexpected parameter: {arg_name}"
            
    # Check types and enums
    for arg_name, arg_val in arguments.items():
        prop_schema = properties.get(arg_name, {})
        prop_type = prop_schema.get("type")
        
        # Check type
        if prop_type == "string":
            if not isinstance(arg_val, str):
                return f"Parameter '{arg_name}' must be a string"
        elif prop_type == "integer":
            if isinstance(arg_val, bool) or not isinstance(arg_val, int):
                return f"Parameter '{arg_name}' must be an integer"
        elif prop_type == "number":
            if isinstance(arg_val, bool) or not isinstance(arg_val, (int, float)):
                return f"Parameter '{arg_name}' must be a number"
        elif prop_type == "boolean":
            if not isinstance(arg_val, bool):
                return f"Parameter '{arg_name}' must be a boolean"
        elif prop_type == "object":
            if not isinstance(arg_val, dict):
                return f"Parameter '{arg_name}' must be an object"
        elif prop_type == "array":
            if not isinstance(arg_val, list):
                return f"Parameter '{arg_name}' must be an array"
                
        # Check enum
        if "enum" in prop_schema:
            if arg_val not in prop_schema["enum"]:
                allowed = ", ".join(repr(x) for x in prop_schema["enum"])
                return f"Parameter '{arg_name}' must be one of: {allowed}"
                
    return None


def main():
    import sys
    import concurrent.futures
    
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
                        "version": "0.4.0"
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
                        elif tool_name == "analyze_project":
                            timeout_seconds = arguments.get("timeout_seconds")
                            # Run under concurrent thread executor to support timeout constraints
                            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                                future = executor.submit(analyze_project, **arguments)
                                try:
                                    res = future.result(timeout=timeout_seconds)
                                except concurrent.futures.TimeoutError:
                                    res = {
                                        "tool": "analyze_project",
                                        "status": "error",
                                        "path": arguments.get("project_path"),
                                        "error": f"Analysis timed out after {timeout_seconds} seconds"
                                    }
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
                        else:
                            raise ValueError(f"Unknown tool: {tool_name}")

                        resp = {
                            "jsonrpc": "2.0",
                            "id": rpc_id,
                            "result": {
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
