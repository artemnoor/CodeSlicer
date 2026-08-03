"""Language semantic provider registry.

This layer is intentionally descriptive. It exposes honest capability flags for
each supported language instead of pretending every language has Python parity.
"""
from __future__ import annotations

from impact_engine.languages.models import LanguageSemanticCapabilities, LanguageSemanticProvider


PYTHON_SEMANTICS = LanguageSemanticProvider(
    language_id="python",
    provider_id="python_ast_precision",
    capabilities=LanguageSemanticCapabilities(
        structural_extraction=True,
        import_resolution=True,
        call_resolution="semantic",
        endpoint_resolution=True,
        framework_rules=True,
        production_semantic_baseline=True,
        notes=(
            "Production-supported semantic baseline.",
            "Supports Python AST facts, DI/self.attr/call receiver resolution, and support-pack framework hooks.",
        ),
    ),
    confidence_policy="high-confidence semantic resolver; inferred edges may reach production confidence when evidence is complete",
    diagnostics_label="Python semantic baseline",
)

JAVASCRIPT_SEMANTICS = LanguageSemanticProvider(
    language_id="javascript",
    provider_id="javascript_tree_sitter_endpoint_provider",
    capabilities=LanguageSemanticCapabilities(
        structural_extraction=True,
        import_resolution=True,
        call_resolution="semantic",
        endpoint_resolution=True,
        framework_rules=True,
        production_semantic_baseline=False,
        notes=(
            "Evidence-first local semantic provider.",
            "Resolves explicit local imports, re-exports, direct calls, bounded endpoint wrappers and React/client patterns.",
            "Dynamic imports, prototype mutation and runtime monkey patching remain unresolved.",
        ),
    ),
    confidence_policy="explicit local declaration/import edges are exact; dynamic JavaScript remains limited",
    diagnostics_label="JavaScript local semantic baseline",
)

TYPESCRIPT_SEMANTICS = LanguageSemanticProvider(
    language_id="typescript",
    provider_id="typescript_tree_sitter_endpoint_provider",
    capabilities=LanguageSemanticCapabilities(
        structural_extraction=True,
        import_resolution=True,
        call_resolution="semantic",
        endpoint_resolution=True,
        framework_rules=True,
        production_semantic_baseline=False,
        notes=(
            "Evidence-first local semantic provider.",
            "Resolves explicit local imports, re-exports, direct calls, tsconfig-style aliases and endpoint wrappers.",
            "Compiler-only overload/type-narrowing facts remain unresolved without an explicit LSP/SCIP overlay.",
        ),
    ),
    confidence_policy="explicit local declaration/import edges are exact; compiler-only facts require LSP/SCIP",
    diagnostics_label="TypeScript local semantic baseline",
)

GO_SEMANTICS = LanguageSemanticProvider(
    language_id="go",
    provider_id="go_tree_sitter_structural",
    capabilities=LanguageSemanticCapabilities(
        structural_extraction=True,
        import_resolution=True,
        call_resolution="semantic",
        endpoint_resolution=True,
        framework_rules=True,
        production_semantic_baseline=False,
        notes=(
            "Local typed receiver and struct-field semantic resolution.",
            "Literal Gin route registrations are resolved without a network dependency.",
            "Interface dispatch, reflection and generated clients remain unresolved unless an explicit LSP/SCIP overlay is added.",
        ),
    ),
    confidence_policy="typed local receiver/field and literal route edges are evidence-backed; interface dispatch is limited",
    diagnostics_label="Go local semantic baseline",
)

JAVA_SEMANTICS = LanguageSemanticProvider(
    language_id="java",
    provider_id="java_tree_sitter_structural",
    capabilities=LanguageSemanticCapabilities(
        structural_extraction=True,
        import_resolution=True,
        call_resolution="semantic",
        endpoint_resolution=True,
        framework_rules=True,
        production_semantic_baseline=False,
        notes=(
            "Local typed receiver, field and constructor-injection resolution.",
            "Literal Spring route annotations are resolved locally.",
            "Reflection, proxy dispatch and complex generic overload resolution require an explicit LSP/SCIP overlay.",
        ),
    ),
    confidence_policy="typed local calls and literal Spring routes are evidence-backed; proxy/reflection paths are limited",
    diagnostics_label="Java local semantic baseline",
)

CSHARP_SEMANTICS = LanguageSemanticProvider(
    language_id="csharp",
    provider_id="csharp_structural_local",
    capabilities=LanguageSemanticCapabilities(
        structural_extraction=True,
        import_resolution=True,
        call_resolution="semantic",
        endpoint_resolution=True,
        framework_rules=True,
        production_semantic_baseline=False,
        notes=(
            "Local deterministic C# semantic provider; no SDK, Roslyn restore, or network is required.",
            "Supports namespaces, declarations, typed member calls, project references and ASP.NET/DI/MediatR/EF evidence packs.",
            "Roslyn/compiler binding, overload resolution, source generators and reflection remain explicitly limited.",
        ),
    ),
    confidence_policy="direct syntax and exact local references are confirmed; heuristic receiver/framework bindings are capped at likely",
    diagnostics_label="C# local semantic baseline",
)

CPP_SEMANTICS = LanguageSemanticProvider(
    language_id="cpp",
    provider_id="cpp_tree_sitter_plus_lsp",
    capabilities=LanguageSemanticCapabilities(
        structural_extraction=True,
        import_resolution=True,
        call_resolution="limited",
        endpoint_resolution=False,
        framework_rules=False,
        production_semantic_baseline=False,
        notes=(
            "Structural C/C++ facts are local and deliberately limited.",
            "Compiler-accurate navigation requires a fresh compilation database, selected toolchain, generated headers, and an explicitly configured language server.",
        ),
    ),
    confidence_policy="structural C/C++ facts are limited; LSP evidence is capped until a fresh compilation database and exact range mapping are available",
    diagnostics_label="C/C++ structural and LSP-assisted semantics",
)


def _generic_tree_sitter_semantics(language_id: str, display_name: str) -> LanguageSemanticProvider:
    return LanguageSemanticProvider(
        language_id=language_id,
        provider_id=f"{language_id}_tree_sitter_generic_structural",
        capabilities=LanguageSemanticCapabilities(
            structural_extraction=True,
            import_resolution=True,
            call_resolution="limited",
            endpoint_resolution=False,
            framework_rules=False,
            production_semantic_baseline=False,
            notes=(
                f"Native Tree-sitter structural extraction for {display_name}.",
                "Reports declarations, source ranges, imports and direct calls; type-aware and framework-specific resolution is explicitly unavailable.",
            ),
        ),
        confidence_policy="structural facts only; unresolved calls must not be presented as confirmed behavioural impact",
        diagnostics_label=f"{display_name} structural semantics",
    )


RUST_SEMANTICS = _generic_tree_sitter_semantics("rust", "Rust")
KOTLIN_SEMANTICS = _generic_tree_sitter_semantics("kotlin", "Kotlin")
PHP_SEMANTICS = _generic_tree_sitter_semantics("php", "PHP")
RUBY_SEMANTICS = _generic_tree_sitter_semantics("ruby", "Ruby")
HTML_SEMANTICS = _generic_tree_sitter_semantics("html", "HTML")
CSS_SEMANTICS = _generic_tree_sitter_semantics("css", "CSS and stylesheet sources")
VUE_SEMANTICS = _generic_tree_sitter_semantics("vue", "Vue single-file components")
SVELTE_SEMANTICS = _generic_tree_sitter_semantics("svelte", "Svelte components")
ASTRO_SEMANTICS = _generic_tree_sitter_semantics("astro", "Astro components")

PROVIDERS = {
    provider.language_id: provider
    for provider in (
        PYTHON_SEMANTICS,
        JAVASCRIPT_SEMANTICS,
        TYPESCRIPT_SEMANTICS,
        GO_SEMANTICS,
        JAVA_SEMANTICS,
        CSHARP_SEMANTICS,
        CPP_SEMANTICS,
        RUST_SEMANTICS,
        KOTLIN_SEMANTICS,
        PHP_SEMANTICS,
        RUBY_SEMANTICS,
        HTML_SEMANTICS,
        CSS_SEMANTICS,
        VUE_SEMANTICS,
        SVELTE_SEMANTICS,
        ASTRO_SEMANTICS,
    )
}


def get_language_semantic_provider(language_id: str) -> LanguageSemanticProvider | None:
    return PROVIDERS.get(language_id)


def list_language_semantic_providers() -> list[LanguageSemanticProvider]:
    return list(PROVIDERS.values())


def build_language_capability_diagnostics(languages: list[str]) -> dict:
    result = {}
    for language_id in languages:
        provider = get_language_semantic_provider(language_id)
        if provider:
            result[language_id] = provider.to_dict()
        else:
            result[language_id] = {
                "language_id": language_id,
                "provider_id": "unknown",
                "capabilities": LanguageSemanticCapabilities().to_dict(),
                "confidence_policy": "unsupported language",
                "diagnostics_label": "Unsupported language",
            }
    return result
