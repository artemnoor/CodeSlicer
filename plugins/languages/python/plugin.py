from impact_engine.extractors.python_ast import extract_project
from impact_engine.plugin_architecture.language_runtime import ManifestLanguagePlugin


def create_plugin(manifest):
    return ManifestLanguagePlugin(manifest, extractor=extract_project)
