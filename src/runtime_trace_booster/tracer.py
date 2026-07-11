"""Embedded tracer runner source.

The public runner writes this source into a temporary directory and executes it in
an isolated Python subprocess. The embedded script intentionally uses only the
standard library and does not import :mod:`runtime_trace_booster`, which keeps it
usable even when tracing a target project with a different working directory.
"""

from __future__ import annotations

TRACER_RUNNER_SOURCE = r'''
from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time
import traceback

DEFAULT_EXCLUDE_PATTERNS = [
    ".venv",
    "venv",
    "site-packages",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
]


def _as_posix_patterns(patterns):
    return [str(pattern).replace("\\", "/") for pattern in (patterns or [])]


def _safe_resolve(filename):
    try:
        return Path(filename).resolve()
    except OSError:
        return None


class TraceCollector:
    def __init__(self, project_path, include_patterns=None, exclude_patterns=None):
        self.project_path = Path(project_path).resolve()
        self.include_patterns = _as_posix_patterns(include_patterns or [])
        self.exclude_patterns = _as_posix_patterns(DEFAULT_EXCLUDE_PATTERNS + (exclude_patterns or []))
        self.calls_by_key = {}
        self.tests = {}
        self.diagnostics = []
        self._include_cache = {}

    def is_included(self, filename):
        cached = self._include_cache.get(filename)
        if cached is not None:
            return cached
        if not filename or filename.startswith("<"):
            self._include_cache[filename] = False
            return False
        path = _safe_resolve(filename)
        if path is None:
            self._include_cache[filename] = False
            return False
        try:
            relative = path.relative_to(self.project_path)
        except ValueError:
            self._include_cache[filename] = False
            return False
        rel_posix = relative.as_posix()
        abs_posix = path.as_posix()
        for part in relative.parts:
            if part in self.exclude_patterns:
                self._include_cache[filename] = False
                return False
        for pattern in self.exclude_patterns:
            if fnmatch.fnmatch(rel_posix, pattern) or fnmatch.fnmatch(abs_posix, pattern):
                self._include_cache[filename] = False
                return False
            if "/" not in pattern and pattern in relative.parts:
                self._include_cache[filename] = False
                return False
        if self.include_patterns:
            result = any(
                fnmatch.fnmatch(rel_posix, pattern) or fnmatch.fnmatch(abs_posix, pattern)
                for pattern in self.include_patterns
            )
            self._include_cache[filename] = result
            return result
        self._include_cache[filename] = True
        return True

    def relative_file(self, filename):
        path = _safe_resolve(filename)
        if path is None:
            return filename
        try:
            return path.relative_to(self.project_path).as_posix()
        except ValueError:
            return path.as_posix()

    def module_from_file(self, filename):
        rel = self.relative_file(filename)
        if rel.endswith(".py"):
            rel = rel[:-3]
        parts = [part for part in rel.replace("\\", "/").split("/") if part]
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts) if parts else "__main__"

    def symbol_for_frame(self, frame):
        code = frame.f_code
        func_name = code.co_name
        file_module = self.module_from_file(code.co_filename)

        local_self = frame.f_locals.get("self")
        if local_self is not None:
            cls = local_self.__class__
            cls_module = getattr(cls, "__module__", "") or file_module
            if cls_module == "__main__":
                cls_module = file_module
            cls_qualname = getattr(cls, "__qualname__", cls.__name__)
            return f"{cls_module}.{cls_qualname}.{func_name}"

        local_cls = frame.f_locals.get("cls")
        if isinstance(local_cls, type):
            cls_module = getattr(local_cls, "__module__", "") or file_module
            if cls_module == "__main__":
                cls_module = file_module
            cls_qualname = getattr(local_cls, "__qualname__", local_cls.__name__)
            return f"{cls_module}.{cls_qualname}.{func_name}"

        qualname = getattr(code, "co_qualname", func_name)
        if "." in qualname and "<locals>" not in qualname:
            return f"{file_module}.{qualname}"
        return f"{file_module}.{func_name}"

    def test_id_for_frame(self, frame):
        return f"{self.module_from_file(frame.f_code.co_filename)}.{frame.f_code.co_name}"

    def find_current_test(self, frame):
        cursor = frame
        while cursor is not None:
            if self.is_included(cursor.f_code.co_filename) and cursor.f_code.co_name.startswith("test_"):
                test_id = self.test_id_for_frame(cursor)
                self.tests.setdefault(
                    test_id,
                    {
                        "id": test_id,
                        "status": "observed",
                        "file": self.relative_file(cursor.f_code.co_filename),
                        "runtime_calls": [],
                    },
                )
                return test_id
            cursor = cursor.f_back
        return None

    def nearest_included_caller(self, frame):
        cursor = frame
        while cursor is not None:
            if self.is_included(cursor.f_code.co_filename):
                return cursor
            cursor = cursor.f_back
        return None

    def profile(self, frame, event, arg):  # noqa: ARG002 - profile signature
        if event != "call":
            return self.profile
        try:
            if not self.is_included(frame.f_code.co_filename):
                return self.profile

            if frame.f_code.co_name.startswith("test_"):
                test_id = self.test_id_for_frame(frame)
                self.tests.setdefault(
                    test_id,
                    {
                        "id": test_id,
                        "status": "observed",
                        "file": self.relative_file(frame.f_code.co_filename),
                        "runtime_calls": [],
                    },
                )

            test_id = self.find_current_test(frame)
            if not test_id:
                return self.profile

            caller_frame = self.nearest_included_caller(frame.f_back)
            if caller_frame is None:
                return self.profile

            caller = self.symbol_for_frame(caller_frame)
            callee = self.symbol_for_frame(frame)
            if caller == callee:
                return self.profile

            call = {
                "caller": caller,
                "callee": callee,
                "caller_file": self.relative_file(caller_frame.f_code.co_filename),
                "caller_line": int(caller_frame.f_lineno),
                "callee_file": self.relative_file(frame.f_code.co_filename),
                "callee_line": int(frame.f_code.co_firstlineno),
                "test_id": test_id,
                "confidence": 0.98,
                "source": "RUNTIME_CONFIRMED",
            }
            key = (
                call["caller"],
                call["callee"],
                call["caller_file"],
                call["caller_line"],
                call["callee_file"],
                call["callee_line"],
                call["test_id"],
            )
            if key not in self.calls_by_key:
                self.calls_by_key[key] = call
                self.tests[test_id]["runtime_calls"].append(call)
        except BaseException as exc:  # profiling must never break the test run
            if len(self.diagnostics) < 20:
                self.diagnostics.append(
                    {
                        "level": "warning",
                        "message": "Profiler ignored an internal error.",
                        "details": {"error": repr(exc)},
                    }
                )
        return self.profile

    def result(self, exit_code):
        tests = []
        for test in sorted(self.tests.values(), key=lambda item: item["id"]):
            copied = dict(test)
            copied["status"] = "passed" if exit_code == 0 else "unknown"
            tests.append(copied)
        return {
            "tests": tests,
            "runtime_calls": list(self.calls_by_key.values()),
            "diagnostics": self.diagnostics,
        }


def _is_python_executable(token):
    name = Path(token).name.lower()
    return name in {"python", "python3", "python.exe"} or name.startswith("python3.")


def _coerce_exit_code(code):
    if code is None:
        return 0
    try:
        return int(code)
    except Exception:
        return 1


def run_command(command, project_path):
    if not command:
        return 2, [{"level": "error", "message": "Empty test command.", "details": {}}]

    args = list(command)
    if args and _is_python_executable(args[0]):
        args = args[1:]

    diagnostics = []
    old_argv = sys.argv[:]
    try:
        if args and args[0] == "-m" and len(args) >= 2:
            module = args[1]
            sys.argv = [module] + args[2:]
            runpy.run_module(module, run_name="__main__", alter_sys=True)
            return 0, diagnostics

        if args and Path(args[0]).name.lower() in {"pytest", "pytest.exe"}:
            sys.argv = ["pytest"] + args[1:]
            runpy.run_module("pytest", run_name="__main__", alter_sys=True)
            return 0, diagnostics

        if args and args[0].endswith(".py"):
            script = args[0]
            sys.argv = [script] + args[1:]
            runpy.run_path(script, run_name="__main__")
            return 0, diagnostics

        # Last-resort fallback. This preserves CLI behavior, but calls inside the
        # child process cannot be profiled. It is intentionally diagnosed.
        completed = subprocess.run(command, cwd=str(project_path), text=True)
        diagnostics.append(
            {
                "level": "warning",
                "message": "Command was executed as a child process, so Python calls inside it could not be traced.",
                "details": {"command": command},
            }
        )
        return int(completed.returncode), diagnostics
    except SystemExit as exc:
        return _coerce_exit_code(exc.code), diagnostics
    except BaseException as exc:
        diagnostics.append(
            {
                "level": "error",
                "message": "Test command raised an exception inside tracer runner.",
                "details": {"error": repr(exc), "traceback": traceback.format_exc()},
            }
        )
        return 1, diagnostics
    finally:
        sys.argv = old_argv


def main(argv=None):
    parser = argparse.ArgumentParser(description="Temporary runtime call tracer runner")
    parser.add_argument("--project-path", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = args.command
    if command and command[0] == "--":
        command = command[1:]

    project_path = Path(args.project_path).resolve()
    with open(args.config, "r", encoding="utf-8") as fh:
        config = json.load(fh)

    collector = TraceCollector(
        project_path=project_path,
        include_patterns=config.get("include_patterns") or [],
        exclude_patterns=config.get("exclude_patterns") or [],
    )

    start = time.monotonic()
    exit_code = 1
    command_diagnostics = []
    old_cwd = Path.cwd()
    try:
        os.chdir(project_path)
        sys.path.insert(0, str(project_path))
        sys.setprofile(collector.profile)
        exit_code, command_diagnostics = run_command(command, project_path)
    finally:
        sys.setprofile(None)
        try:
            os.chdir(old_cwd)
        except OSError:
            pass

    result = collector.result(exit_code)
    result["exit_code"] = exit_code
    result["duration_seconds"] = round(time.monotonic() - start, 6)
    result["diagnostics"].extend(command_diagnostics)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2, sort_keys=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
'''
