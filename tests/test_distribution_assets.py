from __future__ import annotations

from pathlib import Path

from impact_engine.local_api import default_frontend_dir
from impact_engine.plugin_architecture.registry import discover_plugin_registry
from impact_engine.support_packs.paths import builtin_support_packs_root


def test_source_distribution_assets_are_discoverable():
    frontend = Path(default_frontend_dir())
    assert (frontend / "index.html").is_file()
    assert (frontend / "app.js").is_file()
    registry = discover_plugin_registry()
    assert {plugin.manifest.id for plugin in registry.language_plugins()} >= {
        "language.python",
        "language.csharp",
        "language.typescript",
    }
    packs = builtin_support_packs_root()
    assert (packs / "python" / "fastapi" / "support_pack.json").is_file()
    assert (packs / "python" / "sqlalchemy" / "support_pack.json").is_file()
    assert (packs / "javascript" / "express" / "support_pack.json").is_file()
