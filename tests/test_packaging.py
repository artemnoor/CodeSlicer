from __future__ import annotations

import importlib
import tomllib
from pathlib import Path
from importlib import metadata

ROOT = Path(__file__).resolve().parents[1]


def test_import_impact_engine():
    import impact_engine
    assert impact_engine.__version__ == "0.4.0"


def test_import_key_modules():
    modules = [
        "impact_engine.analysis.pipeline",
        "impact_engine.extractors.python_ast",
        "impact_engine.extractors.tree_sitter.adapter",
        "impact_engine.resolution.engine",
        "impact_engine.impact",
        "impact_engine.adapters.graphify",
        "impact_engine.research.fetcher",
        "impact_engine.research.workflow",
        "impact_engine.mcp.server",
        "impact_engine.cli",
    ]
    for mod_name in modules:
        assert importlib.import_module(mod_name) is not None


def test_pyproject_dependencies_console_scripts_and_network_dependency_declaration():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = set(data["project"].get("dependencies", []))
    scripts = data["project"].get("scripts", {})

    assert "tree-sitter" in deps
    assert "tree-sitter-language-pack" in deps
    assert "requests" in deps
    assert "httpx" not in deps
    assert scripts["impact-engine"] == "impact_engine.cli:main"
    assert scripts["impact-engine-mcp"] == "impact_engine.mcp.server:main"

    source_text = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "src" / "impact_engine").rglob("*.py"))
    if "import requests" in source_text or "from requests" in source_text:
        assert "requests" in deps
    if "import httpx" in source_text or "from httpx" in source_text:
        assert "httpx" in deps


def test_installed_entry_points_are_declared_when_distribution_metadata_available():
    eps = metadata.entry_points(group="console_scripts")
    values = {ep.name: ep.value for ep in eps if ep.name in {"impact-engine", "impact-engine-mcp"}}
    # In editable installs this proves the real package metadata exposes the scripts.
    assert values.get("impact-engine") == "impact_engine.cli:main"
    assert values.get("impact-engine-mcp") == "impact_engine.mcp.server:main"
