from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from impact_engine.adapters.lsp import configure_lsp, probe_lsp


@pytest.mark.lsp_interop
@pytest.mark.parametrize(
    ("family", "environment", "command", "source_name", "source_text"),
    [
        ("typescript", "CODESLICER_TYPESCRIPT_LSP", "typescript-language-server", "main.ts", "export function greet() { return 'ok'; }\n"),
        ("pyright", "CODESLICER_PYRIGHT_LSP", "pyright-langserver", "main.py", "def greet() -> str:\n    return 'ok'\n"),
        ("roslyn", "CODESLICER_ROSLYN_LSP", None, "Program.cs", "class Program { static void Main() {} }\n"),
    ],
)
def test_explicit_real_lsp_probe_when_server_is_installed(tmp_path: Path, family: str, environment: str, command: str | None, source_name: str, source_text: str):
    executable = os.environ.get(environment) or (shutil.which(command) if command else None)
    if not executable:
        pytest.skip(f"{family} LSP executable is not installed/configured; no automatic installation is performed")
    project = tmp_path / family
    project.mkdir()
    (project / source_name).write_text(source_text, encoding="utf-8")
    arguments = ["--stdio"] if family in {"typescript", "pyright"} else []
    configure_lsp(project, Path(executable).resolve(), [project], arguments=arguments, timeout_ms=10_000)
    result = probe_lsp(project, timeout_ms=10_000)
    assert result["probe"]["status"] == "passed", result
    assert result["probe"].get("capabilities") is not None
