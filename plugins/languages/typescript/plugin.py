from impact_engine.plugin_architecture.language_runtime import ManifestLanguagePlugin, tree_sitter_extractor


def create_plugin(manifest):
    return ManifestLanguagePlugin(manifest, extractor=tree_sitter_extractor(manifest.language))
