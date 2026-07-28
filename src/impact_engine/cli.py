"""CLI implementation. Stage 6 complete."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from impact_engine.models import GraphDocument
from impact_engine.extractors.python_ast import extract_project
from impact_engine.resolution.precision import resolve_precision
from impact_engine.impact import impact_query, explain_edge


def _print_json(data: object) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    # Keep machine-readable stdout ASCII-safe on Windows; UTF-8 remains in
    # graph artifacts and the visual API, while subprocess clients can decode
    # JSON reliably under the active console code page.
    print(json.dumps(data, indent=2, ensure_ascii=True))


def _print_result(data: object, json_output: bool, human: str | None = None) -> None:
    if json_output:
        _print_json(data)
    elif human is not None:
        print(human)


def _attach_runtime_contract(result: dict, *, scope: str | None = None) -> dict:
    """Expose the stable cache/progress/coverage envelope for JSON clients."""
    graph = result.get("graph") if isinstance(result, dict) else None
    metadata = graph.get("metadata", {}) if isinstance(graph, dict) else {}
    cache = dict(metadata.get("cache") or metadata.get("incremental_cache") or result.get("cache") or {})
    status = cache.get("status")
    if status not in {"hit", "miss", "partial", "invalidated"}:
        status = "hit" if cache.get("analysis_reused") or cache.get("cache_hit_rate") == 1.0 else "miss"
    result["cache"] = {
        "status": status,
        "reason": cache.get("reason") or cache.get("cache_reason") or "analysis_completed",
        "branch": cache.get("branch"),
        "snapshot": cache.get("snapshot") or cache.get("source_snapshot_hash"),
        "scope": scope or cache.get("scope") or cache.get("scan_scope") or ".",
        "plugins": cache.get("plugins") or metadata.get("plugin_selection_plan", {}).get("selected", []),
        "files_reused": int(cache.get("files_reused", 0) or 0),
        "files_reanalyzed": int(cache.get("files_reanalyzed", 0) or 0),
        "facts_reused": int(cache.get("facts_reused", 0) or 0),
        "facts_rebuilt": int(cache.get("facts_rebuilt", 0) or 0),
    }
    progress = result.get("progress") or metadata.get("analysis_progress") or {}
    current = progress.get("current", progress) if isinstance(progress, dict) else {}
    result["progress"] = {
        "phase": current.get("phase") or current.get("stage", "unknown"),
        "completed": current.get("completed", current.get("processed", 0)),
        "total": current.get("total", 0),
        "elapsed_seconds": current.get("elapsed_seconds", 0.0),
        "eta_seconds": current.get("eta_seconds"),
        "cancellable": current.get("cancellable", True),
    }
    result["coverage"] = metadata.get("resolution_coverage", result.get("coverage", []))
    result["incomplete"] = bool(result.get("incomplete", False) or metadata.get("incomplete", False))
    return result


def _project_graph_path(project_path: str) -> str:
    """Return the canonical project-local graph destination.

    Analysis artifacts must never appear in the caller's current directory:
    that both pollutes the workspace and makes a later review treat the graph
    as an externally supplied, unverified file.
    """
    return str(Path(project_path).expanduser().resolve() / ".impact_engine" / "graph.json")


def _load_support_pack_candidate(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _registry_pack_path(pack: dict, root: str | Path = "support_packs") -> Path:
    language = str(pack.get("language") or pack.get("ecosystem") or "unknown").lower()
    library = str(pack.get("library") or "unknown").lower()
    return Path(root) / language / library / "support_pack.json"


def _save_staged_support_pack(pack: dict, workflow_id: str | None = None, root: str | Path = "support_packs") -> Path:
    language = str(pack.get("language") or pack.get("ecosystem") or "unknown").lower()
    library = str(pack.get("library") or "unknown").lower()
    stage_id = workflow_id or "manual"
    dest = Path(root) / ".staging" / language / library / stage_id / "support_pack.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
    return dest


def _doctor_report(full: bool = False) -> dict:
    from impact_engine.extractors.tree_sitter.adapter import is_tree_sitter_available
    from impact_engine.support_packs.store import SupportPackStore

    checks = []
    tree_sitter_ok = is_tree_sitter_available()
    checks.append({
        "name": "tree_sitter",
        "status": "ok" if tree_sitter_ok else "warning",
        "message": "Native tree-sitter runtime is available" if tree_sitter_ok else "Tree-sitter unavailable; polyglot extraction may degrade",
    })

    support_pack_count = len(SupportPackStore().list_packs())
    checks.append({
        "name": "support_packs",
        "status": "ok",
        "message": f"{support_pack_count} support packs installed",
    })

    research_dir = Path(".impact_engine/research_workflows")
    checks.append({
        "name": "research_workspace",
        "status": "ok" if research_dir.exists() else "info",
        "message": str(research_dir.resolve()) if research_dir.exists() else "Research workspace will be created on first workflow",
    })
    if full:
        from impact_engine.support_packs.paths import builtin_support_packs_root
        from impact_engine.local_api import default_frontend_dir
        packs = builtin_support_packs_root()
        required_packs = [packs / "python" / name / "support_pack.json" for name in ("fastapi", "sqlalchemy")]
        checks.append({
            "name": "bundled_framework_support_packs",
            "status": "ok" if all(path.is_file() for path in required_packs) else "error",
            "message": str(packs) if all(path.is_file() for path in required_packs) else "Built-in FastAPI/SQLAlchemy support packs are missing from this installation",
        })
        frontend = Path(default_frontend_dir())
        checks.append({
            "name": "bundled_frontend",
            "status": "ok" if (frontend / "index.html").is_file() and (frontend / "app.js").is_file() else "error",
            "message": str(frontend),
        })

    statuses = {item["status"] for item in checks}
    overall = "error" if "error" in statuses else ("warning" if "warning" in statuses else "ok")
    return {"status": overall, "checks": checks}


def _qa_run(projects_root: str, out_dir: str | None = None) -> dict:
    from impact_engine.qa import run_qa_matrix

    return run_qa_matrix(projects_root, out_dir)


def _researcher_pro_root() -> Path:
    configured = os.environ.get("IMPACT_RESEARCHER_PRO_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    # The researcher is an optional sibling project, kept outside the engine repo.
    return Path(__file__).resolve().parents[3] / "ai_library_researcher_pro"


def _run_researcher_pro(args: argparse.Namespace) -> dict:
    root = _researcher_pro_root()
    if not root.exists():
        raise FileNotFoundError(f"ai_library_researcher_pro is not installed at {root}")
    cmd = [
        sys.executable,
        "-m",
        "ai_library_researcher_pro.cli",
        "--storage-root",
        str(Path.cwd()),
        "run",
        "--library",
        args.library,
        "--ecosystem",
        args.ecosystem,
        "--project-path",
        args.project_path,
        "--json",
    ]
    if args.allow_network:
        cmd.append("--allow-network")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(cmd, cwd=root, env=env, timeout=120, capture_output=True, text=True)
    if result.returncode not in {0, 2}:
        raise RuntimeError(result.stderr or result.stdout or f"researcher-pro failed with exit code {result.returncode}")
    data = json.loads(result.stdout)
    data["researcher"] = "ai_library_researcher_pro"
    data["exit_code"] = result.returncode
    if getattr(args, "install_draft", False) and data.get("support_pack_path"):
        from impact_engine.research.pro_adapter import adapt_researcher_pro_draft_file
        from impact_engine.support_packs.store import SupportPackStore

        adapted = adapt_researcher_pro_draft_file(data["support_pack_path"])
        target_path = _registry_pack_path(adapted)
        if not getattr(args, "confirm_install", False):
            staged_path = _save_staged_support_pack(adapted, data.get("workflow_id"))
            data["install_result"] = {
                "status": "staged",
                "valid": True,
                "path": str(staged_path.as_posix()),
                "target_path": str(target_path.as_posix()),
                "message": "Draft staged. Re-run with --confirm-install to install into the main registry.",
            }
        elif target_path.exists() and not getattr(args, "overwrite", False):
            staged_path = _save_staged_support_pack(adapted, data.get("workflow_id"))
            data["install_result"] = {
                "status": "blocked_existing_pack",
                "valid": False,
                "path": str(staged_path.as_posix()),
                "target_path": str(target_path.as_posix()),
                "errors": [f"Support pack already exists: {target_path.as_posix()}"],
                "message": "Existing pack was not overwritten. Use --overwrite with --confirm-install if replacement is intentional.",
            }
        else:
            install_result = SupportPackStore().validate_and_save_pack(adapted)
            install_result["status"] = "installed" if install_result.get("valid") else "error"
            data["install_result"] = install_result
    return data


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="impact-engine")
    parser.add_argument("--json", action="store_true", help="Output raw JSON results")
    sub = parser.add_subparsers(dest="command")

    analyze = sub.add_parser("analyze")
    analyze.add_argument("path")
    analyze.add_argument("--out", default=None)
    analyze.add_argument("--local-registry", dest="remote_registry", action="store_true", help="Use the local SQLite registry")
    analyze.add_argument("--no-research-requests", action="store_true")
    analyze.add_argument("--graphify", default=None, help="Optional Graphify graph.json to normalize and merge")
    analyze.add_argument("--use-scan-plan", action="store_true", help="Create/reuse .impact_engine/scan_plan.json before analysis")
    analyze.add_argument("--scope", default=None, help="Workspace/package scope to analyze")
    analyze.add_argument("--no-daemon", action="store_true", help="Do not use the local daemon owner")

    onboard = sub.add_parser("onboard", help="Connect a local project or explicit Git URL and build separate CodeSlicer/Graphify graphs")
    onboard.add_argument("source", help="Existing local project directory or Git URL")
    onboard.add_argument("--allow-network", action="store_true", help="Explicitly allow git clone when source is a URL")
    onboard.add_argument("--workspace", default=None, help="Local directory for a URL clone; defaults to ~/.codeslicer/projects")
    onboard.add_argument("--branch", default=None, help="Optional branch for a Git URL clone")
    onboard.add_argument("--graphify", choices=["auto", "off", "required"], default="auto", help="Build a separate optional Graphify architecture graph")
    onboard.add_argument("--graphify-timeout", type=int, default=120)
    onboard.add_argument("--out", default=None, help="Optional copy of the onboarding JSON report")

    scan_plan = sub.add_parser("scan-plan", help="Plan the files and directories that will be analyzed")
    scan_plan.add_argument("path")
    scan_plan.add_argument("--json", action="store_true", dest="local_json")

    visualize = sub.add_parser("visualize")
    visualize.add_argument("graph", help="Path to graph.json")
    visualize.add_argument("--out", default=None, help="Output HTML path")

    compare = sub.add_parser("visualize-compare")
    compare.add_argument("impact_graph", help="Impact Engine graph.json")
    compare.add_argument("graphify_graph", help="Graphify graph.json")
    compare.add_argument("--out", default="graph_comparison.html", help="Output HTML path")

    incremental = sub.add_parser("analyze-incremental")
    incremental.add_argument("path")
    incremental.add_argument("--out", default=None)
    incremental.add_argument("--snapshot", default=None)
    incremental.add_argument("--changed", action="append", default=None)
    incremental.add_argument("--scope", default=None)
    incremental.add_argument("--no-daemon", action="store_true")

    watch = sub.add_parser("watch")
    watch.add_argument("path")
    watch.add_argument("--out", default=None)
    watch.add_argument("--interval", type=float, default=1.0)
    watch.add_argument("--iterations", type=int, default=1)
    watch.add_argument("--scope", default=None)
    watch.add_argument("--no-daemon", action="store_true")

    daemon = sub.add_parser("daemon", help="Manage the local persistent analysis owner")
    daemon_sub = daemon.add_subparsers(dest="daemon_command")
    daemon_start = daemon_sub.add_parser("start")
    daemon_start.add_argument("project")
    daemon_status_parser = daemon_sub.add_parser("status")
    daemon_status_parser.add_argument("project")
    daemon_stop = daemon_sub.add_parser("stop")
    daemon_stop.add_argument("project")

    adapters = sub.add_parser("adapters", help="Manage optional local evidence adapters")
    adapters_sub = adapters.add_subparsers(dest="adapter_command")
    adapters_list = adapters_sub.add_parser("list")
    adapters_list.add_argument("project")
    adapters_list.add_argument("--json", action="store_true", dest="local_json")
    adapters_preflight = adapters_sub.add_parser("preflight", help="Show the explicit local setup action for every optional adapter")
    adapters_preflight.add_argument("project")
    adapters_preflight.add_argument("adapter_id", nargs="?", default=None)
    adapters_preflight.add_argument("--json", action="store_true", dest="local_json")
    adapters_native = adapters_sub.add_parser("native", help="Discover or explicitly run an allowlisted local upstream-tool operation")
    adapters_native.add_argument("project")
    adapters_native.add_argument("adapter_id", choices=["graphify", "codegraph", "gortex", "joern", "openapi", "asyncapi", "scip", "cyclonedx", "spdx", "sarif"])
    adapters_native.add_argument("operation", nargs="?", default="profile", help="profile, probe, index, sync, status, query, context, impact, callers, callees, affected, refresh, or recipes")
    adapters_native.add_argument("--query", default="", help="Required by native query operations; never interpreted by a shell")
    adapters_native.add_argument("--confirm", action="store_true", help="Explicitly allow an operation that can create local tool state")
    adapters_native.add_argument("--timeout-seconds", type=int, default=60)
    adapters_native.add_argument("--json", action="store_true", dest="local_json")
    adapters_status = adapters_sub.add_parser("status", help="Show one optional adapter status")
    adapters_status.add_argument("project")
    adapters_status.add_argument("adapter_id")
    adapters_status.add_argument("--json", action="store_true", dest="local_json")
    adapters_import = adapters_sub.add_parser("import", help="Import one explicit local artifact for any artifact-backed adapter")
    adapters_import.add_argument("project")
    adapters_import.add_argument("adapter_id")
    adapters_import.add_argument("artifact")
    adapters_import.add_argument("--enable", action="store_true", help="Enable only after the local artifact passes validation")
    adapters_import.add_argument("--json", action="store_true", dest="local_json")
    adapters_import_scip = adapters_sub.add_parser("import-scip")
    adapters_import_scip.add_argument("project")
    adapters_import_scip.add_argument("artifact")
    adapters_import_scip.add_argument("--json", action="store_true", dest="local_json")
    adapters_enable = adapters_sub.add_parser("enable")
    adapters_enable.add_argument("project")
    adapters_enable.add_argument("adapter_id")
    adapters_enable.add_argument("--json", action="store_true", dest="local_json")
    adapters_disable = adapters_sub.add_parser("disable")
    adapters_disable.add_argument("project")
    adapters_disable.add_argument("adapter_id")
    adapters_disable.add_argument("--json", action="store_true", dest="local_json")
    adapters_verify_scip = adapters_sub.add_parser("verify-scip", help="Verify explicit local SCIP golden artifacts")
    adapters_verify_scip.add_argument("corpus", nargs="?", default=None, help="Golden corpus directory (default: repository tests/fixtures/scip/golden)")
    adapters_verify_scip.add_argument("--no-lint", action="store_true", help="Skip the official scip lint subprocess")
    adapters_verify_scip.add_argument("--json", action="store_true", dest="local_json")
    adapters_lsp = adapters_sub.add_parser("lsp", help="Configure and query an explicitly selected local Language Server")
    lsp_sub = adapters_lsp.add_subparsers(dest="lsp_command")
    lsp_status = lsp_sub.add_parser("status")
    lsp_status.add_argument("project")
    lsp_status.add_argument("--json", action="store_true", dest="local_json")
    lsp_preflight = lsp_sub.add_parser("preflight", help="Inspect local semantic readiness without starting a server")
    lsp_preflight.add_argument("project")
    lsp_preflight.add_argument("--compile-commands", default=None, help="Absolute local compilation database path")
    lsp_preflight.add_argument("--json", action="store_true", dest="local_json")
    lsp_configure = lsp_sub.add_parser("configure")
    lsp_configure.add_argument("project")
    lsp_configure.add_argument("--executable", required=True, help="Absolute local LSP or official agent-lsp executable")
    lsp_configure.add_argument("--workspace-root", action="append", required=True, dest="workspace_roots", help="Absolute allowed workspace root; repeat for multiple roots")
    lsp_configure.add_argument("--arg", action="append", default=[], dest="arguments", help="Optional local process argument; repeat as needed")
    lsp_configure.add_argument("--timeout-ms", type=int, default=5000)
    lsp_configure.add_argument("--backend", choices=["native_stdio", "agent_lsp", "auto"], default="native_stdio")
    lsp_configure.add_argument("--server-family", default="unknown")
    lsp_configure.add_argument("--compile-commands", default=None, help="Absolute local compilation database path")
    lsp_configure.add_argument("--json", action="store_true", dest="local_json")
    lsp_probe = lsp_sub.add_parser("probe")
    lsp_probe.add_argument("project")
    lsp_probe.add_argument("--json", action="store_true", dest="local_json")
    lsp_start = lsp_sub.add_parser("start", help="Start or reuse the configured official Agent-LSP runtime")
    lsp_start.add_argument("project")
    lsp_start.add_argument("--json", action="store_true", dest="local_json")
    lsp_disable = lsp_sub.add_parser("disable")
    lsp_disable.add_argument("project")
    lsp_disable.add_argument("--json", action="store_true", dest="local_json")
    lsp_query = lsp_sub.add_parser("query", help="Explicitly request one bounded LSP semantic operation")
    lsp_query.add_argument("project")
    lsp_query.add_argument("--method", required=True, choices=["documentSymbol", "definition", "references", "implementation", "declaration", "typeDefinition", "hover", "workspace/symbol", "callHierarchy", "typeHierarchy", "diagnostics"])
    lsp_query.add_argument("--file", default=None)
    lsp_query.add_argument("--line", type=int, default=0)
    lsp_query.add_argument("--character", type=int, default=0)
    lsp_query.add_argument("--query", default="")
    lsp_query.add_argument("--entity-id", default=None)
    lsp_query.add_argument("--graph", default=None)
    lsp_query.add_argument("--timeout-ms", type=int, default=None)
    lsp_query.add_argument("--json", action="store_true", dest="local_json")
    for boundary_id in ("openapi", "asyncapi"):
        boundary_parser = adapters_sub.add_parser(boundary_id, help=f"Manage the local {boundary_id} boundary overlay")
        boundary_sub = boundary_parser.add_subparsers(dest="boundary_command")
        boundary_import = boundary_sub.add_parser("import")
        boundary_import.add_argument("project")
        boundary_import.add_argument("spec")
        boundary_import.add_argument("--json", action="store_true", dest="local_json")
        for action in ("enable", "disable", "status"):
            boundary_action = boundary_sub.add_parser(action)
            boundary_action.add_argument("project")
            boundary_action.add_argument("--json", action="store_true", dest="local_json")
    otel_parser = adapters_sub.add_parser("otel", help="Manage the local OpenTelemetry runtime evidence overlay")
    otel_sub = otel_parser.add_subparsers(dest="otel_command")
    otel_import = otel_sub.add_parser("import")
    otel_import.add_argument("project")
    otel_import.add_argument("trace")
    otel_import.add_argument("--json", action="store_true", dest="local_json")
    for action in ("enable", "disable", "status"):
        otel_action = otel_sub.add_parser(action)
        otel_action.add_argument("project")
        otel_action.add_argument("--json", action="store_true", dest="local_json")
    for security_id in ("cyclonedx", "spdx", "sarif"):
        security_parser = adapters_sub.add_parser(security_id, help=f"Manage the local {security_id} security evidence overlay")
        security_sub = security_parser.add_subparsers(dest="security_command")
        security_import = security_sub.add_parser("import")
        security_import.add_argument("project")
        security_import.add_argument("report")
        security_import.add_argument("--json", action="store_true", dest="local_json")
        for action in ("enable", "disable", "status"):
            security_action = security_sub.add_parser(action)
            security_action.add_argument("project")
            security_action.add_argument("--json", action="store_true", dest="local_json")
    for external_graph_id in ("graphify", "codegraph"):
        external_graph_parser = adapters_sub.add_parser(external_graph_id, help=f"Manage the local {external_graph_id} external graph overlay")
        external_graph_sub = external_graph_parser.add_subparsers(dest="external_graph_command")
        external_graph_import = external_graph_sub.add_parser("import")
        external_graph_import.add_argument("project")
        external_graph_import.add_argument("artifact")
        external_graph_import.add_argument("--json", action="store_true", dest="local_json")
        for action in ("enable", "disable", "status"):
            external_graph_action = external_graph_sub.add_parser(action)
            external_graph_action.add_argument("project")
            external_graph_action.add_argument("--json", action="store_true", dest="local_json")
    joern_parser = adapters_sub.add_parser("joern", help="Manage the explicit local Joern CPG/data-flow overlay")
    joern_sub = joern_parser.add_subparsers(dest="joern_command")
    joern_import = joern_sub.add_parser("import")
    joern_import.add_argument("project")
    joern_import.add_argument("artifact")
    joern_import.add_argument("--json", action="store_true", dest="local_json")
    joern_convert = joern_sub.add_parser("convert", help="Convert explicit local native GraphSON/CPGQL output to CodeSlicer interchange")
    joern_convert.add_argument("graphson")
    joern_convert.add_argument("--project", required=True)
    joern_convert.add_argument("--output", required=True)
    joern_convert.add_argument("--json", action="store_true", dest="local_json")
    joern_benchmark = joern_sub.add_parser("benchmark", help="Run a bounded local Joern quality benchmark")
    joern_benchmark.add_argument("project")
    joern_benchmark.add_argument("artifact")
    joern_benchmark.add_argument("--case-file", default=None, help="Absolute golden-case JSON file")
    joern_benchmark.add_argument("--case-id", default=None)
    joern_benchmark.add_argument("--output", default=None, help="Absolute aggregate report path")
    joern_benchmark.add_argument("--entity", default=None)
    joern_benchmark.add_argument("--max-nodes", type=int, default=80)
    joern_benchmark.add_argument("--max-edges", type=int, default=160)
    joern_benchmark.add_argument("--max-paths", type=int, default=40)
    joern_benchmark.add_argument("--json", action="store_true", dest="local_json")
    joern_discover = joern_sub.add_parser("discover", help="Find explicit local Joern interchange exports")
    joern_discover.add_argument("roots", nargs="+")
    joern_discover.add_argument("--max-files", type=int, default=5000)
    joern_discover.add_argument("--timeout", type=float, default=10.0, help="Maximum discovery time in seconds")
    joern_discover.add_argument("--include-synthetic", action="store_true", help="Include tests/fixtures and corpus directories")
    joern_discover.add_argument("--json", action="store_true", dest="local_json")
    for action in ("enable", "disable", "status"):
        joern_action = joern_sub.add_parser(action)
        joern_action.add_argument("project")
        joern_action.add_argument("--json", action="store_true", dest="local_json")

    quality = sub.add_parser("graph-quality")
    quality.add_argument("graph")

    unknown_regions = sub.add_parser(
        "unknown-regions",
        help="Prepare or validate evidence-gated tasks for unresolved graph regions",
    )
    unknown_regions.add_argument("project_path", nargs="?", default=None)
    unknown_regions.add_argument("--graph", default=None, help="Existing graph.json instead of re-analyzing")
    unknown_regions.add_argument("--out", default=None, help="Task JSON output path")
    unknown_regions.add_argument("--json", action="store_true", dest="local_json", help="Output JSON")

    impact = sub.add_parser("impact")
    impact.add_argument("graph_positional", nargs="?", default=None, metavar="graph.json")
    impact.add_argument("--graph", default=None)
    # Old syntax target, or new symbol/file
    impact.add_argument("--target", default=None)
    impact.add_argument("--symbol", default=None)
    impact.add_argument("--file", default=None, dest="file_arg")
    impact.add_argument("--direction", default="both", choices=["upstream", "downstream", "both"])
    impact.add_argument("--depth", type=int, default=None)
    impact.add_argument("--min-confidence", type=float, default=0.0)
    impact.add_argument("--full-context-tokens", type=int, default=None,
                        help="Measured tokens in the full repository context")
    impact.add_argument("--selected-context-tokens", type=int, default=None,
                        help="Measured tokens in the graph-selected context")

    pr_review = sub.add_parser("pr-review")
    pr_review.add_argument("project_path")
    pr_review.add_argument("--graph", default=None)
    pr_review.add_argument("--diff-file", default=None)
    pr_review.add_argument("--depth", type=int, default=6)
    pr_review.add_argument("--min-confidence", type=float, default=0.0)
    pr_review.add_argument("--max-results", type=int, default=10, help="Maximum concise impact entities (capped at 10)")
    pr_review.add_argument("--full-evidence", action="store_true", help="Explicitly include the complete impact closure for investigation")

    review = sub.add_parser("review", help="Build a compact local-first daily review brief")
    review.add_argument("project_path")
    review.add_argument("--base", default=None)
    review.add_argument("--deep", action="store_true")
    review.add_argument("--entity", default=None, help="Entity to inspect in explicit deep mode")
    review.add_argument("--graph", default=None)
    review.add_argument("--diff-file", default=None)
    review.add_argument("--refresh", choices=["auto", "never", "force"], default="auto")
    review.add_argument("--max-results", type=int, default=10)
    review.add_argument("--run-tests", choices=["none", "suggested"], default="suggested")
    review.add_argument("--json", action="store_true", dest="local_json")
    review.add_argument("--scope", default=None)
    review.add_argument("--no-daemon", action="store_true")

    inspect = sub.add_parser("inspect", help="Explain one local graph entity")
    inspect.add_argument("project_path")
    inspect.add_argument("--entity", required=True)
    inspect.add_argument("--graph", default=None)
    inspect.add_argument("--refresh", choices=["auto", "never", "force"], default="never")
    inspect.add_argument("--max-context", type=int, default=12)
    inspect.add_argument("--json", action="store_true", dest="local_json")

    investigate = sub.add_parser("investigate", help="Run an explicit bounded deep graph investigation")
    investigate.add_argument("project_path")
    investigate.add_argument("--entity", required=True)
    investigate.add_argument("--graph", default=None)
    investigate.add_argument("--direction", choices=["upstream", "downstream", "both"], default="both")
    investigate.add_argument("--depth", type=int, default=8)
    investigate.add_argument("--runtime-validate", action="store_true")
    investigate.add_argument("--max-nodes", type=int, default=500)
    investigate.add_argument("--max-edges", type=int, default=1000)
    investigate.add_argument("--refresh", choices=["auto", "never", "force"], default="never")
    investigate.add_argument("--json", action="store_true", dest="local_json")

    ci = sub.add_parser("ci", help="Evaluate the review projection with an optional CI policy")
    ci.add_argument("project_path")
    ci.add_argument("--base", default=None)
    ci.add_argument("--policy", default=None)
    ci.add_argument("--graph", default=None)
    ci.add_argument("--diff-file", default=None)
    ci.add_argument("--refresh", choices=["auto", "never", "force"], default="auto")
    ci.add_argument("--format", choices=["json", "sarif"], default="json")
    ci.add_argument("--out", default=None)
    ci.add_argument("--run-tests", action="store_true", help="Explicitly run the selected project test command")
    ci.add_argument("--test-command", nargs="+", default=None, help="Explicit test command argv; only used with --run-tests")
    ci.add_argument("--json", action="store_true", dest="local_json")

    runtime_trace = sub.add_parser("runtime-trace")
    runtime_trace.add_argument("project_path")
    runtime_trace.add_argument("--graph", default=None)
    runtime_trace.add_argument("--out", default=None)
    runtime_trace.add_argument("--timeout", type=int, default=60)

    explain = sub.add_parser("explain-edge")
    explain.add_argument("graph_positional", nargs="?", default=None, metavar="graph.json")
    explain.add_argument("--graph", default=None)
    explain.add_argument("--from", required=True, dest="from_node")
    explain.add_argument("--to", required=True, dest="to_node")
    explain.add_argument("--kind", default=None)

    # detect-languages
    det_lang = sub.add_parser("detect-languages")
    det_lang.add_argument("project_path")

    # inventory
    inv = sub.add_parser("inventory")
    inv.add_argument("project_path")

    # libraries
    libraries_parser = sub.add_parser("libraries")
    libraries_sub = libraries_parser.add_subparsers(dest="libraries_command")

    lib_detect = libraries_sub.add_parser("detect")
    lib_detect.add_argument("project_path")

    lib_research = libraries_sub.add_parser("research")
    lib_research.add_argument("project_path")
    lib_research.add_argument("--library", required=True)
    lib_research.add_argument("--ecosystem", required=True)
    lib_research.add_argument("--allow-network", action="store_true")
    lib_research.add_argument("--build-input", action="store_true")
    lib_research.add_argument("--pro", action="store_true", help="Use vendored ai_library_researcher_pro workflow")
    lib_research.add_argument("--install-draft", action="store_true", help="Stage adapted researcher-pro draft when validation succeeds")
    lib_research.add_argument("--confirm-install", action="store_true", help="Install adapted draft into the main support pack registry")
    lib_research.add_argument("--overwrite", action="store_true", help="Allow replacing an existing pack with --confirm-install")

    # support-packs
    sp_parser = sub.add_parser("support-packs")
    sp_sub = sp_parser.add_subparsers(dest="sp_command")
    sp_sub.add_parser("list")
    
    sp_validate = sp_sub.add_parser("validate")
    sp_validate.add_argument("path")
    
    sp_install = sp_sub.add_parser("install")
    sp_install.add_argument("path")
    sp_install.add_argument("--overwrite", action="store_true")

    sp_adapt = sp_sub.add_parser("adapt-pro-draft")
    sp_adapt.add_argument("path")
    sp_adapt.add_argument("--out", default=None)

    project_packs = sub.add_parser(
        "project-packs",
        help="Manage support packs scoped to one project under .impact_engine/local_packs",
    )
    project_packs_sub = project_packs.add_subparsers(dest="project_packs_command")
    project_packs_init = project_packs_sub.add_parser("init")
    project_packs_init.add_argument("project_path")
    project_packs_list = project_packs_sub.add_parser("list")
    project_packs_list.add_argument("project_path")
    project_packs_install = project_packs_sub.add_parser("install")
    project_packs_install.add_argument("project_path")
    project_packs_install.add_argument("pack_path")
    project_packs_install.add_argument("--trust-level", default="draft")
    project_packs_install.add_argument("--overwrite", action="store_true")

    # db
    db_parser = sub.add_parser("db")
    db_sub = db_parser.add_subparsers(dest="db_command")
    
    db_init = db_sub.add_parser("init")
    db_init.add_argument("--path", default=None)
    
    db_runs = db_sub.add_parser("runs")
    db_runs.add_argument("--path", default=None)

    # research
    research_parser = sub.add_parser("research")
    research_sub = research_parser.add_subparsers(dest="research_command")
    
    r_start = research_sub.add_parser("start")
    r_start.add_argument("project_path")
    r_start.add_argument("--library", required=True)
    r_start.add_argument("--ecosystem", required=True)
    
    r_fetch = research_sub.add_parser("fetch")
    r_fetch.add_argument("workflow_id")
    
    r_build = research_sub.add_parser("build-input")
    r_build.add_argument("workflow_id")
    
    r_validate = research_sub.add_parser("validate")
    r_validate.add_argument("workflow_id")
    r_validate.add_argument("support_pack")
    
    r_install = research_sub.add_parser("install")
    r_install.add_argument("workflow_id")
    r_install.add_argument("support_pack")

    # doctor
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--full", action="store_true", help="Verify wheel/runtime assets in addition to local capabilities")

    approvals = sub.add_parser("approvals", help="List and approve one-time local action requests")
    approvals_sub = approvals.add_subparsers(dest="approvals_command", required=True)
    approvals_list = approvals_sub.add_parser("list")
    approvals_list.add_argument("project_path")
    approvals_show = approvals_sub.add_parser("show")
    approvals_show.add_argument("project_path")
    approvals_show.add_argument("approval_id")
    approvals_approve = approvals_sub.add_parser("approve")
    approvals_approve.add_argument("project_path")
    approvals_approve.add_argument("approval_id")

    # local registry
    registry_parser = sub.add_parser("registry")
    registry_sub = registry_parser.add_subparsers(dest="registry_command")
    registry_sub.add_parser("status")

    registry_cache_pack = registry_sub.add_parser("cache-pack")
    registry_cache_pack.add_argument("path")

    registry_pull_pack = registry_sub.add_parser("pull-pack")
    registry_pull_pack.add_argument("ecosystem")
    registry_pull_pack.add_argument("library")

    registry_research = registry_sub.add_parser("create-research-request")
    registry_research.add_argument("--ecosystem", required=True)
    registry_research.add_argument("--library", required=True)
    registry_research.add_argument("--package", default=None, dest="package_name")
    registry_research.add_argument("--project-fingerprint", default=None)

    registry_sync = registry_sub.add_parser("sync-project")
    registry_sync.add_argument("project_path")
    registry_sync.add_argument("--no-research-requests", action="store_true")

    registry_worker = registry_sub.add_parser("process-queue")
    registry_worker.add_argument("project_path")
    registry_worker.add_argument("--limit", type=int, default=20)
    registry_worker.add_argument("--allow-network", action="store_true")

    registry_register = registry_sub.add_parser("register-library")
    registry_register.add_argument("ecosystem")
    registry_register.add_argument("library")
    registry_register.add_argument("--docs-url", default=None)
    registry_register.add_argument("--repository-url", default=None)
    registry_register.add_argument("--package-manager", default=None)

    registry_status_library = registry_sub.add_parser("library-status")
    registry_status_library.add_argument("ecosystem")
    registry_status_library.add_argument("library")

    registry_approve = registry_sub.add_parser("approve-pack")
    registry_approve.add_argument("pack_id")
    registry_approve.add_argument("--trust-level", required=True)
    registry_approve.add_argument("--reviewer", required=True)
    registry_approve.add_argument("--note", default=None)

    registry_doc_check = registry_sub.add_parser("doc-check")
    registry_doc_check.add_argument("ecosystem")
    registry_doc_check.add_argument("library")
    registry_doc_check.add_argument("url")
    registry_doc_check.add_argument("--content-hash", required=True)
    registry_doc_check.add_argument("--source-type", default="docs")

    registry_simulate = registry_sub.add_parser("simulate-lifecycle")
    registry_simulate.add_argument("ecosystem")
    registry_simulate.add_argument("library")
    registry_simulate.add_argument("--source-url", required=True)

    # qa
    qa_parser = sub.add_parser("qa")
    qa_sub = qa_parser.add_subparsers(dest="qa_command")
    qa_run = qa_sub.add_parser("run")
    qa_run.add_argument("projects_root")
    qa_run.add_argument("--out-dir", default=None)

    benchmark_parser = sub.add_parser("benchmark")
    benchmark_sub = benchmark_parser.add_subparsers(dest="benchmark_command")
    benchmark_run = benchmark_sub.add_parser("run")
    benchmark_run.add_argument("root")
    benchmark_det = benchmark_sub.add_parser("determinism")
    benchmark_det.add_argument("project_path")
    benchmark_det.add_argument("--runs", type=int, default=3)
    benchmark_mutate = benchmark_sub.add_parser("mutate")
    benchmark_mutate.add_argument("root")
    benchmark_libraries = benchmark_sub.add_parser("libraries")
    benchmark_libraries.add_argument("root", nargs="?", default=".")
    benchmark_typescript = benchmark_sub.add_parser("typescript")
    benchmark_typescript.add_argument("root", nargs="?", default=".")
    benchmark_typescript_source = benchmark_sub.add_parser("typescript-source")
    benchmark_typescript_source.add_argument("root", nargs="?", default=".")
    benchmark_research_e2e = benchmark_sub.add_parser("research-e2e")
    benchmark_research_e2e.add_argument("root", nargs="?", default=".")
    benchmark_polyglot = benchmark_sub.add_parser("polyglot")
    benchmark_polyglot.add_argument("root", nargs="?", default=".")

    raw_argv = list(argv if argv is not None else sys.argv[1:])
    runtime_test_command = None
    if "runtime-trace" in raw_argv and "--" in raw_argv:
        separator_index = raw_argv.index("--")
        runtime_test_command = raw_argv[separator_index + 1:]
        raw_argv = raw_argv[:separator_index]

    args = parser.parse_args(raw_argv)
    if getattr(args, "command", None) == "runtime-trace" and runtime_test_command is not None:
        args.test_command = runtime_test_command
    elif getattr(args, "command", None) == "runtime-trace":
        args.test_command = []

    if args.command == "daemon":
        from impact_engine.persistence import daemon_status, start_daemon, stop_daemon
        if args.daemon_command == "start":
            result = start_daemon(args.project)
        elif args.daemon_command == "status":
            result = daemon_status(args.project)
        elif args.daemon_command == "stop":
            result = stop_daemon(args.project)
        else:
            result = {"status": "error", "error": "daemon subcommand is required"}
        if args.json:
            _print_json(result)
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        if result.get("status") == "error":
            sys.exit(1)

    elif args.command == "adapters":
        if args.adapter_command == "native":
            from impact_engine.adapters.native import native_profile, run_native_operation
            try:
                result = (
                    {"status": "ok", "adapter_id": args.adapter_id, "native": native_profile(args.adapter_id), "privacy": {"mode": "local-only", "network_used": False}}
                    if args.operation == "profile"
                    else run_native_operation(args.project, args.adapter_id, args.operation, confirmed=args.confirm, query=args.query, timeout_seconds=args.timeout_seconds)
                )
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") in {"error", "failed", "timeout"}:
                sys.exit(1)
            return
        if args.adapter_command in {"preflight", "status", "import"}:
            from impact_engine.adapters.registry import AdapterRegistry
            registry = AdapterRegistry(args.project)
            try:
                if args.adapter_command == "preflight":
                    result = registry.preflight(args.adapter_id)
                elif args.adapter_command == "status":
                    result = {"status": "ok", "adapter": registry.status(args.adapter_id), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.adapter_id == "lsp":
                    raise ValueError("LSP is a local process; configure it explicitly with `impact-engine adapters lsp configure`")
                else:
                    imported = registry.import_artifact(args.adapter_id, args.artifact)
                    adapter = registry.set_enabled(args.adapter_id, True) if args.enable else imported.get("adapter")
                    result = {"status": "ok", "import_status": imported.get("status"), "adapter": adapter, "privacy": {"mode": "local-only", "network_used": False}}
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        if args.adapter_command == "verify-scip":
            from impact_engine.adapters.scip_interop import verify_golden_corpus
            result = verify_golden_corpus(args.corpus, run_lint=not args.no_lint)
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        if args.adapter_command == "lsp":
            from impact_engine.adapters.lsp import configure_lsp, disable_lsp, lsp_status, preflight_lsp, probe_lsp, query_lsp
            try:
                if args.lsp_command == "status":
                    result = {"status": "ok", "adapter": lsp_status(args.project), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.lsp_command == "preflight":
                    result = {"status": "ok", "preflight": preflight_lsp(args.project, compile_commands=args.compile_commands), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.lsp_command == "configure":
                    result = {"status": "ok", "adapter": configure_lsp(args.project, args.executable, args.workspace_roots, arguments=args.arguments, timeout_ms=args.timeout_ms, backend=args.backend, server_family=args.server_family, compile_commands=args.compile_commands), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.lsp_command == "probe":
                    result = {"status": "ok", "adapter": probe_lsp(args.project), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.lsp_command == "start":
                    from impact_engine.adapters.agent_lsp import start_agent_lsp_runtime
                    result = {"status": "ok", "adapter": start_agent_lsp_runtime(args.project), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.lsp_command == "disable":
                    result = {"status": "ok", "adapter": disable_lsp(args.project), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.lsp_command == "query":
                    result = query_lsp(args.project, method=args.method, file=args.file, line=args.line, character=args.character, query=args.query, entity_id=args.entity_id, timeout_ms=args.timeout_ms)
                    # `--graph` is meaningful only for an explicit LSP query:
                    # it lets the adapter expose exact/ambiguous mapping to
                    # the canonical graph without changing that graph.  The
                    # parser advertised the flag but previously ignored it.
                    if args.graph and result.get("status") == "ok":
                        from impact_engine.adapters.lsp import map_lsp_overlay
                        canonical = GraphDocument.from_json(Path(args.graph).read_text(encoding="utf-8"))
                        result = map_lsp_overlay(result, canonical)
                else:
                    result = {"status": "error", "error": "lsp subcommand is required"}
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        if args.adapter_command in {"openapi", "asyncapi"}:
            from impact_engine.adapters.registry import AdapterRegistry
            registry = AdapterRegistry(args.project)
            try:
                if args.boundary_command == "import":
                    imported = registry.import_artifact(args.adapter_command, args.spec)
                    result = {"status": "ok", "import_status": imported.get("status"), "adapter": imported.get("adapter"), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.boundary_command == "enable":
                    result = {"status": "ok", "adapter": registry.set_enabled(args.adapter_command, True), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.boundary_command == "disable":
                    result = {"status": "ok", "adapter": registry.set_enabled(args.adapter_command, False), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.boundary_command == "status":
                    result = {"status": "ok", "adapter": registry.status(args.adapter_command), "privacy": {"mode": "local-only", "network_used": False}}
                else:
                    result = {"status": "error", "error": f"{args.adapter_command} subcommand is required"}
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        if args.adapter_command == "otel":
            from impact_engine.adapters.registry import AdapterRegistry
            registry = AdapterRegistry(args.project)
            try:
                if args.otel_command == "import":
                    imported = registry.import_artifact("otel", args.trace)
                    result = {"status": "ok", "import_status": imported.get("status"), "adapter": imported.get("adapter"), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.otel_command == "enable":
                    result = {"status": "ok", "adapter": registry.set_enabled("otel", True), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.otel_command == "disable":
                    result = {"status": "ok", "adapter": registry.set_enabled("otel", False), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.otel_command == "status":
                    result = {"status": "ok", "adapter": registry.status("otel"), "privacy": {"mode": "local-only", "network_used": False}}
                else:
                    result = {"status": "error", "error": "otel subcommand is required"}
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        if args.adapter_command in {"cyclonedx", "spdx", "sarif"}:
            from impact_engine.adapters.registry import AdapterRegistry
            registry = AdapterRegistry(args.project)
            try:
                if args.security_command == "import":
                    imported = registry.import_artifact(args.adapter_command, args.report)
                    result = {"status": "ok", "import_status": imported.get("status"), "adapter": imported.get("adapter"), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.security_command == "enable":
                    result = {"status": "ok", "adapter": registry.set_enabled(args.adapter_command, True), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.security_command == "disable":
                    result = {"status": "ok", "adapter": registry.set_enabled(args.adapter_command, False), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.security_command == "status":
                    result = {"status": "ok", "adapter": registry.status(args.adapter_command), "privacy": {"mode": "local-only", "network_used": False}}
                else:
                    result = {"status": "error", "error": f"{args.adapter_command} subcommand is required"}
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        if args.adapter_command in {"graphify", "codegraph"}:
            from impact_engine.adapters.registry import AdapterRegistry
            registry = AdapterRegistry(args.project)
            try:
                if args.external_graph_command == "import":
                    imported = registry.import_artifact(args.adapter_command, args.artifact)
                    result = {"status": "ok", "import_status": imported.get("status"), "adapter": imported.get("adapter"), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.external_graph_command == "enable":
                    result = {"status": "ok", "adapter": registry.set_enabled(args.adapter_command, True), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.external_graph_command == "disable":
                    result = {"status": "ok", "adapter": registry.set_enabled(args.adapter_command, False), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.external_graph_command == "status":
                    result = {"status": "ok", "adapter": registry.status(args.adapter_command), "privacy": {"mode": "local-only", "network_used": False}}
                else:
                    result = {"status": "error", "error": f"{args.adapter_command} subcommand is required"}
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        if args.adapter_command == "joern":
            from impact_engine.adapters.registry import AdapterRegistry
            try:
                if args.joern_command == "import":
                    registry = AdapterRegistry(args.project)
                    imported = registry.import_artifact("joern", args.artifact)
                    result = {"status": "ok", "import_status": imported.get("status"), "adapter": imported.get("adapter"), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.joern_command == "convert":
                    from impact_engine.adapters.joern_bridge import convert_graphson_file
                    result = convert_graphson_file(args.graphson, project_path=args.project, output_path=args.output)
                elif args.joern_command == "benchmark":
                    from impact_engine.adapters.joern_benchmark import run_joern_benchmark
                    case = None
                    if args.case_file:
                        case_path = Path(args.case_file).expanduser()
                        if not case_path.is_absolute():
                            raise ValueError("case_file must be an absolute local path")
                        case_data = json.loads(case_path.resolve().read_text(encoding="utf-8"))
                        cases = case_data.get("cases") if isinstance(case_data, dict) and isinstance(case_data.get("cases"), list) else [case_data]
                        if args.case_id:
                            case = next((item for item in cases if isinstance(item, dict) and item.get("case_id") == args.case_id), None)
                            if case is None:
                                raise ValueError(f"golden case not found: {args.case_id}")
                        elif len(cases) == 1:
                            case = cases[0]
                        else:
                            raise ValueError("case_id is required when case_file contains multiple cases")
                    result = run_joern_benchmark(args.project, args.artifact, case=case, output_path=args.output, entity=args.entity, max_nodes=args.max_nodes, max_edges=args.max_edges, max_paths=args.max_paths)
                elif args.joern_command == "discover":
                    from impact_engine.adapters.joern_benchmark import discover_local_joern_corpus
                    result = discover_local_joern_corpus(args.roots, max_files=args.max_files, timeout_seconds=args.timeout, include_synthetic=args.include_synthetic)
                elif args.joern_command == "enable":
                    registry = AdapterRegistry(args.project)
                    result = {"status": "ok", "adapter": registry.set_enabled("joern", True), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.joern_command == "disable":
                    registry = AdapterRegistry(args.project)
                    result = {"status": "ok", "adapter": registry.set_enabled("joern", False), "privacy": {"mode": "local-only", "network_used": False}}
                elif args.joern_command == "status":
                    registry = AdapterRegistry(args.project)
                    result = {"status": "ok", "adapter": registry.status("joern"), "privacy": {"mode": "local-only", "network_used": False}}
                else:
                    result = {"status": "error", "error": "joern subcommand is required"}
            except (FileNotFoundError, ValueError, OSError) as exc:
                result = {"status": "error", "error": str(exc)}
            if args.json or getattr(args, "local_json", False):
                _print_json(result)
            else:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            if result.get("status") == "error":
                sys.exit(1)
            return
        from impact_engine.adapters.registry import AdapterRegistry
        registry = AdapterRegistry(args.project)
        try:
            if args.adapter_command == "list":
                result = {"status": "ok", "project_path": str(registry.project_path), "adapters": registry.list(), "privacy": {"mode": "local-only", "network_used": False}}
            elif args.adapter_command == "import-scip":
                imported = registry.import_artifact("scip", args.artifact)
                result = {"status": "ok", "import_status": imported.get("status"), "adapter": imported.get("adapter"), "privacy": {"mode": "local-only", "network_used": False}}
            elif args.adapter_command in {"enable", "disable"}:
                result = {"status": "ok", "adapter": registry.set_enabled(args.adapter_id, args.adapter_command == "enable"), "privacy": {"mode": "local-only", "network_used": False}}
            else:
                result = {"status": "error", "error": "adapter subcommand is required"}
        except (FileNotFoundError, ValueError, OSError) as exc:
            result = {"status": "error", "error": str(exc)}
        if args.json or getattr(args, "local_json", False):
            _print_json(result)
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        if result.get("status") == "error":
            sys.exit(1)

    elif args.command == "scan-plan":
        from impact_engine.scope import build_scan_plan, write_scan_plan
        plan = build_scan_plan(args.path)
        plan["plan_path"] = str(write_scan_plan(args.path, plan))
        if args.json or getattr(args, "local_json", False):
            _print_json(plan)
        else:
            print(f"Scan plan: {plan['plan_path']}")
            print(f"  Included files: {plan['included_files']}")
            print(f"  Excluded directories: {len(plan['excluded_directories'])}")

    elif args.command in {"visualize", "visualize-compare"}:
        from impact_engine.visualization import render_graph_comparison_html, render_graph_html

        try:
            if args.command == "visualize-compare":
                output = render_graph_comparison_html(args.impact_graph, args.graphify_graph, args.out)
                result = {"status": "ok", "impact_graph": args.impact_graph, "graphify_graph": args.graphify_graph, "html": str(output.as_posix())}
            else:
                output = render_graph_html(args.graph, args.out)
                result = {"status": "ok", "graph": args.graph, "html": str(output.as_posix())}
        except Exception as exc:
            result = {"status": "error", "graph": args.graph, "error": str(exc)}
        if args.json:
            _print_json(result)
        else:
            if result["status"] == "ok":
                print(f"Graph viewer created: {result['html']}")
            else:
                print(f"Graph viewer error: {result['error']}", file=sys.stderr)
        if result["status"] == "error":
            sys.exit(1)

    elif args.command == "analyze-incremental":
        from impact_engine.analysis.pipeline import analyze_project_core
        from impact_engine.incremental import incremental_update, load_snapshot, save_snapshot
        from contextlib import nullcontext
        from impact_engine.persistence import CacheLock, CancellationToken
        out_path = args.out or _project_graph_path(args.path)
        snapshot_path = args.snapshot or str(Path(args.path).resolve() / ".impact_engine" / "project.snapshot.json")
        previous = load_snapshot(snapshot_path) if Path(snapshot_path).exists() else None
        scope_key = __import__("hashlib").sha256((args.scope or ".").encode("utf-8")).hexdigest()[:12]
        raw_cache = str(Path(args.path).resolve() / ".impact_engine" / f"raw_graph.{scope_key}.json")
        cancellation = CancellationToken()
        from impact_engine.persistence import daemon_request, daemon_status
        daemon_running = not args.no_daemon and daemon_status(args.path).get("status") == "running"
        try:
            if daemon_running:
                result = daemon_request(args.path, "analyze-incremental", {
                    "out_path": out_path, "snapshot_path": snapshot_path,
                    "changed_files": args.changed, "scope": args.scope,
                })
            else:
                with CacheLock(args.path, owner="cli-incremental"):
                    result = incremental_update(
                    args.path,
                    lambda changed: analyze_project_core(
                        args.path,
                        out_path=None,
                        changed_files=changed,
                        raw_graph_cache_path=raw_cache,
                        scope=args.scope,
                        cancellation=cancellation,
                    ),
                    previous_snapshot=previous,
                    out_path=out_path,
                    previous_graph_path=out_path,
                    forced_changed=args.changed,
                    scope=args.scope,
                    cancellation=cancellation,
                    )
                    save_snapshot(result["incremental"]["snapshot"], snapshot_path)
        except KeyboardInterrupt:
            result = {"status": "cancelled", "incomplete": True, "diagnostics": ["analysis cancelled by user"]}
        _attach_runtime_contract(result, scope=args.scope)
        if args.json:
            _print_json(result)
        else:
            print(f"Incremental analysis: {result.get('status')}")
            print(f"  Changed files: {result.get('incremental', {}).get('changed_file_count', 0)}")
            print(f"  Graph: {result.get('graph_path') or out_path}")

    elif args.command == "watch":
        from impact_engine.analysis.pipeline import analyze_project_core
        from impact_engine.watch import watch_project
        from contextlib import nullcontext
        from impact_engine.persistence import CacheLock, CancellationToken
        out_path = args.out or _project_graph_path(args.path)
        cancellation = CancellationToken()
        from impact_engine.persistence import daemon_request, daemon_status
        if not args.no_daemon and daemon_status(args.path).get("status") == "running":
            daemon_result = daemon_request(args.path, "watch", {
                "out_path": out_path, "interval_seconds": args.interval,
                "iterations": args.iterations, "scope": args.scope,
            })
            results = daemon_result.get("iterations", [])
        else:
            with CacheLock(args.path, owner="cli-watch"):
                results = list(watch_project(
                args.path,
                lambda: analyze_project_core(args.path, out_path=None, scope=args.scope, cancellation=cancellation),
                interval_seconds=args.interval,
                iterations=args.iterations,
                out_path=out_path,
                scope=args.scope,
                cancellation=cancellation,
                ))
        result = results[-1] if results else {"incremental": {}}
        _attach_runtime_contract(result, scope=args.scope)
        if args.json:
            _print_json({"status": "ok", "iterations": results, **result})
        else:
            print(f"Watch completed: {len(results)} iteration(s)")
            print(f"  Last changed files: {result.get('incremental', {}).get('changed_file_count', 0)}")

    elif args.command == "graph-quality":
        from impact_engine.graph_quality import graph_quality_report
        graph = GraphDocument.from_json(Path(args.graph).read_text(encoding="utf-8"))
        result = graph_quality_report(graph)
        if args.json:
            _print_json(result)
        else:
            print(f"Graph quality: {result['status']}")
            print(f"  Nodes: {result['node_count']}; edges: {result['edge_count']}")
            print(f"  Orphans: {result['orphan_node_count']}; dangling edges: {result['dangling_edge_count']}")

    elif args.command == "unknown-regions":
        from impact_engine.unknown_regions import analyze_unknown_regions, build_research_requests, write_research_requests

        try:
            if args.graph:
                graph = GraphDocument.from_json(Path(args.graph).read_text(encoding="utf-8"))
                project_path = args.project_path or graph.metadata.get("project_path") or graph.metadata.get("path")
            elif args.project_path:
                from impact_engine.analysis.pipeline import analyze_project_core

                analysis = analyze_project_core(args.project_path)
                graph = GraphDocument.from_dict(analysis["graph"])
                project_path = args.project_path
            else:
                raise ValueError("Provide project_path or --graph")
            report = analyze_unknown_regions(graph)
            requests = build_research_requests(report, project_path=project_path)
            output_path = args.out
            if not output_path and project_path and Path(str(project_path)).is_dir():
                output_path = str(Path(str(project_path)) / ".impact_engine" / "unknown_region_tasks.json")
            if output_path:
                report["task_file"] = write_research_requests(requests, output_path)
            result = {"status": "ok", "report": report, "requests": requests}
        except Exception as exc:
            result = {"status": "error", "error": str(exc)}
        if args.json or args.local_json:
            _print_json(result)
        else:
            if result["status"] == "ok":
                report = result["report"]
                print(f"Unknown regions: {report['status']}")
                print(f"  Unresolved: {report['counts']['unresolved']}; suspicious: {report['counts']['suspicious']}")
                print(f"  AI tasks: {len(result['requests'])}")
                if report.get("task_file"):
                    print(f"  Task file: {report['task_file']}")
            else:
                print(f"Unknown-region error: {result['error']}", file=sys.stderr)
                sys.exit(1)

    elif args.command == "benchmark":
        from impact_engine.benchmarks import run_benchmark_suite, run_determinism_check, run_determinism_suite, run_mutation_suite, write_library_reports

        if args.benchmark_command == "run":
            result = run_benchmark_suite(args.root)
            determinism = run_determinism_suite(args.root, runs=3)
            Path(args.root).resolve().joinpath("determinism_report.json").write_text(json.dumps(determinism, indent=2, ensure_ascii=False), encoding="utf-8")
            result["determinism"] = determinism
            result["quality_gates"]["determinism_true"] = determinism["determinism"] is True
            if not result["quality_gates"]["determinism_true"]:
                result["status"] = "failed"
            Path(args.root).resolve().joinpath("benchmark_summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        elif args.benchmark_command == "determinism":
            result = run_determinism_check(args.project_path, args.runs)
        elif args.benchmark_command == "mutate":
            result = run_mutation_suite(args.root)
            Path(args.root).resolve().joinpath("mutation_report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        elif args.benchmark_command == "libraries":
            result = write_library_reports(args.root)
        elif args.benchmark_command == "typescript":
            from impact_engine.benchmarks.typescript_support import run_typescript_support_benchmark
            result = run_typescript_support_benchmark(args.root)
        elif args.benchmark_command == "typescript-source":
            from impact_engine.benchmarks.source_typescript import run_source_typescript_benchmark
            result = run_source_typescript_benchmark(args.root)
        elif args.benchmark_command == "research-e2e":
            from impact_engine.research.real_e2e import run_real_research_e2e
            result = run_real_research_e2e(args.root)
        elif args.benchmark_command == "polyglot":
            from impact_engine.benchmarks.sprint5_polyglot import run_sprint5_benchmark
            result = run_sprint5_benchmark(args.root)
        else:
            result = {"status": "error", "error": "benchmark subcommand is required"}
        if args.json:
            _print_json(result)
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        if result.get("status") == "failed" or result.get("status") == "error":
            sys.exit(1)

    elif args.command == "onboard":
        from impact_engine.project_onboarding import onboard_project
        try:
            summary = onboard_project(
                args.source, allow_network=args.allow_network, workspace=args.workspace, branch=args.branch,
                graphify_mode=args.graphify, graphify_timeout_seconds=args.graphify_timeout,
            )
        except (FileNotFoundError, FileExistsError, PermissionError, RuntimeError, ValueError, OSError) as exc:
            summary = {"schema_version": "CodeSlicerProjectOnboarding/v1", "status": "error", "error": str(exc), "privacy": {"mode": "local-only", "network_used": False}}
        if args.out and summary.get("status") != "error":
            destination = Path(args.out).expanduser().resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if args.json:
            _print_json(summary)
        else:
            print(f"Project onboarding: {summary.get('status')}")
            if summary.get("project"):
                print(f"  Project: {summary['project'].get('path')}")
            if summary.get("canonical_graph"):
                print(f"  CodeSlicer graph: {summary['canonical_graph'].get('nodes')} nodes, {summary['canonical_graph'].get('edges')} edges")
            if summary.get("architecture_graph"):
                print(f"  Graphify: {summary['architecture_graph'].get('status')}")
            for limitation in summary.get("limitations", []):
                print(f"  Limitation: {limitation}")
            if summary.get("error"):
                print(f"  Error: {summary['error']}", file=sys.stderr)
        if summary.get("status") == "error":
            sys.exit(1)

    elif args.command == "analyze":
        from impact_engine.analysis.pipeline import analyze_project_core
        from impact_engine.support_packs.detection import detect_unknown_libraries_core
        from contextlib import nullcontext
        from impact_engine.persistence import CacheLock, CancellationToken, daemon_request, daemon_status
        out_path = args.out or _project_graph_path(args.path)
        if args.use_scan_plan:
            from impact_engine.scope import build_scan_plan, write_scan_plan
            write_scan_plan(args.path, build_scan_plan(args.path))
        def report_progress(event):
            stream = sys.stderr if args.json else sys.stdout
            print(
                f"[{event['overall_percent']:>5.1f}%] {event['message']} "
                f"({event['processed']}/{event['total']})",
                file=stream,
                flush=True,
            )
        cancellation = CancellationToken()
        if not args.no_daemon and daemon_status(args.path).get("status") == "running":
            summary = daemon_request(args.path, "analyze", {
                "out_path": out_path, "scope": args.scope,
                "enable_remote_registry": args.remote_registry,
                "create_research_requests": not args.no_research_requests,
                "graphify_path": args.graphify,
            })
        else:
            with CacheLock(args.path, owner="cli-analyze"):
                summary = analyze_project_core(
                    args.path, out_path=out_path, enable_remote_registry=args.remote_registry,
                    create_research_requests=not args.no_research_requests, graphify_path=args.graphify,
                    progress_callback=report_progress, scope=args.scope, cancellation=cancellation,
                )
        
        try:
            unknown_libs = detect_unknown_libraries_core(args.path)
            summary["unknown_libraries_count"] = len(unknown_libs)
            summary["unknown libraries count"] = len(unknown_libs)
        except Exception:
            summary["unknown_libraries_count"] = 0
            summary["unknown libraries count"] = 0
            
        summary["extractors"] = summary["extractors_used"]
        summary["support pack errors"] = summary["support_pack_load_errors"]
        _attach_runtime_contract(summary, scope=args.scope)
        
        if args.json:
            _print_json(summary)
        else:
            print("Project analysis completed successfully.")
            print(f"  Path: {summary.get('path')}")
            print(f"  Status: {summary.get('status')}")
            print(f"  Nodes: {summary.get('nodes')}, Edges: {summary.get('edges')}")
            print(f"  Languages: {', '.join(summary.get('languages', []))}")
            print(f"  Extractors used: {', '.join(summary.get('extractors_used', []))}")
            print(f"  Graph saved to: {summary.get('graph_path')}")
        
    elif args.command == "impact":
        graph_path = args.graph_positional or args.graph
        if not graph_path:
            print("Error: Missing graph path", file=sys.stderr)
            sys.exit(1)
        graph_text = Path(graph_path).read_text(encoding="utf-8")
        graph = GraphDocument.from_json(graph_text)
        
        result = impact_query(
            graph,
            target=args.target or "",
            symbol=args.symbol,
            file_path=args.file_arg,
            direction=args.direction,
            max_depth=args.depth,
            min_confidence=args.min_confidence,
            full_context_tokens=args.full_context_tokens,
            selected_context_tokens=args.selected_context_tokens,
        )
        if args.json:
            _print_json(result)
        else:
            print("Impact Query Results:")
            print(f"  Target: {args.target or args.symbol or args.file_arg}")
            print(f"  Direction: {args.direction}")
            print(f"  Matched Nodes: {len(result.get('matched_nodes', []))}")
            print(f"  Affected Nodes: {len(result.get('affected_nodes', []))}")
            for n in result.get('affected_nodes', []):
                print(f"    - {n.get('id')} ({n.get('kind')})")
            ranking = result.get("impact_ranking", [])
            if ranking:
                print("  Impact Ranking:")
                for item in ranking[:10]:
                    print(
                        f"    - {item.get('node_id')}: score={item.get('impact_score', 0):.3f}, "
                        f"confidence={item.get('path_confidence', 0):.0%}, "
                        f"status={item.get('confidence_status')}"
                    )
            print(f"  {result.get('scoring', {}).get('compact')}")
            context = result.get("context_efficiency", {})
            if context.get("status") == "measured":
                print(
                    f"  Context: {context['full_context_tokens']:,} -> "
                    f"{context['selected_context_tokens']:,} tokens "
                    f"({context['saving_percent']:.1f}% saved)"
                )
            else:
                print(f"  Context: {context.get('label')}")

    elif args.command == "pr-review":
        from impact_engine.pr_review import pr_review_core

        diff_text = None
        if args.diff_file:
            diff_text = Path(args.diff_file).read_text(encoding="utf-8")
        try:
            result = pr_review_core(
                args.project_path,
                graph_path=args.graph,
                diff_text=diff_text,
                max_depth=args.depth,
                min_confidence=args.min_confidence,
                max_results=args.max_results,
                include_full_evidence=args.full_evidence,
            )
        except Exception as exc:
            result = {"status": "error", "error": str(exc)}
        if args.json:
            _print_json(result)
        else:
            print("PR Impact Report:")
            print(f"  Status: {result.get('status')}")
            if result.get("status") == "ok":
                print(f"  Risk: {result.get('risk', {}).get('level')} ({result.get('risk', {}).get('score')})")
                print(f"  Changed files: {result.get('summary', {}).get('changed_files')}")
                print(f"  Changed symbols: {result.get('summary', {}).get('changed_symbols')}")
                print(f"  Top impacts: {result.get('summary', {}).get('top_impacts')}")
                print("  Risk reasons:")
                for reason in result.get("risk", {}).get("reasons", []):
                    print(f"    - {reason}")
                print("  Required tests:")
                for item in result.get("suggested_tests", {}).get("required", []):
                    print(f"    - {item.get('file') or item.get('node')} ({item.get('reason')})")
                print("  Recommended tests:")
                for item in result.get("suggested_tests", {}).get("recommended", []):
                    print(f"    - {item.get('file') or item.get('node')} ({item.get('reason')})")
            else:
                print(f"  Error: {result.get('error')}")
        if result.get("status") == "error":
            sys.exit(1)

    elif args.command == "review":
        from impact_engine.review import build_review_report
        from impact_engine.persistence import CacheLock, daemon_request, daemon_status
        from impact_engine.contracts import build_mode_response

        diff_text = Path(args.diff_file).read_text(encoding="utf-8") if args.diff_file else None
        try:
            if not args.no_daemon and daemon_status(args.project_path).get("status") == "running":
                result = daemon_request(args.project_path, "review", {
                    "diff_text": diff_text, "base": args.base, "graph_path": args.graph,
                    "refresh": args.refresh, "max_results": args.max_results,
                    "run_tests": args.run_tests, "deep": args.deep, "entity": args.entity,
                    "scope": args.scope,
                })
            else:
                graph = GraphDocument.from_json(Path(args.graph).read_text(encoding="utf-8")) if args.graph else None
                with CacheLock(args.project_path, owner="cli-review"):
                    result = build_review_report(
                        args.project_path, graph=graph, diff_text=diff_text, base=args.base,
                        graph_path=args.graph, refresh=args.refresh, max_results=args.max_results,
                        run_tests=args.run_tests, deep=args.deep, entity=args.entity, scope=args.scope,
                    )
            from impact_engine.review_history import record_review
            result["review_id"] = record_review(args.project_path, result)
            result["mode_response"] = build_mode_response(
                "review", project=args.project_path,
                freshness=result.get("graph_freshness"), coverage=result.get("coverage"),
                warnings=result.get("warnings", []), adapters=result.get("adapters", []), result=result,
            )
        except Exception as exc:
            result = {"status": "error", "error": str(exc), "schema_version": "ReviewReport/v1"}
        if args.json or getattr(args, "local_json", False):
            _print_json(result)
        else:
            print("Daily Review:")
            print(f"  Risk: {result.get('risk', {}).get('level')} (confidence: {result.get('risk', {}).get('confidence')})")
            print(f"  Graph: {result.get('graph_freshness', {}).get('refresh_mode')} / stale={result.get('graph_freshness', {}).get('stale')}")
            print("  Review now:")
            for item in result.get("top_impacts", []):
                print(f"    - {item.get('label')} [{item.get('kind')}] ({item.get('confidence')})")
            print("  Tests:")
            for item in result.get("test_recommendations", [])[:10]:
                print(f"    - {item.get('file')} ({item.get('priority')})")
            for warning in result.get("warnings", []):
                print(f"  Warning: {warning}")

    elif args.command in {"inspect", "investigate", "ci"}:
        from impact_engine.modes import build_ci_report, build_inspect_report, build_investigate_report, to_sarif
        from impact_engine.contracts import build_mode_response

        diff_text = Path(args.diff_file).read_text(encoding="utf-8") if getattr(args, "diff_file", None) else None
        exit_code = 0
        try:
            if args.command == "inspect":
                result = build_inspect_report(
                    args.project_path, entity=args.entity, graph_path=args.graph,
                    refresh=args.refresh, max_context=args.max_context,
                )
            elif args.command == "investigate":
                result = build_investigate_report(
                    args.project_path, entity=args.entity, graph_path=args.graph,
                    direction=args.direction, depth=args.depth, refresh=args.refresh,
                    runtime_validate=args.runtime_validate, max_nodes=args.max_nodes,
                    max_edges=args.max_edges,
                )
            else:
                result = build_ci_report(
                    args.project_path, base=args.base, policy_path=args.policy,
                    graph_path=args.graph, diff_text=diff_text, refresh=args.refresh,
                    run_tests=args.run_tests, test_command=args.test_command,
                )
                exit_code = int(result.get("exit_code", 0))
        except (FileNotFoundError, ValueError) as exc:
            exit_code = 2
            result = {
                "schema_version": "CodeSlicerModeReport/v1",
                "mode": args.command,
                "status": "invalid_input",
                "local_only": True,
                "error": str(exc),
                "warnings": [str(exc)],
                "coverage": [],
                "graph_freshness": {"status": "unavailable", "stale": True},
                "actions": {"items": []},
                "exit_code": exit_code,
            }
        except Exception as exc:
            exit_code = 3 if args.command == "ci" else 1
            result = {
                "schema_version": "CodeSlicerModeReport/v1",
                "mode": args.command,
                "status": "analysis_failed",
                "local_only": True,
                "error": str(exc),
                "warnings": [f"analysis could not complete: {exc}"],
                "coverage": [],
                "graph_freshness": {"status": "unavailable", "stale": True},
                "actions": {"items": []},
                "exit_code": exit_code,
            }
        result["mode_response"] = build_mode_response(
            args.command, project=args.project_path,
            freshness=result.get("graph_freshness"), coverage=result.get("coverage"),
            warnings=result.get("warnings", []), adapters=result.get("adapters", []), result=result,
        )
        output = to_sarif(result) if args.command == "ci" and args.format == "sarif" else result
        if getattr(args, "out", None):
            destination = Path(args.out).expanduser().resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
            if not args.json and args.command == "ci":
                print(f"CodeSlicer CI report written: {destination}")
        elif args.json or getattr(args, "local_json", False) or args.command == "ci":
            _print_json(output)
        else:
            print(f"{args.command.capitalize()}: {result.get('status')}")
            if result.get("resolved_entity"):
                print(f"  Entity: {result['resolved_entity'].get('id')}")
            if result.get("risk"):
                print(f"  Risk: {result['risk'].get('level')}")
            for warning in result.get("warnings", []):
                print(f"  Warning: {warning}")
        if exit_code:
            sys.exit(exit_code)

    elif args.command == "runtime-trace":
        from impact_engine.runtime_trace import runtime_trace_project_core

        test_command = list(args.test_command or [])
        if test_command and test_command[0] == "--":
            test_command = test_command[1:]
        try:
            result = runtime_trace_project_core(
                args.project_path,
                graph_path=args.graph,
                out_path=args.out,
                test_command=test_command or None,
                timeout_seconds=args.timeout,
            )
        except Exception as exc:
            result = {"status": "error", "error": str(exc)}
        if args.json:
            _print_json(result)
        else:
            print("Runtime Trace Booster:")
            print(f"  Status: {result.get('status')}")
            print(f"  Runtime calls: {result.get('summary', {}).get('runtime_calls', 0)}")
            print(f"  Matched edges: {result.get('summary', {}).get('matched_edges', 0)}")
            print(f"  Unmatched calls: {result.get('summary', {}).get('unmatched_calls', 0)}")
            if result.get("out_path"):
                print(f"  Patched graph: {result.get('out_path')}")
            if result.get("error"):
                print(f"  Error: {result.get('error')}")
        if result.get("status") not in {"ok"}:
            sys.exit(1)
        
    elif args.command == "explain-edge":
        graph_path = args.graph_positional or args.graph
        if not graph_path:
            print("Error: Missing graph path", file=sys.stderr)
            sys.exit(1)
        graph_text = Path(graph_path).read_text(encoding="utf-8")
        graph = GraphDocument.from_json(graph_text)
        result = explain_edge(graph, args.from_node, args.to_node, args.kind)
        
        if args.json:
            _print_json(result)
        else:
            print("Edge Explanation:")
            print(f"  Found: {result.get('found')}")
            if result.get('found'):
                edge = result.get('edge', {})
                print(f"  From: {edge.get('from')}")
                print(f"  To: {edge.get('to')}")
                print(f"  Kind: {edge.get('kind')}")
                print(f"  Confidence: {result.get('confidence')}")
                print(f"  Source: {result.get('source')}")
                print("  Reasoning Steps:")
                for step in result.get('reasoning_steps', []):
                    print(f"    - {step}")
                print("  Evidence:")
                for ev in result.get('evidence_chain', []):
                    print(f"    - {ev.get('description')} ({ev.get('file')}:{ev.get('line')})")
        
    elif args.command == "detect-languages":
        from impact_engine.languages.registry import detect_languages
        langs = detect_languages(args.project_path)
        if args.json:
            _print_json(langs)
        else:
            print(f"Languages detected: {', '.join(langs)}")

    elif args.command == "inventory":
        from impact_engine.inventory.scanner import scan_project_inventory
        inv_res = scan_project_inventory(args.project_path)
        if args.json:
            _print_json(inv_res.to_dict())
        else:
            d = inv_res.to_dict()
            print("Project Inventory:")
            print(f"  Files: {d.get('files_count', 0)}")
            print(f"  Classes: {d.get('classes_count', 0)}")
            print(f"  Functions/Methods: {d.get('methods_count', 0)}")
            print(f"  LOC (Lines of Code): {d.get('loc', 0)}")

    elif args.command == "support-packs":
        from impact_engine.support_packs.store import SupportPackStore
        store = SupportPackStore()
        
        if args.sp_command == "list":
            packs = store.list_packs()
            from dataclasses import asdict
            if args.json:
                _print_json([asdict(p) for p in packs])
            else:
                print("Installed Support Packs:")
                for p in packs:
                    print(f"  - {p.library} ({p.language}, {p.version_range})")
            
        elif args.sp_command == "validate":
            from impact_engine.support_packs.registry import validate_support_pack_file
            res = validate_support_pack_file(args.path)
            if args.json:
                _print_json(res)
            else:
                if res["valid"]:
                    print(f"Support pack at '{args.path}' is VALID.")
                    print(f"  Library: {res.get('library')}")
                else:
                    print(f"Support pack at '{args.path}' is INVALID:")
                    for err in res.get("errors", []):
                        print(f"  - {err}")
            if not res["valid"]:
                sys.exit(1)
            
        elif args.sp_command == "install":
            try:
                from impact_engine.support_packs.schema import validate_support_pack_dict

                pack_dict = _load_support_pack_candidate(args.path)
                install_pack = pack_dict
                adapted_from = None
                validation_errors = validate_support_pack_dict(install_pack)
                if validation_errors:
                    try:
                        from impact_engine.research.pro_adapter import adapt_researcher_pro_draft
                        install_pack = adapt_researcher_pro_draft(pack_dict)
                        adapted_from = "ai_library_researcher_pro"
                        validation_errors = validate_support_pack_dict(install_pack)
                    except Exception as exc:
                        validation_errors = validation_errors + [f"researcher-pro adaptation failed: {exc}"]

                if validation_errors:
                    res = {"valid": False, "errors": validation_errors, "path": None}
                else:
                    target_path = _registry_pack_path(install_pack)
                    if target_path.exists() and not args.overwrite:
                        staged_path = _save_staged_support_pack(install_pack)
                        res = {
                            "valid": False,
                            "status": "blocked_existing_pack",
                            "errors": [f"Support pack already exists: {target_path.as_posix()}"],
                            "path": str(staged_path.as_posix()),
                            "target_path": str(target_path.as_posix()),
                            "message": "Existing pack was not overwritten. Use --overwrite if replacement is intentional.",
                        }
                    else:
                        res = store.validate_and_save_pack(install_pack)
                        res["status"] = "installed" if res.get("valid") else "error"
                        if adapted_from and res.get("valid", False):
                            res["adapted_from"] = adapted_from
                if args.json:
                    _print_json(res)
                else:
                    if res.get("valid", True):
                        print(f"Support pack for '{res.get('library')}' installed successfully at: {res.get('path')}")
                    else:
                        print("Support pack installation failed:")
                        for err in res.get("errors", []):
                            print(f"  - {err}")
                if not res.get("valid", True):
                    sys.exit(1)
            except Exception as e:
                err_dict = {"valid": False, "errors": [str(e)], "path": None}
                print(json.dumps(err_dict, indent=2, ensure_ascii=False) if args.json else f"Installation error: {str(e)}")
                sys.exit(1)

        elif args.sp_command == "adapt-pro-draft":
            try:
                from impact_engine.research.pro_adapter import adapt_researcher_pro_draft_file
                adapted = adapt_researcher_pro_draft_file(args.path)
                if args.out:
                    out_path = Path(args.out)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_text(json.dumps(adapted, indent=2, ensure_ascii=False), encoding="utf-8")
                    res = {"status": "ok", "path": str(out_path), "support_pack": adapted}
                else:
                    res = {"status": "ok", "support_pack": adapted}
                if args.json:
                    _print_json(res)
                else:
                    print("Researcher-pro draft adapted successfully.")
                    if args.out:
                        print(f"  Output: {args.out}")
            except Exception as e:
                res = {"status": "error", "errors": [str(e)]}
                if args.json:
                    _print_json(res)
                else:
                    print(f"Adaptation error: {e}")
                sys.exit(1)

    elif args.command == "project-packs":
        from impact_engine.project_packs import initialize_project_packs, install_project_pack, list_project_packs

        if args.project_packs_command == "init":
            res = initialize_project_packs(args.project_path)
        elif args.project_packs_command == "list":
            res = {"status": "ok", "scope": "project_local", "packs": list_project_packs(args.project_path)}
        elif args.project_packs_command == "install":
            res = install_project_pack(
                args.project_path,
                args.pack_path,
                trust_level=args.trust_level,
                overwrite=args.overwrite,
            )
        else:
            res = {"status": "error", "error": "project-packs subcommand is required"}
        if args.json:
            _print_json(res)
        else:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        if res.get("status") == "error":
            sys.exit(1)

    elif args.command == "libraries":
        if args.libraries_command == "detect":
            from impact_engine.support_packs.detection import detect_unknown_libraries_core
            unknown = detect_unknown_libraries_core(args.project_path)
            res = {"status": "ok", "project_path": args.project_path, "unknown_libraries": unknown, "count": len(unknown)}
            if args.json:
                _print_json(res)
            else:
                print("Unknown Libraries:")
                if not unknown:
                    print("  none")
                for library in unknown:
                    print(f"  - {library}")

        elif args.libraries_command == "research":
            if args.pro:
                try:
                    res = _run_researcher_pro(args)
                except Exception as exc:
                    res = {"status": "error", "error": str(exc)}
                if args.json:
                    _print_json(res)
                else:
                    print("Library research workflow completed with ai_library_researcher_pro.")
                    print(f"  Workflow ID: {res.get('workflow_id')}")
                    print(f"  Support pack draft: {res.get('support_pack_path')}")
                    if res.get("install_result"):
                        print(f"  Install: {res['install_result']}")
                install_result = res.get("install_result")
                if (
                    res.get("status") == "error"
                    or res.get("ok") is False
                    or (isinstance(install_result, dict) and install_result.get("valid") is False)
                ):
                    sys.exit(1)
                return

            from impact_engine.research.workflow import init_workflow, fetch_pages, build_input_pack
            workflow_id = init_workflow(args.project_path, args.library, args.ecosystem)
            fetched_count = 0
            input_pack = None
            if args.allow_network:
                fetched_count = len(fetch_pages(workflow_id))
            if args.build_input or args.allow_network:
                input_pack = build_input_pack(workflow_id)
            res = {
                "status": "initialized",
                "workflow_id": workflow_id,
                "project_path": args.project_path,
                "library": args.library,
                "ecosystem": args.ecosystem,
                "network_fetches": fetched_count,
                "input_pack_built": input_pack is not None,
            }
            if input_pack is not None:
                res["agent_task_path"] = str(
                    (Path(".impact_engine/research_workflows") / workflow_id / "agent_task.json").as_posix()
                )
            if args.json:
                _print_json(res)
            else:
                print("Library research workflow initialized.")
                print(f"  Workflow ID: {workflow_id}")
                print(f"  Library: {args.library} ({args.ecosystem})")
                if input_pack is not None:
                    print("  Research input pack built.")
                    print(f"  Agent task: {res['agent_task_path']}")
        else:
            print("Error: Missing libraries subcommand", file=sys.stderr)
            sys.exit(1)

    elif args.command == "db":
        from impact_engine.storage.db import init_db, list_analysis_runs, get_default_db_path
        db_p = args.path if args.path else None
        
        if args.db_command == "init":
            initialized_path = init_db(db_p)
            res = {"status": "ok", "db_path": str(initialized_path.as_posix())}
            if args.json:
                _print_json(res)
            else:
                print(f"Database initialized at: {initialized_path}")
            
        elif args.db_command == "runs":
            runs = list_analysis_runs(db_p or get_default_db_path())
            if args.json:
                _print_json(runs)
            else:
                print("Analysis Runs:")
                for r in runs:
                    print(f"  - Run ID: {r.get('run_id')} (Timestamp: {r.get('timestamp')}, Path: {r.get('project_path')})")

    elif args.command == "research":
        from impact_engine.research.workflow import (
            init_workflow, fetch_pages, build_input_pack, validate_candidate, install_candidate
        )
        
        if args.research_command == "start":
            wf_id = init_workflow(args.project_path, args.library, args.ecosystem)
            res = {"status": "initialized", "workflow_id": wf_id}
            if args.json:
                _print_json(res)
            else:
                print("Research workflow initialized.")
                print(f"  Workflow ID: {wf_id}")
            
        elif args.research_command == "fetch":
            res = fetch_pages(args.workflow_id)
            out = {"status": "fetched", "pages_count": len(res)}
            if args.json:
                _print_json(out)
            else:
                print(f"Fetched {len(res)} pages for workflow '{args.workflow_id}'.")
            
        elif args.research_command == "build-input":
            res = build_input_pack(args.workflow_id)
            out = {"status": "input_built", "excerpts_count": len(res.get("fetched_pages", []))}
            if args.json:
                _print_json(out)
            else:
                print(f"Research input built with {len(res.get('fetched_pages', []))} page excerpts.")
            
        elif args.research_command == "validate":
            candidate = _load_support_pack_candidate(args.support_pack)
            res = validate_candidate(args.workflow_id, candidate)
            if args.json:
                _print_json(res)
            else:
                if res.get("valid", True):
                    print("Candidate support pack is VALID.")
                else:
                    print("Candidate support pack is INVALID:")
                    for err in res.get("errors", []):
                        print(f"  - {err}")
            if not res.get("valid", True):
                sys.exit(1)
            
        elif args.research_command == "install":
            candidate = _load_support_pack_candidate(args.support_pack)
            res = install_candidate(args.workflow_id, candidate)
            if args.json:
                _print_json(res)
            else:
                if res.get("status") == "installed":
                    print(f"Candidate support pack installed at: {res.get('path')}")
                else:
                    print("Candidate installation failed:")
                    for err in res.get("errors", []):
                        print(f"  - {err}")
            if res.get("status") == "error":
                sys.exit(1)

    elif args.command == "doctor":
        res = _doctor_report(full=bool(getattr(args, "full", False)))
        if args.json:
            _print_json(res)
        else:
            print("Impact Engine Doctor:")
            print(f"  Status: {res['status']}")
            for check in res["checks"]:
                print(f"  - {check['name']}: {check['status']} - {check['message']}")
        if res["status"] == "error":
            sys.exit(1)

    elif args.command == "approvals":
        from impact_engine.approvals import ApprovalStore
        store = ApprovalStore(args.project_path)
        if args.approvals_command == "list":
            res = {"status": "ok", "project_path": str(Path(args.project_path).resolve()), "approvals": store.list()}
        elif args.approvals_command == "show":
            res = {"status": "ok", "approval": store.show(args.approval_id)}
        else:
            res = {"status": "approved", "approval": store.approve(args.approval_id)}
        if args.json:
            _print_json(res)
        else:
            print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "registry":
        from impact_engine.remote_registry import RegistryClient, ResearchRequestRecord

        client = RegistryClient()
        if args.registry_command == "status":
            res = client.connection_status()
        elif args.registry_command == "cache-pack":
            pack = _load_support_pack_candidate(args.path)
            res = client.cache_support_pack(pack)
        elif args.registry_command == "pull-pack":
            res = client.pull_support_pack(args.ecosystem, args.library)
        elif args.registry_command == "create-research-request":
            request = ResearchRequestRecord(
                ecosystem=args.ecosystem,
                library_name=args.library,
                package_name=args.package_name,
                project_fingerprint=args.project_fingerprint,
            )
            res = client.create_research_request(request)
        elif args.registry_command == "sync-project":
            from dataclasses import asdict
            from impact_engine.inventory.scanner import scan_project_inventory
            from impact_engine.remote_registry.sync import sync_registry_for_inventory

            inv = asdict(scan_project_inventory(args.project_path))
            res = sync_registry_for_inventory(inv, create_research_requests=not args.no_research_requests)
        elif args.registry_command == "process-queue":
            from impact_engine.remote_registry.worker import process_local_research_queue

            res = process_local_research_queue(
                project_path=args.project_path,
                limit=args.limit,
                allow_network=args.allow_network,
            )
        elif args.registry_command == "register-library":
            res = client.register_library(
                args.ecosystem, args.library, docs_url=args.docs_url,
                repository_url=args.repository_url, package_manager=args.package_manager,
            )
        elif args.registry_command == "library-status":
            res = client.library_status(args.ecosystem, args.library)
        elif args.registry_command == "approve-pack":
            res = client.approve_support_pack(args.pack_id, args.trust_level, args.reviewer, args.note)
        elif args.registry_command == "doc-check":
            res = client.record_documentation_check(
                args.ecosystem, args.library, args.url, args.content_hash, args.source_type
            )
        elif args.registry_command == "simulate-lifecycle":
            res = client.simulate_library_lifecycle(args.ecosystem, args.library, args.source_url)
        else:
            print("Error: Missing registry subcommand", file=sys.stderr)
            sys.exit(1)
        if args.json:
            _print_json(res)
        else:
            print(f"Registry: {res.get('status')}")
            if res.get("mode"):
                print(f"  Mode: {res.get('mode')}")
            if res.get("path"):
                print(f"  Path: {res.get('path')}")
        if res.get("status") == "error":
            sys.exit(1)

    elif args.command == "qa":
        if args.qa_command == "run":
            try:
                res = _qa_run(args.projects_root, args.out_dir)
            except Exception as exc:
                res = {"status": "error", "error": str(exc)}
            if args.json:
                _print_json(res)
            else:
                print("QA Run:")
                print(f"  Status: {res.get('status')}")
                if res.get("summary"):
                    print(f"  Summary: {res.get('summary')}")
                for run in res.get("runs", []):
                    print(f"  - {run.get('project')}: {run.get('status')} ({run.get('nodes', 0)} nodes, {run.get('edges', 0)} edges)")
                    failed = [c for c in run.get("checks", []) if c.get("status") in {"fail", "known_gap"}]
                    for check in failed[:8]:
                        print(f"      {check.get('status')}: {check.get('type')} {check.get('description') or check.get('contains') or check.get('to')}")
            if res.get("status") in {"error", "failed"}:
                sys.exit(1)
        else:
            print("Error: Missing qa subcommand", file=sys.stderr)
            sys.exit(1)
        
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
