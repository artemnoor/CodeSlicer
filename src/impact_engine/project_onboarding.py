"""Local-first project connection workflow.

This module deliberately creates *two* independent products for a project:

* a canonical CodeSlicer graph for impact and PR review;
* an optional Graphify architecture graph for broad exploration.

The latter is never merged into the former or used by CodeSlicer ranking.
"""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any
from urllib.parse import urlparse

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.inventory.scanner import scan_project_inventory
from impact_engine.project_storage import ensure_project_storage
from impact_engine.adapters.graphify_paths import graphify_artifact_root, record_graphify_interpreter


ONBOARDING_SCHEMA = "CodeSlicerProjectOnboarding/v1"
_GIT_SSH_RE = re.compile(r"^[^\s@/:]+@[^\s:/]+:[^\s]+(?:\.git)?$")


def _is_git_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme in {"http", "https", "ssh", "git"}
        and bool(parsed.netloc)
        and bool(parsed.path)
    ) or bool(_GIT_SSH_RE.fullmatch(value))


def _clone_name(url: str) -> str:
    raw = urlparse(url).path if "://" in url else url.rsplit(":", 1)[-1]
    base = Path(raw).name.removesuffix(".git")
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", base).strip(".-") or "project"
    suffix = sha256(url.encode("utf-8")).hexdigest()[:8]
    return f"{safe}-{suffix}"


def _git_details(root: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"], cwd=root,
            capture_output=True, text=True, shell=False, timeout=15, check=False,
        )
        if result.returncode != 0 or result.stdout.strip() != "true":
            return {"repository": False, "head": None, "branch": None}
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, shell=False, timeout=15, check=False)
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=root, capture_output=True, text=True, shell=False, timeout=15, check=False)
        return {
            "repository": True,
            "head": head.stdout.strip() if head.returncode == 0 else None,
            "branch": branch.stdout.strip() if branch.returncode == 0 else None,
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"repository": False, "head": None, "branch": None}


def _resolve_project(
    source: str,
    *,
    allow_network: bool,
    workspace: str | Path | None,
    branch: str | None,
) -> tuple[Path, dict[str, Any]]:
    candidate = Path(source).expanduser()
    if candidate.is_dir():
        return candidate.resolve(), {"kind": "local_path", "network_used": False, "cloned": False, "source": str(candidate.resolve())}
    if not _is_git_url(source):
        raise FileNotFoundError(f"project directory does not exist and source is not a supported Git URL: {source}")
    if not allow_network:
        raise PermissionError("cloning a Git URL requires --allow-network; no network action was performed")

    workspace_root = Path(workspace).expanduser().resolve() if workspace else (Path.home() / ".codeslicer" / "projects")
    workspace_root.mkdir(parents=True, exist_ok=True)
    target = workspace_root / _clone_name(source)
    if target.exists():
        if not (target / ".git").is_dir():
            raise FileExistsError(f"clone destination exists but is not a Git checkout: {target}")
        return target.resolve(), {"kind": "git_url", "network_used": False, "cloned": False, "source": source, "workspace": str(workspace_root), "reused_clone": True}

    command = ["git"]
    if branch:
        command.extend(["clone", "--depth", "1", "--branch", branch, source, str(target)])
    else:
        command.extend(["clone", "--depth", "1", source, str(target)])
    try:
        result = subprocess.run(command, cwd=workspace_root, capture_output=True, text=True, shell=False, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"could not clone project: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or f"git clone failed with {result.returncode}").strip()[:4000])
    return target.resolve(), {"kind": "git_url", "network_used": True, "cloned": True, "source": source, "workspace": str(workspace_root)}


def _graphify_summary(project: Path, artifact_root: Path, *, mode: str, timeout_seconds: int) -> dict[str, Any]:
    if mode == "off":
        return {"status": "disabled", "reason": "disabled by caller", "participates_in_ranking": False}
    executable = shutil.which("graphify")
    if not executable:
        result = {"status": "unavailable", "reason": "Graphify executable was not found locally", "participates_in_ranking": False}
        if mode == "required":
            result["required"] = True
        return result

    command = [executable, "extract", str(project), "--code-only", "--out", str(artifact_root)]
    try:
        process = subprocess.run(command, cwd=project, capture_output=True, text=True, shell=False, timeout=max(1, min(timeout_seconds, 300)), check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "reason": str(exc), "command": command, "participates_in_ranking": False}
    graph_path = artifact_root / "graphify-out" / "graph.json"
    if process.returncode != 0 or not graph_path.is_file():
        return {
            "status": "error", "reason": (process.stderr or process.stdout or "Graphify did not create graph.json").strip()[:4000],
            "command": command, "exit_code": process.returncode, "participates_in_ranking": False,
        }
    record_graphify_interpreter(graph_path, executable)
    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
        nodes = data.get("nodes") if isinstance(data.get("nodes"), list) else []
        edges = data.get("links") if isinstance(data.get("links"), list) else data.get("edges") if isinstance(data.get("edges"), list) else []
        ids = {str(node.get("id")) for node in nodes if isinstance(node, dict) and node.get("id") is not None}
        dangling = sum(
            1 for edge in edges if isinstance(edge, dict)
            and (str(edge.get("source") or edge.get("from")) not in ids or str(edge.get("target") or edge.get("to")) not in ids)
        )
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "error", "reason": f"could not read Graphify output: {exc}", "command": command, "participates_in_ranking": False}
    return {
        "status": "ok", "graph_path": str(graph_path), "nodes": len(nodes), "edges": len(edges),
        "communities": len({str(node.get("community")) for node in nodes if isinstance(node, dict) and node.get("community") is not None}),
        "dangling_edges": dangling, "command": command, "exit_code": process.returncode,
        "purpose": "broad architecture exploration", "participates_in_ranking": False,
        "separate_from_canonical": True, "privacy": {"mode": "local-only", "network_used": False},
    }


def onboard_project(
    source: str,
    *,
    allow_network: bool = False,
    workspace: str | Path | None = None,
    branch: str | None = None,
    graphify_mode: str = "auto",
    graphify_timeout_seconds: int = 120,
    support_pack_root: str = "support_packs",
) -> dict[str, Any]:
    """Connect a project and produce isolated architecture and impact graphs.

    The function never runs tests, changes source files, sends source code, or
    creates a network connection for a local path.  A Git URL needs explicit
    ``allow_network=True``.
    """
    if graphify_mode not in {"auto", "off", "required"}:
        raise ValueError("graphify_mode must be auto, off, or required")
    project, source_info = _resolve_project(source, allow_network=allow_network, workspace=workspace, branch=branch)
    storage = ensure_project_storage(project)
    inventory = asdict(scan_project_inventory(str(project)))
    canonical_path = project / ".impact_engine" / "graph.json"
    analysis = analyze_project_core(
        str(project), out_path=str(canonical_path), support_pack_root=support_pack_root,
        enable_remote_registry=False, create_research_requests=False,
    )
    graphify = _graphify_summary(project, graphify_artifact_root(project), mode=graphify_mode, timeout_seconds=graphify_timeout_seconds)

    limitations: list[str] = []
    coverage = analysis.get("coverage") or []
    for item in coverage:
        if isinstance(item, dict) and str(item.get("capability") or item.get("status") or "").lower() not in {"high", "supported", "full"}:
            language = item.get("language") or "unknown language"
            limitations.append(f"{language}: {item.get('capability') or item.get('status') or 'limited coverage'}")
    if graphify.get("status") == "unavailable":
        limitations.append("Graphify architecture graph was not built because the optional executable is unavailable")
    if graphify.get("dangling_edges"):
        limitations.append(f"Graphify reported {graphify['dangling_edges']} dangling architecture edges; treat its graph as partial exploration evidence")
    if graphify_mode == "required" and graphify.get("status") != "ok":
        limitations.append("Graphify was required but did not complete")

    report = {
        "schema_version": ONBOARDING_SCHEMA,
        "status": "partial" if limitations else "ok",
        "project": {"path": str(project), "name": project.name, "source": source_info, "git": _git_details(project)},
        "stack": {
            "languages": inventory.get("languages", []), "package_manifests": inventory.get("package_manifests", []),
            "declared_dependencies": inventory.get("declared_dependencies", []), "files": inventory.get("files_count", 0),
            "loc": inventory.get("loc", 0),
        },
        "canonical_graph": {
            "path": analysis.get("graph_path") or str(canonical_path), "nodes": analysis.get("nodes", 0), "edges": analysis.get("edges", 0),
            "coverage": coverage, "purpose": "impact, Git diff review and targeted tests", "participates_in_ranking": True,
        },
        "architecture_graph": graphify,
        "limitations": limitations,
        "next_actions": {
            "understand_architecture": f'graphify query "<question>" --graph "{graphify.get("graph_path", "<graphify graph>")}"' if graphify.get("status") == "ok" else "Install or enable Graphify, then rerun onboarding with --graphify auto",
            "find_code": f'impact-engine --json inspect "{project}" --entity "<entity-id>"',
            "review_change": f'impact-engine --json review "{project}" --run-tests suggested',
            "run_recommended_tests": "Review only selects tests; it does not execute them. After explicit confirmation use `impact-engine ci <project> --run-tests --test-command <argv...>`.",
        },
        "privacy": {"mode": "local-only", "network_used": bool(source_info.get("network_used")), "source_code_sent": False},
    }
    report_path = storage / "artifacts" / "onboarding" / "last.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    return report
