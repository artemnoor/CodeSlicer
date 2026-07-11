"""Real CLI subprocess E2E smoke tests.

These tests intentionally complement the fast in-process CLI tests. They prove
that the installed package can be exercised through the Python module entrypoint
and the console script without relying on pytest internals or shared state.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from importlib import metadata

ROOT = Path(__file__).resolve().parents[1]
PROJECT_PATH = ROOT / "examples" / "golden_cases" / "python_di_basic"
TIMEOUT = 20


def _env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    src_path = str(ROOT / "src")
    env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")
    env["IMPACT_ENGINE_TEST_TIMEOUT"] = "0"  # child process should not inherit pytest SIGALRM behavior
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run_subprocess(args: list[str], tmp_path: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=tmp_path,
        env=_env(tmp_path),
        timeout=TIMEOUT,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            "subprocess CLI command failed\n"
            f"args={args!r}\n"
            f"returncode={result.returncode}\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
    return result


def test_python_module_cli_real_subprocess_e2e(tmp_path):
    graph_path = tmp_path / "tmp_graph.json"

    analyze = run_subprocess([
        sys.executable,
        "-m",
        "impact_engine.cli",
        "analyze",
        str(PROJECT_PATH),
        "--out",
        str(graph_path),
    ], tmp_path)
    assert analyze.returncode == 0
    assert graph_path.exists()
    graph_data = json.loads(graph_path.read_text(encoding="utf-8"))
    edge = next(
        (
            e for e in graph_data["edges"]
            if e["kind"] == "CALLS"
            and e["from"] == "services.OrderService.create_order"
            and e["to"] == "repositories.OrderRepository.save"
        ),
        None,
    )
    assert edge is not None
    assert edge["source"] == "INFERRED"
    assert edge["confidence"] >= 0.80
    assert len(edge.get("evidence", [])) >= 1

    impact = run_subprocess([
        sys.executable,
        "-m",
        "impact_engine.cli",
        "impact",
        str(graph_path),
        "--symbol",
        "repositories.OrderRepository.save",
        "--direction",
        "upstream",
        "--depth",
        "3",
        "--min-confidence",
        "0.8",
    ], tmp_path)
    assert "Impact Query Results:" in impact.stdout
    assert "services.OrderService.create_order" in impact.stdout

    explain = run_subprocess([
        sys.executable,
        "-m",
        "impact_engine.cli",
        "explain-edge",
        str(graph_path),
        "--from",
        "services.OrderService.create_order",
        "--to",
        "repositories.OrderRepository.save",
    ], tmp_path)
    assert "Edge Explanation:" in explain.stdout
    assert "Found: True" in explain.stdout
    assert "Receiver method resolution" in explain.stdout

    languages = run_subprocess([
        sys.executable,
        "-m",
        "impact_engine.cli",
        "detect-languages",
        str(PROJECT_PATH),
    ], tmp_path)
    assert "python" in languages.stdout

    inventory = run_subprocess([
        sys.executable,
        "-m",
        "impact_engine.cli",
        "inventory",
        str(PROJECT_PATH),
    ], tmp_path)
    assert "Project Inventory:" in inventory.stdout
    assert "Files:" in inventory.stdout

    research = run_subprocess([
        sys.executable,
        "-m",
        "impact_engine.cli",
        "research",
        "start",
        str(PROJECT_PATH),
        "--library",
        "fastapi",
        "--ecosystem",
        "python",
    ], tmp_path)
    assert "Research workflow initialized." in research.stdout
    assert (tmp_path / ".impact_engine" / "research_workflows").exists()


def test_installed_console_script_real_subprocess_or_entrypoint(tmp_path):
    exe = shutil.which("impact-engine")
    if exe:
        result = run_subprocess([exe, "--json", "detect-languages", str(PROJECT_PATH)], tmp_path)
        langs = json.loads(result.stdout)
        assert "python" in langs
        return

    # Honest fallback for environments that run tests before editable scripts are
    # on PATH: verify packaging metadata rather than pretending a subprocess ran.
    entry_points = metadata.entry_points(group="console_scripts")
    matches = [ep for ep in entry_points if ep.name == "impact-engine"]
    assert matches, "impact-engine console script is not installed and no entrypoint metadata exists"
    assert matches[0].value == "impact_engine.cli:main"


def test_all_subprocess_run_calls_in_tests_have_timeouts():
    import ast

    for path in (ROOT / "tests").glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_subprocess_run = (
                isinstance(func, ast.Attribute)
                and func.attr == "run"
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            )
            if is_subprocess_run:
                kw_names = {kw.arg for kw in node.keywords}
                assert "timeout" in kw_names, f"subprocess.run without timeout in {path}:{node.lineno}"
