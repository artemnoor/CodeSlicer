"""Known local semantic-server profiles for evidence-gated LSP enrichment.

Profiles are recommendations and command contracts, never an installer.  The
caller must explicitly choose one and CodeSlicer only starts the executable
after the normal LSP confirmation boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Iterable


@dataclass(frozen=True)
class LspServerProfile:
    profile_id: str
    languages: tuple[str, ...]
    executable_names: tuple[str, ...]
    arguments: tuple[str, ...] = ()
    documentation_url: str = ""
    semantic_source: str = "language-server"
    prerequisites: tuple[str, ...] = ()
    confidence_cap: str = "likely"

    def discover(self) -> Path | None:
        for name in self.executable_names:
            value = which(name)
            if value:
                return Path(value).resolve()
        return None

    def to_dict(self, *, configured_family: str | None = None) -> dict:
        discovered = self.discover()
        configured = configured_family == self.profile_id
        return {
            "id": self.profile_id,
            "languages": list(self.languages),
            "status": "configured" if configured else ("available" if discovered else "not_installed"),
            "discovered_executable": str(discovered) if discovered else None,
            "arguments": list(self.arguments),
            "semantic_source": self.semantic_source,
            "confidence_cap": self.confidence_cap,
            "prerequisites": list(self.prerequisites),
            "documentation_url": self.documentation_url,
            "install_policy": "never installed or downloaded by CodeSlicer",
        }


# URLs are deliberately primary project documentation/repositories.  They are
# shown to the user only as provenance for the local executable they select.
PROFILES: tuple[LspServerProfile, ...] = (
    LspServerProfile("gopls", ("go",), ("gopls",), ("serve",), "https://pkg.go.dev/golang.org/x/tools/gopls", "go/types via gopls", ("Go module/workspace must be locally loadable.",)),
    LspServerProfile("clangd", ("cpp",), ("clangd", "clangd.exe"), ("--background-index",), "https://clangd.llvm.org/design/compile-commands", "Clang compiler index", ("A fresh compile_commands.json is required for compiler-accurate C/C++ evidence.",)),
    LspServerProfile("rust-analyzer", ("rust",), ("rust-analyzer", "rust-analyzer.exe"), (), "https://rust-analyzer.github.io/manual.html", "rust-analyzer semantic model", ("Cargo metadata and the selected toolchain must be locally available.",)),
    LspServerProfile("jdtls", ("java",), ("jdtls", "jdtls.cmd", "jdtls.exe"), (), "https://github.com/eclipse-jdtls/eclipse.jdt.ls", "Eclipse JDT semantic model", ("JDK 21+ and a unique local JDT.LS workspace data directory are required.",)),
    LspServerProfile("kotlin-language-server", ("kotlin",), ("kotlin-language-server", "kotlin-language-server.bat"), (), "https://kotlinlang.org/docs/components-stability.html", "Kotlin Analysis API through LSP", ("Kotlin compiler/project model must be locally available.",)),
    LspServerProfile("phpactor", ("php",), ("phpactor", "phpactor.bat"), ("language-server",), "https://github.com/phpactor/language-server", "PHP language-server symbols", ("Composer autoload/project dependencies must be locally available.",)),
    LspServerProfile("ruby-lsp", ("ruby",), ("ruby-lsp", "ruby-lsp.bat"), (), "https://github.com/Shopify/ruby-lsp", "Ruby LSP semantic navigation", ("The project's Ruby/Bundler environment must be locally available.",)),
    LspServerProfile("typescript-language-server", ("typescript", "javascript"), ("typescript-language-server", "typescript-language-server.cmd", "typescript-language-server.ps1"), ("--stdio",), "https://github.com/typescript-language-server/typescript-language-server", "tsserver language intelligence", ("The workspace TypeScript project must be locally loadable.",)),
    LspServerProfile("vscode-html-language-server", ("html",), ("vscode-html-language-server", "vscode-html-language-server.cmd", "vscode-html-language-server.ps1"), ("--stdio",), "https://github.com/microsoft/vscode/tree/main/extensions/html-language-features", "VS Code HTML language intelligence", ("Install the local Microsoft HTML language-server distribution; no download is attempted.",)),
    LspServerProfile("vscode-css-language-server", ("css",), ("vscode-css-language-server", "vscode-css-language-server.cmd", "vscode-css-language-server.ps1"), ("--stdio",), "https://github.com/microsoft/vscode/tree/main/extensions/css-language-features", "VS Code CSS language intelligence", ("Install the local Microsoft CSS language-server distribution; no download is attempted.",)),
    LspServerProfile("vue-language-server", ("vue",), ("vue-language-server", "vue-language-server.cmd", "vue-language-server.ps1"), ("--stdio",), "https://vuejs.org/guide/scaling-up/tooling", "Vue official language tooling", ("The workspace TypeScript/Vue project must be locally loadable.",)),
    LspServerProfile("svelte-language-server", ("svelte",), ("svelteserver", "svelteserver.cmd", "svelteserver.ps1"), ("--stdio",), "https://github.com/sveltejs/language-tools", "Svelte language tooling", ("The workspace Node/Svelte project must be locally loadable.",)),
    LspServerProfile("astro-language-server", ("astro",), ("astro-ls", "astro-ls.cmd", "astro-ls.ps1"), ("--stdio",), "https://docs.astro.build/en/reference/configuration-reference/", "Astro language tooling", ("The workspace Node/Astro project must be locally loadable.",)),
)


def get_lsp_server_profile(profile_id: str) -> LspServerProfile | None:
    normalized = str(profile_id or "").strip().lower()
    return next((profile for profile in PROFILES if profile.profile_id == normalized), None)


def lsp_server_profiles(languages: Iterable[str], *, configured_family: str | None = None) -> list[dict]:
    detected = {str(language).strip().lower() for language in languages}
    return [profile.to_dict(configured_family=configured_family) for profile in PROFILES if detected.intersection(profile.languages)]
