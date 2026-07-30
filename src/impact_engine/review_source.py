"""Local-only review-source and base-reference selection.

The selection result is deliberately a small data contract.  Clients can show
the choices to a developer instead of silently assuming that ``main`` is the
right comparison branch.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable


GitRunner = Callable[[Path, list[str]], str | None]


def git(root: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _exists(root: Path, ref: str, runner: GitRunner) -> bool:
    return runner(root, ["rev-parse", "--verify", "--quiet", ref]) is not None


def detect_base_refs(root: Path, explicit_base: str | None = None, *, runner: GitRunner = git) -> dict:
    """Return an honest, deterministic base-ref choice for a local review.

    Explicit input wins.  Otherwise an actual remote default branch is the
    only automatic choice.  Familiar local names are merely candidates: a
    multi-candidate repository needs a user decision.
    """
    if explicit_base and explicit_base != "auto":
        return {
            "status": "selected" if _exists(root, explicit_base, runner) else "missing",
            "base_ref": explicit_base,
            "candidates": [explicit_base],
            "reason": "explicit base reference",
        }

    remote_head = runner(root, ["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"])
    if remote_head and _exists(root, remote_head, runner):
        return {
            "status": "automatic",
            "base_ref": remote_head,
            "candidates": [remote_head],
            "reason": "origin default branch",
        }

    candidates: list[str] = []
    for ref in ("main", "master", "develop", "trunk", "origin/main", "origin/master", "origin/develop"):
        if _exists(root, ref, runner) and ref not in candidates:
            candidates.append(ref)
    if len(candidates) == 1:
        return {
            "status": "automatic",
            "base_ref": candidates[0],
            "candidates": candidates,
            "reason": "only verified conventional base branch",
        }
    return {
        "status": "selection_required" if candidates else "unavailable",
        "base_ref": None,
        "candidates": candidates,
        "reason": "multiple verified base branches" if candidates else "no local or origin base branch was found",
    }


def review_source(root: Path, *, base: str | None = None, diff_file: str | None = None, runner: GitRunner = git) -> dict:
    if diff_file:
        return {
            "kind": "diff_file",
            "label": "Diff file",
            "local_only": True,
            "base": {"status": "not_required", "base_ref": None, "candidates": [], "reason": "diff file supplied"},
        }
    base_selection = detect_base_refs(root, base, runner=runner)
    return {
        "kind": "current_changes",
        "label": "Current changes",
        "local_only": True,
        "base": base_selection,
    }
