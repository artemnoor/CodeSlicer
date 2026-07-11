"""Public runtime tracing API."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .matcher import match_runtime_calls_to_graph
from .tracer import TRACER_RUNNER_SOURCE


def _json_safe_diagnostic(level: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"level": level, "message": message, "details": details or {}}


def _default_test_command() -> list[str]:
    return [sys.executable, "-m", "pytest", "-q"]


def _load_trace_output(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("trace output is not a JSON object")
    return data


def _base_result(
    *,
    status: str,
    project_path: Path,
    test_command: list[str],
    exit_code: int | None,
    duration_seconds: float,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "project_path": str(project_path),
        "test_command": list(test_command),
        "exit_code": exit_code,
        "duration_seconds": round(duration_seconds, 6),
        "tests": [],
        "runtime_calls": [],
        "matched_edges": [],
        "unmatched_calls": [],
        "diagnostics": diagnostics or [],
    }


def run_runtime_trace(
    project_path: str,
    test_command: list[str] | None = None,
    graph: dict[str, Any] | None = None,
    timeout_seconds: int = 60,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> dict[str, Any]:
    """Run Python tests under a stdlib profiler and return JSON-compatible data.

    The tracer is executed in a subprocess. For commands shaped like
    ``python -m pytest -q`` or ``pytest -q`` it runs pytest inside the tracer's
    Python process so ``sys.setprofile`` can observe project calls.
    """

    start = time.monotonic()
    project = Path(project_path).resolve()
    command = list(test_command or _default_test_command())

    if timeout_seconds <= 0:
        return _base_result(
            status="error",
            project_path=project,
            test_command=command,
            exit_code=None,
            duration_seconds=time.monotonic() - start,
            diagnostics=[_json_safe_diagnostic("error", "timeout_seconds must be positive.")],
        )

    if not project.exists() or not project.is_dir():
        return _base_result(
            status="error",
            project_path=project,
            test_command=command,
            exit_code=None,
            duration_seconds=time.monotonic() - start,
            diagnostics=[_json_safe_diagnostic("error", "project_path does not exist or is not a directory.")],
        )

    with tempfile.TemporaryDirectory(prefix="runtime_trace_booster_") as temp_name:
        temp_dir = Path(temp_name)
        tracer_script = temp_dir / "tracer_runner.py"
        output_path = temp_dir / "trace.json"
        config_path = temp_dir / "config.json"

        tracer_script.write_text(TRACER_RUNNER_SOURCE, encoding="utf-8")
        config_path.write_text(
            json.dumps(
                {
                    "include_patterns": include_patterns or [],
                    "exclude_patterns": exclude_patterns or [],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        invocation = [
            sys.executable,
            str(tracer_script),
            "--project-path",
            str(project),
            "--output",
            str(output_path),
            "--config",
            str(config_path),
            "--",
            *command,
        ]

        try:
            completed = subprocess.run(
                invocation,
                cwd=str(project),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start
            return _base_result(
                status="timeout",
                project_path=project,
                test_command=command,
                exit_code=None,
                duration_seconds=duration,
                diagnostics=[
                    _json_safe_diagnostic(
                        "error",
                        "Runtime trace timed out.",
                        {
                            "timeout_seconds": timeout_seconds,
                            "stdout": exc.stdout or "",
                            "stderr": exc.stderr or "",
                        },
                    )
                ],
            )

        duration = time.monotonic() - start
        diagnostics: list[dict[str, Any]] = []
        if completed.stdout:
            diagnostics.append(
                _json_safe_diagnostic("info", "Test command stdout captured.", {"stdout": completed.stdout[-8000:]})
            )
        if completed.stderr:
            diagnostics.append(
                _json_safe_diagnostic("info", "Test command stderr captured.", {"stderr": completed.stderr[-8000:]})
            )

        if not output_path.exists():
            return _base_result(
                status="test_failed" if completed.returncode else "error",
                project_path=project,
                test_command=command,
                exit_code=int(completed.returncode),
                duration_seconds=duration,
                diagnostics=diagnostics
                + [
                    _json_safe_diagnostic(
                        "error",
                        "Tracer did not write an output JSON file.",
                        {"returncode": completed.returncode},
                    )
                ],
            )

        try:
            raw_trace = _load_trace_output(output_path)
        except Exception as exc:  # noqa: BLE001 - public API must return JSON-safe error data
            return _base_result(
                status="error",
                project_path=project,
                test_command=command,
                exit_code=int(completed.returncode),
                duration_seconds=duration,
                diagnostics=diagnostics
                + [_json_safe_diagnostic("error", "Failed to read tracer output.", {"error": repr(exc)})],
            )

    exit_code = int(raw_trace.get("exit_code", completed.returncode))
    diagnostics.extend(raw_trace.get("diagnostics", []) or [])

    status = "ok" if exit_code == 0 else "test_failed"
    runtime_calls = raw_trace.get("runtime_calls", []) or []
    tests = raw_trace.get("tests", []) or []

    if status != "ok":
        # Failed tests are useful diagnostics, but runtime confirmations from a
        # failing run should not boost production confidence.
        runtime_calls = []

    result = {
        "status": status,
        "project_path": str(project),
        "test_command": command,
        "exit_code": exit_code,
        "duration_seconds": round(duration, 6),
        "tests": tests,
        "runtime_calls": runtime_calls,
        "matched_edges": [],
        "unmatched_calls": [],
        "diagnostics": diagnostics,
    }

    if graph is not None and status == "ok":
        match_result = match_runtime_calls_to_graph(graph, runtime_calls)
        result["matched_edges"] = match_result["matched_edges"]
        result["unmatched_calls"] = match_result["unmatched_calls"]
        result["diagnostics"].extend(match_result.get("diagnostics", []) or [])

    return result
