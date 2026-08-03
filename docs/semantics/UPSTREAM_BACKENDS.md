# Compiler-backed semantics: upstream backends

CodeSlicer does not attempt to recreate compilers or language servers. Its
canonical graph stays local and evidence-gated; a compiler-backed semantic
source is an explicit, separately fresh overlay. This gives a language the
same *kind* of proof that Python receives from its semantic resolver, without
claiming that a dynamic runtime can be made statically perfect.

## Selection

The common artifact is [SCIP](https://github.com/scip-code/scip): a
language-agnostic protocol for definitions, references and implementations.
The upstream SCIP project lists ready indexers for TypeScript/JavaScript, Go,
Java/Kotlin, C#, C/C++, Rust, Python, Ruby and PHP. For template languages
where no equivalent precise SCIP indexer exists, CodeSlicer uses the language's
official LSP rather than guessing from template syntax.

| Languages | Chosen upstream semantic engine | Required local context |
| --- | --- | --- |
| TypeScript, JavaScript | [scip-typescript](https://github.com/scip-code/scip) / TypeScript compiler | `package.json`, `tsconfig` when applicable |
| Go | [scip-go](https://github.com/scip-code/scip-go) / `go/types` | loadable `go.mod` workspace |
| Java, Kotlin | [scip-java](https://github.com/sourcegraph/scip-java) and JDT LS/Kotlin tooling | supported Maven, Gradle or configured JVM build |
| C# | [scip-dotnet](https://github.com/sourcegraph/scip-dotnet) / Roslyn | restored `.sln` or `.csproj` |
| C, C++ | [scip-clang](https://github.com/sourcegraph/scip-clang) / clangd | fresh `compile_commands.json` and toolchain headers |
| Rust | [rust-analyzer](https://rust-analyzer.github.io/manual.html) | Cargo metadata and selected toolchain |
| PHP | [Phpactor](https://phpactor.readthedocs.io/en/master/lsp/support.html) plus SCIP when supplied | Composer/project environment |
| Ruby | [Ruby LSP](https://github.com/Shopify/ruby-lsp) and scip-ruby | Bundler; Sorbet annotations improve precision |
| Vue | [Vue - Official / Volar](https://vuejs.org/guide/scaling-up/tooling) | local Node/Vue project |
| Svelte | [Svelte language tools](https://github.com/sveltejs/language-tools) | local Node/Svelte project |
| Astro | [Astro language server](https://docs.astro.build/en/reference/configuration-reference/) | local Node/Astro project |
| HTML, CSS | Microsoft VS Code HTML/CSS language services | local server distribution |

## Safety and admission

Analysis and review never download, start or trust one of these programs
implicitly. `impact-engine adapters lsp preflight <project>` reports the
relevant backends and whether a local executable is discoverable. A user must
explicitly configure a language server or explicitly run/import a SCIP
artifact. The importer validates the artifact, source path and freshness; an
unverified overlay cannot raise canonical review confidence.

CodeSlicer now has tested native output contracts for `scip-typescript` and
`scip-go`. Other listed tools are exposed as explicit local artifact inputs
until their exact command, output location and project prerequisites have been
verified on a real project. This is deliberate: accepting their generated
standard SCIP is already supported, but inventing an invocation contract would
be less reliable than asking for the already-generated local artifact.

## Real validation on 2026-08-03

| Upstream engine | Public project | Result |
| --- | --- | --- |
| scip-go 0.2.7 | [Gin](https://github.com/gin-gonic/gin) | Native contract wrote a 3.83 MB SCIP artifact to `.codeslicer`; CodeSlicer decoded 3,596 nodes / 38,353 edges and verified its Windows `file://C:%5C...` project URI. |
| scip-typescript 0.4.0 | [Express](https://github.com/expressjs/express) | Native contract wrote a 0.67 MB SCIP artifact to `.codeslicer`; CodeSlicer decoded 2,493 nodes / 13,341 edges and marked it fresh/verified. |

The external projects' dependency installation and own test suites were not
run. These are end-to-end validations of the local CodeSlicer → upstream
indexer → SCIP decoder/import/freshness path.
