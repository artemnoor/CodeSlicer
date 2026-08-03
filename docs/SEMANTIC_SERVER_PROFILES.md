# Local semantic-server profiles

CodeSlicer keeps its canonical graph deterministic and local. Tree-sitter
extracts structural facts; a configured compiler or language server can add a
separate, bounded evidence overlay for exact definitions, references and
implementations. It never silently downloads, installs, or starts a server.

## Use

First inspect the project without writing or starting a process:

```powershell
impact-engine --json adapters lsp preflight C:\work\project
```

Then explicitly configure a profile that is already installed locally. This
only writes local adapter configuration; `probe` is the explicit process start.

```powershell
impact-engine --json adapters lsp configure-profile C:\work\project rust-analyzer `
  --workspace-root C:\work\project
impact-engine --json adapters lsp probe C:\work\project
```

| Language | Profile | Semantic source | Required local context |
| --- | --- | --- | --- |
| Go | `gopls` | Go types | Loadable Go module/workspace |
| C/C++ | `clangd` | Clang compiler index | Fresh `compile_commands.json` |
| Rust | `rust-analyzer` | Rust analyzer | Cargo metadata and toolchain |
| Java | `jdtls` | Eclipse JDT | JDK 21+ and unique JDT.LS workspace data |
| Kotlin | `kotlin-language-server` | Kotlin Analysis API through LSP | Local compiler/project model |
| PHP | `phpactor` | PHP language-server | Local Composer autoload/dependencies |
| Ruby | `ruby-lsp` | Ruby LSP | Local Bundler environment |
| TypeScript / JavaScript | `typescript-language-server` | tsserver | Loadable local TypeScript project |
| HTML | `vscode-html-language-server` | VS Code HTML language service | Locally installed HTML language server |
| CSS / SCSS / Less | `vscode-css-language-server` | VS Code CSS language service | Locally installed CSS language server |
| Vue / Svelte / Astro | corresponding profile | framework language tooling | Loadable local Node project |

For C#, CodeSlicer retains its deterministic local resolver and marks Roslyn
`SemanticModel` enrichment separately. Roslyn needs the project compilation,
references and compiler options; it is intentionally not faked from filenames.
A team that provisions a compatible local Roslyn LSP host can use the generic
`adapters lsp configure` command; CodeSlicer does not invent a portable launch
profile for a host that the installed SDK has not explicitly supplied.

## Evidence boundary

LSP output is an overlay with source ranges and provenance. It is bounded,
freshness-checked and never changes canonical review risk on its own. Ambiguous
or stale mappings remain unresolved. This keeps external compiler intelligence
useful without making a user-configured process an unverified source of risk.

## Primary sources

- Go package loading and type information: <https://pkg.go.dev/golang.org/x/tools/go/packages>
- clangd compilation database: <https://clangd.llvm.org/design/compile-commands>
- rust-analyzer: <https://rust-analyzer.github.io/manual.html>
- Eclipse JDT.LS: <https://github.com/eclipse-jdtls/eclipse.jdt.ls>
- Kotlin component stability / Analysis API: <https://kotlinlang.org/docs/components-stability.html>
- Roslyn semantic analysis: <https://learn.microsoft.com/en-us/dotnet/csharp/roslyn-sdk/get-started/semantic-analysis>
- VS Code HTML/CSS language services: <https://github.com/microsoft/vscode/tree/main/extensions/html-language-features>
- Vue official tooling: <https://vuejs.org/guide/scaling-up/tooling>
- Ruby LSP: <https://github.com/Shopify/ruby-lsp>
