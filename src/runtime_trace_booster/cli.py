"""Command line interface for Runtime Trace Booster."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .graph_patch import apply_runtime_trace_to_graph
from .runner import run_runtime_trace


def _read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _write_json(path: str | Path, data: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


def _parse_patterns(values: list[str] | None) -> list[str] | None:
    return values if values else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="runtime-trace-booster")
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    trace = subparsers.add_parser("trace", help="run tests under runtime tracer")
    trace.add_argument("project_path")
    trace.add_argument("--graph", help="optional static graph JSON used for edge matching")
    trace.add_argument("--out", required=True, help="output trace result JSON path")
    trace.add_argument("--timeout", type=int, default=60, help="timeout in seconds")
    trace.add_argument("--include", action="append", help="include glob pattern; may be repeated")
    trace.add_argument("--exclude", action="append", help="exclude glob pattern; may be repeated")
    apply = subparsers.add_parser("apply", help="apply trace result to graph")
    apply.add_argument("graph_json")
    apply.add_argument("trace_result_json")
    apply.add_argument("--out", required=True, help="output patched graph JSON path")
    apply.add_argument(
        "--create-unmatched-edges",
        action="store_true",
        help="create edges from unmatched runtime calls; conservative default is false",
    )

    return parser


def _clean_remainder(remainder: list[str]) -> list[str] | None:
    if not remainder:
        return None
    command = list(remainder)
    if command and command[0] == "--":
        command = command[1:]
    return command or None


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    test_command_after_separator: list[str] | None = None
    if "--" in raw_argv:
        separator_index = raw_argv.index("--")
        test_command_after_separator = raw_argv[separator_index + 1 :]
        raw_argv = raw_argv[:separator_index]

    parser = build_parser()
    args = parser.parse_args(raw_argv)

    try:
        if args.command_name == "trace":
            graph = _read_json(args.graph) if args.graph else None
            result = run_runtime_trace(
                project_path=args.project_path,
                test_command=test_command_after_separator,
                graph=graph,
                timeout_seconds=args.timeout,
                include_patterns=_parse_patterns(args.include),
                exclude_patterns=_parse_patterns(args.exclude),
            )
            _write_json(args.out, result)
            return 0 if result.get("status") == "ok" else 1

        if args.command_name == "apply":
            graph = _read_json(args.graph_json)
            trace_result = _read_json(args.trace_result_json)
            patched = apply_runtime_trace_to_graph(
                graph,
                trace_result,
                create_unmatched_edges=bool(args.create_unmatched_edges),
            )
            _write_json(args.out, patched)
            return 0
    except Exception as exc:  # noqa: BLE001 - CLI should fail cleanly
        print(f"runtime-trace-booster: {exc}", file=sys.stderr)
        return 2

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
