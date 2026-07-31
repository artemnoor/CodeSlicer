from impact_engine.plugin_architecture.language_runtime import ManifestLanguagePlugin, tree_sitter_extractor
from impact_engine.deep_language_semantics import apply_js_ts_semantics


def create_plugin(manifest):
    return ManifestLanguagePlugin(
        manifest,
        extractor=tree_sitter_extractor(manifest.language),
        resolver=lambda context, graph: apply_js_ts_semantics(graph, context.project_path, "typescript"),
    )
