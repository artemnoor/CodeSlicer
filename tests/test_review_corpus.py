"""Acceptance regressions for the named real-project review corpora.

The projects are intentionally opt-in: they are local/private repositories and
must never be downloaded or analyzed as a side effect of the normal test run.
Set the project and diff environment variables to run a case locally.
"""
import os
import hashlib
import json
import subprocess
import time
from pathlib import Path

import pytest

from impact_engine.review import build_review_report


CASES = ("JunMate", "JevioFuseHack", "Cruxa")
MANIFEST = json.loads((Path(__file__).parent / "fixtures" / "review_corpora.json").read_text(encoding="utf-8"))


def _source_snapshot_sha256(root: Path) -> str:
    """Fingerprint an unpacked local corpus when its .git metadata is absent."""
    digest = hashlib.sha256()
    files = []
    excluded = {".git", ".impact_engine", ".codeslicer", ".impactlens", ".pytest_cache", "__pycache__"}
    for path in root.rglob("*"):
        if path.is_file() and not any(part in excluded for part in path.relative_to(root).parts):
            files.append(path)
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        contents = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return digest.hexdigest()


@pytest.mark.parametrize("case", CASES)
def test_named_corpus_review_is_bounded_and_local(case: str, tmp_path: Path):
    golden = MANIFEST["cases"][case]
    repo_root = Path(__file__).resolve().parents[1]
    configured_root = os.environ.get(golden["root_env"])
    configured_diff = os.environ.get(golden["diff_env"])
    if not configured_root or not configured_diff:
        if os.environ.get("CI", "").lower() in {"1", "true", "yes"}:
            pytest.fail(f"CI requires pinned corpus inputs: {golden['root_env']} and {golden['diff_env']}")
        pytest.skip(f"external corpus is opt-in; set {golden['root_env']} and {golden['diff_env']} to run it")
    if golden["golden_status"] != "pinned" or not golden["diff_sha256"] or not golden.get("source_snapshot_sha256"):
        if os.environ.get("CI", "").lower() in {"1", "true", "yes"}:
            pytest.fail(f"{case} corpus golden fixture is not pinned in review_corpora.json")
        pytest.skip(f"{case} manifest is present but its local snapshot/diff golden is not pinned")

    project = Path(configured_root).expanduser().resolve()
    diff_path = Path(configured_diff).expanduser().resolve()
    graph_path = project / ".impact_engine" / "graph.json"
    if not project.is_dir() or not diff_path.is_file():
        pytest.fail(f"configured {case} corpus is incomplete: project and diff are required")
    if not graph_path.is_file():
        graph_path = tmp_path / f"{case}.graph.json"
        subprocess.run(
            [
                os.environ.get("PYTHON", "python"), "-m", "impact_engine.cli", "--json", "analyze",
                str(project), "--no-research-requests", "--out", str(graph_path),
            ],
            check=True,
            cwd=repo_root,
            env={**os.environ, "PYTHONPATH": str(repo_root / "src")},
            timeout=golden["max_duration_seconds"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    git_root = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False, timeout=10,
    ).stdout.strip()
    actual_sha = ""
    if git_root and Path(git_root).resolve() == project:
        actual_sha = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, timeout=10,
        ).stdout.strip()
    if actual_sha:
        assert actual_sha == golden["commit_sha"]
    else:
        assert golden["commit_sha"] == "UNAVAILABLE_NO_GIT_METADATA"
        assert _source_snapshot_sha256(project) == golden["source_snapshot_sha256"]
    assert hashlib.sha256(diff_path.read_bytes()).hexdigest() == golden["diff_sha256"]

    started = time.perf_counter()
    report = build_review_report(
        str(project), graph_path=graph_path, diff_text=diff_path.read_text(encoding="utf-8"),
        refresh="never", max_results=10, run_tests="suggested",
    )
    assert time.perf_counter() - started <= golden["max_duration_seconds"]
    assert report["schema_version"] == "ReviewReport/v1"
    assert len(report["top_impacts"]) <= 10
    assert report["graph_freshness"]["graph_path"] == str(graph_path)
    assert report["graph_freshness"]["stale"] in (True, False)
    noise = sum(item.get("kind") in {"ASSIGNMENT", "CALL_EXPR", "LIBRARY", "EXTERNAL_LIBRARY", "SUPPORT_PACK"} for item in report["top_impacts"])
    assert (noise / len(report["top_impacts"]) if report["top_impacts"] else 0) <= golden["max_noise_ratio"]
    assert all(
        item.get("why", {}).get("evidence_locations") or item.get("why", {}).get("heuristic")
        for item in report["top_impacts"]
    )
    assert [item.get("entity_id") for item in report["top_impacts"][:5]] == golden["expected_top_impacts"]
    assert sorted({item.get("file") for item in report["test_recommendations"] if item.get("file")}) == sorted(golden["expected_test_files"])
    assert report["chain_summary"]["status"] == golden["expected_chain_status"]
    assert report["graph_integrity"]["dangling_endpoint_edges"] == 0
    assert report["graph_integrity"]["dangling_endpoint_ratio"] == 0
