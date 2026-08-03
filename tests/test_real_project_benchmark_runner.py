from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_real_project_benchmarks.py"


def _git(project: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, check=True, timeout=30)
    return result.stdout.strip()


def test_real_project_benchmark_runner_exercises_cli_analyze_warm_cache_and_review(tmp_path):
    source_root = tmp_path / "sources"
    project = source_root / "fixture"
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname = 'fixture'\nversion = '0.0.1'\n", encoding="utf-8")
    (project / "app.py").write_text("def handler():\n    return 1\n", encoding="utf-8")
    _git(project, "init")
    _git(project, "add", ".")
    _git(project, "-c", "user.name=CodeSlicer test", "-c", "user.email=tests@example.invalid", "commit", "-m", "fixture")
    (project / "README.md").write_text("# Fixture\n", encoding="utf-8")
    _git(project, "add", "README.md")
    _git(project, "-c", "user.name=CodeSlicer test", "-c", "user.email=tests@example.invalid", "commit", "-m", "document fixture")
    commit = _git(project, "rev-parse", "HEAD")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "CodeSlicerRealProjectBenchmarkManifest/v1",
        "projects": [{
            "id": "fixture", "repository": "https://example.invalid/fixture.git", "commit": commit,
            "language": "python", "scope": ".",
            "mutation": {"file": "app.py", "anchor": "def handler():", "comment": "# benchmark mutation"},
        }],
    }), encoding="utf-8")
    output = tmp_path / "report.json"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--manifest", str(manifest), "--source-root", str(source_root), "--output", str(output)],
        cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    item = report["results"][0]
    assert item["validation"]["gates"] == {
        "pinned_commit": True, "cold_analysis_ok": True, "warm_cache_hit": True,
        "historical_review_ok": True, "freshness_review_ok": True, "language_detected": True,
    }
    assert item["analysis"]["nodes"] > 0
    assert item["review"]["historical_commit"]["schema_version"].startswith("ReviewReport/")
    assert item["review"]["freshness_control"]["schema_version"].startswith("ReviewReport/")


def test_real_project_benchmark_runner_fetches_the_pinned_commit_without_a_source_root(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text("[project]\nname = 'remote-fixture'\nversion = '0.0.1'\n", encoding="utf-8")
    (source / "app.py").write_text("def handler():\n    return 1\n", encoding="utf-8")
    _git(source, "init")
    _git(source, "add", ".")
    _git(source, "-c", "user.name=CodeSlicer test", "-c", "user.email=tests@example.invalid", "commit", "-m", "fixture")
    (source / "README.md").write_text("# Remote fixture\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "-c", "user.name=CodeSlicer test", "-c", "user.email=tests@example.invalid", "commit", "-m", "document fixture")
    commit = _git(source, "rev-parse", "HEAD")
    remote = tmp_path / "fixture.git"
    subprocess.run(["git", "clone", "--bare", str(source), str(remote)], check=True, capture_output=True, text=True, timeout=30)
    manifest = tmp_path / "remote-manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "CodeSlicerRealProjectBenchmarkManifest/v1",
        "projects": [{
            "id": "fixture", "repository": remote.as_uri(), "commit": commit,
            "language": "python", "scope": ".",
            "mutation": {"file": "app.py", "anchor": "def handler():", "comment": "# benchmark mutation"},
        }],
    }), encoding="utf-8")
    output = tmp_path / "remote-report.json"
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--manifest", str(manifest), "--output", str(output)],
        cwd=ROOT, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(output.read_text(encoding="utf-8"))["results"][0]["validation"]["gates"]["pinned_commit"]
