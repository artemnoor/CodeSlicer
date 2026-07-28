from impact_engine.plugin_architecture.language_runtime import ManifestLanguagePlugin, tree_sitter_extractor
from impact_engine.polyglot_semantics import apply_limited_polyglot_semantics


def create_plugin(manifest):
    return ManifestLanguagePlugin(manifest, extractor=tree_sitter_extractor(manifest.language), resolver=lambda context, graph: apply_limited_polyglot_semantics(graph, context.project_path))
