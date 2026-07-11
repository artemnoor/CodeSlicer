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
        call_resolution="limited",
        endpoint_resolution=True,
        framework_rules=True,
        production_semantic_baseline=False,
        notes=(
            "Extended structural provider.",
            "Endpoint bridge can resolve bounded constants, wrappers, and React/client patterns.",
            "Not full JavaScript compiler semantic parity.",
        ),
    ),
    confidence_policy="lower-confidence structural edges plus bounded endpoint bridge evidence",
    diagnostics_label="JavaScript extended structural semantics",
)

TYPESCRIPT_SEMANTICS = LanguageSemanticProvider(
    language_id="typescript",
    provider_id="typescript_tree_sitter_endpoint_provider",
    capabilities=LanguageSemanticCapabilities(
        structural_extraction=True,
        import_resolution=True,
        call_resolution="limited",
        endpoint_resolution=True,
        framework_rules=True,
        production_semantic_baseline=False,
        notes=(
            "Extended structural provider.",
            "Supports bounded tsconfig alias/path-helper/API-wrapper endpoint matching.",
            "Not full TypeScript compiler semantic parity.",
        ),
    ),
    confidence_policy="lower-confidence structural edges plus bounded endpoint bridge evidence",
    diagnostics_label="TypeScript extended structural semantics",
)

GO_SEMANTICS = LanguageSemanticProvider(
    language_id="go",
    provider_id="go_tree_sitter_structural",
    capabilities=LanguageSemanticCapabilities(
        structural_extraction=True,
        import_resolution=True,
        call_resolution="limited",
        endpoint_resolution=False,
        framework_rules=False,
        production_semantic_baseline=False,
        notes=(
            "Tree-sitter structural extraction only.",
            "Limited call facts; no production Go framework semantic resolver yet.",
        ),
    ),
    confidence_policy="low-confidence structural facts",
    diagnostics_label="Go structural semantics",
)

JAVA_SEMANTICS = LanguageSemanticProvider(
    language_id="java",
    provider_id="java_tree_sitter_structural",
    capabilities=LanguageSemanticCapabilities(
        structural_extraction=True,
        import_resolution=True,
        call_resolution="limited",
        endpoint_resolution=False,
        framework_rules=False,
        production_semantic_baseline=False,
        notes=(
            "Tree-sitter structural extraction only.",
            "Limited call facts; no production Java framework semantic resolver yet.",
        ),
    ),
    confidence_policy="low-confidence structural facts",
    diagnostics_label="Java structural semantics",
)

PROVIDERS = {
    provider.language_id: provider
    for provider in (
        PYTHON_SEMANTICS,
        JAVASCRIPT_SEMANTICS,
        TYPESCRIPT_SEMANTICS,
        GO_SEMANTICS,
        JAVA_SEMANTICS,
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
