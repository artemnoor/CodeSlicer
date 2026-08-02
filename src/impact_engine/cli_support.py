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
    try:
        print(json.dumps(data, indent=2, ensure_ascii=True))
    except BrokenPipeError:
        # Consumers such as ``head`` may intentionally close stdout after a
        # complete JSON prefix.  Treat that as normal pipe semantics instead
        # of surfacing a PyInstaller traceback from an otherwise successful
        # analysis command.
        try:
            sys.stdout.close()
        except OSError:
            pass


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




__all__ = [name for name in globals() if not name.startswith("__")]
