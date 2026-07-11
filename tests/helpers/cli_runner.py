"""In-process CLI runner for pytest.

The CLI tests used to spawn `python -m impact_engine.cli` repeatedly. In the
full suite that was prone to order-dependent hangs when stdout capture, child
process cleanup, and late DB tests interacted. These helpers exercise the same
`impact_engine.cli.main(argv)` entry point without leaving child processes
behind.
"""
from __future__ import annotations

import os
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class CliResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


def _exit_code(exc: SystemExit) -> int:
    if exc.code is None:
        return 0
    if isinstance(exc.code, int):
        return exc.code
    return 1


def run_cli(argv: Sequence[str], *, cwd: Path | None = None, check: bool = True) -> CliResult:
    """Run the CLI entry point in-process and capture stdout/stderr.

    This deliberately avoids subprocesses in CLI tests. It also isolates the
    current working directory so state written under `.impact_engine/` or the
    default graph/db paths cannot leak across tests.
    """
    from impact_engine.cli import main

    old_cwd = Path.cwd()
    stdout = StringIO()
    stderr = StringIO()
    returncode = 0
    args = list(argv)

    try:
        if cwd is not None:
            os.chdir(cwd)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                main(args)
            except SystemExit as exc:
                returncode = _exit_code(exc)
    finally:
        if cwd is not None:
            os.chdir(old_cwd)

    result = CliResult(args=args, returncode=returncode, stdout=stdout.getvalue(), stderr=stderr.getvalue())
    if check and result.returncode != 0:
        raise AssertionError(
            "CLI command failed\n"
            f"args={result.args!r}\n"
            f"returncode={result.returncode}\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
    return result
