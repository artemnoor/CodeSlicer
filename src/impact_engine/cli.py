"""Stable public CLI facade; parsing and dispatch live in focused modules."""
from __future__ import annotations

from impact_engine.cli_support import *
from impact_engine.cli_parser import build_parser
from impact_engine.cli_dispatch import dispatch_command


def main(argv: list[str] | None = None) -> None:
    executable_name = Path(sys.argv[0]).stem.lower()
    parser = build_parser("codeslicer" if executable_name in {"codeslicer", "codeslicer.exe"} else "impact-engine")
    raw_argv = list(argv if argv is not None else sys.argv[1:])
    runtime_test_command = None
    if "runtime-trace" in raw_argv and "--" in raw_argv:
        separator_index = raw_argv.index("--")
        runtime_test_command = raw_argv[separator_index + 1:]
        raw_argv = raw_argv[:separator_index]

    # ``--json`` is a global output switch, but people naturally place it
    # beside the command they are automating (``codeslicer impact ... --json``).
    # Normalize that spelling before argparse sees a subcommand.  This keeps a
    # single machine-output contract across every command without duplicating
    # the flag in each nested parser.
    if "--json" in raw_argv:
        raw_argv = [value for value in raw_argv if value != "--json"]
        raw_argv.insert(0, "--json")

    args = parser.parse_args(raw_argv)
    if getattr(args, "command", None) == "runtime-trace" and runtime_test_command is not None:
        args.test_command = runtime_test_command
    elif getattr(args, "command", None) == "runtime-trace":
        args.test_command = []

    dispatch_command(args, parser, raw_argv)


if __name__ == "__main__":
    main()
