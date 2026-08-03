"""Curated local semantic backends for every language CodeSlicer detects.

This is a capability catalogue, not an installer or an implicit execution
path.  Compiler-accurate facts are accepted only after a user has explicitly
configured a local server or produced a local SCIP artifact.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from shutil import which
from typing import Iterable


def _discover(executables: tuple[str, ...]) -> str | None:
    for name in executables:
        if found := which(name):
            return found
    # `go install` places binaries in GOPATH/bin. This directory is commonly
    # absent from a fresh Windows PATH, but is still an explicit local tool.
    if any(name.startswith("scip-go") for name in executables):
        root = Path(os.environ.get("GOPATH") or Path.home() / "go") / "bin"
        for name in executables:
            candidate = root / name
            if candidate.is_file():
                return str(candidate.resolve())
    return None


@dataclass(frozen=True)
class SemanticBackend:
    backend_id: str
    languages: tuple[str, ...]
    kind: str
    executables: tuple[str, ...]
    upstream_url: str
    evidence: str
    prerequisites: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        executable = _discover(self.executables)
        return {
            "id": self.backend_id,
            "languages": list(self.languages),
            "kind": self.kind,
            "status": "available" if executable else "not_installed",
            "discovered_executable": executable,
            "upstream_url": self.upstream_url,
            "evidence": self.evidence,
            "prerequisites": list(self.prerequisites),
            "activation": "explicit local configuration or explicit SCIP indexing; never downloaded or started by analysis",
        }


# Sources are maintained as upstream project documentation.  SCIP gives the
# broadest reusable compiler/indexer interchange; framework component files
# continue to use their official LSP because no equivalent precise SCIP
# indexer exists for those template languages.
BACKENDS: tuple[SemanticBackend, ...] = (
    SemanticBackend("scip-typescript", ("typescript", "javascript"), "scip-indexer", ("scip-typescript", "scip-typescript.cmd", "scip-typescript.ps1"), "https://github.com/sourcegraph/scip", "TypeScript compiler/type-checker semantic occurrences"),
    SemanticBackend("scip-go", ("go",), "scip-indexer", ("scip-go", "scip-go.exe"), "https://github.com/scip-code/scip-go", "go/types package and implementation facts", ("A locally loadable go.mod workspace is required.",)),
    SemanticBackend("scip-java", ("java", "kotlin"), "scip-indexer", ("scip-java", "scip-java.cmd"), "https://github.com/sourcegraph/scip-java", "JVM compiler-plugin semantic occurrences", ("A supported Gradle, Maven or other configured JVM build is required.",)),
    SemanticBackend("scip-dotnet", ("csharp",), "scip-indexer", ("scip-dotnet", "scip-dotnet.exe"), "https://github.com/sourcegraph/scip-dotnet", "Roslyn solution/workspace semantic occurrences", ("A locally restored .sln or .csproj is required.",)),
    SemanticBackend("scip-clang", ("cpp",), "scip-indexer", ("scip-clang", "scip-clang.exe"), "https://github.com/sourcegraph/scip-clang", "Clang compiler semantic occurrences", ("A fresh compile_commands.json and toolchain headers are required.",)),
    SemanticBackend("rust-analyzer-scip", ("rust",), "scip-indexer", ("rust-analyzer", "rust-analyzer.exe"), "https://rust-analyzer.github.io/manual.html", "rust-analyzer Cargo semantic model", ("Cargo metadata and the selected Rust toolchain must be locally available.",)),
    SemanticBackend("scip-php", ("php",), "scip-indexer", ("scip-php", "scip-php.exe"), "https://github.com/scip-code/scip", "PHP precise-navigation SCIP artifact", ("Composer/project dependencies may be required by the chosen indexer.",)),
    SemanticBackend("scip-ruby", ("ruby",), "scip-indexer", ("scip-ruby", "scip-ruby.exe"), "https://github.com/sourcegraph/scip-ruby", "Sorbet-backed Ruby semantic occurrences", ("Sorbet annotations improve precision; untyped Ruby remains bounded.",)),
    SemanticBackend("vue-language-server", ("vue",), "language-server", ("vue-language-server", "vue-language-server.cmd", "vue-language-server.ps1"), "https://vuejs.org/guide/scaling-up/tooling", "Volar template and TypeScript component intelligence"),
    SemanticBackend("svelte-language-server", ("svelte",), "language-server", ("svelteserver", "svelteserver.cmd", "svelteserver.ps1"), "https://github.com/sveltejs/language-tools", "Svelte component language intelligence"),
    SemanticBackend("astro-language-server", ("astro",), "language-server", ("astro-ls", "astro-ls.cmd", "astro-ls.ps1"), "https://docs.astro.build/en/reference/configuration-reference/", "Astro component language intelligence"),
    SemanticBackend("vscode-html-language-server", ("html",), "language-server", ("vscode-html-language-server", "vscode-html-language-server.cmd", "vscode-html-language-server.ps1"), "https://github.com/microsoft/vscode/tree/main/extensions/html-language-features", "HTML document and embedded-language intelligence"),
    SemanticBackend("vscode-css-language-server", ("css",), "language-server", ("vscode-css-language-server", "vscode-css-language-server.cmd", "vscode-css-language-server.ps1"), "https://github.com/microsoft/vscode/tree/main/extensions/css-language-features", "CSS stylesheet intelligence"),
)


def semantic_backends_for(languages: Iterable[str]) -> list[dict]:
    selected = {str(language).lower() for language in languages}
    return [backend.to_dict() for backend in BACKENDS if selected.intersection(backend.languages)]
