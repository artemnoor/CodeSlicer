"""Opt-in interoperability checks for external SCIP indexers.

This module is deliberately separate from the import path.  Importing a local
artifact never starts an indexer or invokes a command.  The verifier only runs
when the user explicitly calls ``pytest -m scip_interop`` or
``impact-engine adapters verify-scip``.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from impact_engine.adapters.scip import parse_scip_artifact


GOLDEN_SCHEMA = "CodeSlicerScipGolden/v1"
DEFAULT_GOLDEN_ROOT = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "scip" / "golden"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_golden_manifests(root: str | Path | None = None) -> list[Path]:
    corpus_root = Path(root or DEFAULT_GOLDEN_ROOT).expanduser().resolve()
    if not corpus_root.is_dir():
        return []
    if (corpus_root / "manifest.json").is_file():
        return [corpus_root / "manifest.json"]
    return sorted(corpus_root.glob("*/manifest.json"))


def find_scip_cli() -> str | None:
    """Return an existing local SCIP CLI without installing or downloading it."""
    configured = os.environ.get("CODESLICER_SCIP_CLI")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_absolute() and candidate.is_file():
            return str(candidate.resolve())
        return None
    return shutil.which("scip")


def _manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != GOLDEN_SCHEMA:
        raise ValueError(f"invalid SCIP golden manifest: {path}")
    for key in ("language", "indexer", "indexer_version", "project_dir", "artifact", "artifact_sha256", "generation", "expected"):
        if key not in data:
            raise ValueError(f"SCIP golden manifest is missing {key}: {path}")
    if data.get("status") not in {"not-materialized", "materialized"}:
        raise ValueError(f"invalid SCIP golden manifest status: {path}")
    if data.get("status") == "materialized" and not data.get("artifact_sha256"):
        raise ValueError(f"materialized SCIP golden manifest must record artifact_sha256: {path}")
    return data


def _expected_check(parsed: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    documents = parsed.get("documents") or []
    document_paths = {str(item.get("relative_path")) for item in documents if isinstance(item, dict)}
    for expected_path in expected.get("document_paths", []):
        if str(expected_path) not in document_paths:
            errors.append(f"missing document path: {expected_path}")
    symbols = parsed.get("symbols") or []
    names = {str(item.get("name")) for item in symbols if isinstance(item, dict)}
    for expected_name in expected.get("symbol_names", []):
        if str(expected_name) not in names:
            errors.append(f"missing symbol name: {expected_name}")
    definitions = sum(len(item.get("definitions") or []) for item in symbols if isinstance(item, dict))
    references = sum(len(item.get("references") or []) for item in symbols if isinstance(item, dict))
    implementations = sum(len(item.get("implementations") or []) for item in symbols if isinstance(item, dict))
    ranges = sum(
        1
        for document in documents
        for occurrence in (document.get("occurrences") or [])
        if occurrence.get("range")
    )
    for field, actual in (("definitions", definitions), ("references", references), ("implementations", implementations)):
        minimum = expected.get(f"minimum_{field}")
        if minimum is not None and actual < int(minimum):
            errors.append(f"expected at least {minimum} {field}, observed {actual}")
    minimum_ranges = expected.get("minimum_ranges")
    if minimum_ranges is not None and ranges < int(minimum_ranges):
        errors.append(f"expected at least {minimum_ranges} source ranges, observed {ranges}")
    if expected.get("require_typed_ranges"):
        typed = sum(
            1
            for document in documents
            for occurrence in (document.get("occurrences") or [])
            if occurrence.get("range_encoding") in {"single_line_typed", "multi_line_typed"}
        )
        if typed == 0:
            errors.append("expected at least one typed SCIP range")
    return errors


def _lint(cli: str, artifact: Path, timeout: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [cli, "lint", str(artifact)],
            cwd=str(artifact.parent),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "error": str(exc)}
    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


def verify_golden_corpus(
    root: str | Path | None = None,
    *,
    run_lint: bool = True,
    cli_path: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Verify materialized golden artifacts and optionally run official lint.

    Missing artifacts and missing tools are reported as ``skipped``.  A
    malformed artifact, SHA mismatch, failed parser assertion, or failed lint
    is an error.  No part of this function performs package installation or
    network access.
    """
    manifests = discover_golden_manifests(root)
    results: list[dict[str, Any]] = []
    cli = cli_path or find_scip_cli()
    for manifest_path in manifests:
        try:
            manifest = _manifest(manifest_path)
            artifact = (manifest_path.parent / manifest["project_dir"] / manifest["artifact"]).resolve()
            result: dict[str, Any] = {
                "language": manifest["language"],
                "indexer": manifest["indexer"],
                "manifest": str(manifest_path),
                "artifact": str(artifact),
                "status": "skipped",
            }
            if not artifact.is_file():
                result["reason"] = "golden artifact is not materialized; run the documented indexer command explicitly"
                results.append(result)
                continue
            expected_sha = manifest.get("artifact_sha256")
            actual_sha = _sha256(artifact)
            result["sha256"] = actual_sha
            if not expected_sha:
                result.update({"status": "error", "reason": "materialized artifact has no SHA-256 recorded in manifest"})
                results.append(result)
                continue
            if expected_sha and actual_sha.lower() != str(expected_sha).lower():
                result.update({"status": "error", "reason": "artifact SHA-256 does not match manifest"})
                results.append(result)
                continue
            try:
                parsed = parse_scip_artifact(artifact)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                result.update({"status": "error", "reason": f"CodeSlicer parser rejected artifact: {exc}"})
                results.append(result)
                continue
            result["parser"] = {
                "status": "passed",
                "format": parsed.get("format"),
                "metadata": parsed.get("index_metadata", {}),
                "symbols": len(parsed.get("symbols") or []),
            }
            expected_errors = _expected_check(parsed, manifest["expected"])
            if expected_errors:
                result.update({"status": "error", "reason": "golden expectations failed", "errors": expected_errors})
                results.append(result)
                continue
            if run_lint:
                if not cli:
                    result["reason"] = "official SCIP CLI not found; parser verification passed"
                    result["lint"] = {"status": "skipped", "reason": "scip executable is not on PATH"}
                    results.append(result)
                    continue
                lint = _lint(cli, artifact, timeout)
                result["lint"] = lint
                if lint.get("status") != "passed":
                    result.update({"status": "error", "reason": "official scip lint failed"})
                    results.append(result)
                    continue
            result["status"] = "ok"
            results.append(result)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            results.append({"manifest": str(manifest_path), "status": "error", "reason": str(exc)})
    statuses = {item.get("status") for item in results}
    overall = "error" if "error" in statuses else ("ok" if results and statuses == {"ok"} else "skipped")
    return {
        "schema_version": GOLDEN_SCHEMA,
        "status": overall,
        "scip_cli": cli,
        "network_used": False,
        "results": results,
    }
