import pytest
from pathlib import Path
from impact_engine.languages.registry import list_language_profiles, get_language_profile, detect_languages
from impact_engine.languages.semantics import build_language_capability_diagnostics, get_language_semantic_provider


def test_list_language_profiles():
    profiles = list_language_profiles()
    assert len(profiles) >= 5
    ids = {p.language_id for p in profiles}
    assert "python" in ids
    assert "javascript" in ids
    assert "typescript" in ids
    assert "go" in ids
    assert "java" in ids


def test_get_language_profile():
    python = get_language_profile("python")
    assert python is not None
    assert python.display_name == "Python"
    assert ".py" in python.file_extensions
    assert python.semantic_provider is not None
    assert python.semantic_provider.capabilities.production_semantic_baseline is True
    
    nonexistent = get_language_profile("nonexistent")
    assert nonexistent is None


def test_detect_languages(tmp_path):
    # 1. Empty dir should detect nothing
    assert detect_languages(tmp_path) == []
    
    # 2. Python file
    (tmp_path / "main.py").write_text("print(1)")
    assert detect_languages(tmp_path) == ["python"]
    
    # 3. JavaScript package.json
    (tmp_path / "package.json").write_text("{}")
    assert "javascript" in detect_languages(tmp_path)
    assert "typescript" in detect_languages(tmp_path) # ts also shares package.json


def test_language_semantic_provider_capabilities_are_honest():
    python = get_language_semantic_provider("python")
    typescript = get_language_semantic_provider("typescript")
    go = get_language_semantic_provider("go")
    java = get_language_semantic_provider("java")

    assert python is not None
    assert python.capabilities.production_semantic_baseline is True
    assert python.capabilities.call_resolution == "semantic"
    assert python.capabilities.endpoint_resolution is True

    assert typescript is not None
    assert typescript.capabilities.production_semantic_baseline is False
    assert typescript.capabilities.call_resolution == "limited"
    assert typescript.capabilities.endpoint_resolution is True
    assert typescript.capabilities.framework_rules is True

    assert go is not None
    assert go.capabilities.production_semantic_baseline is False
    assert go.capabilities.structural_extraction is True
    assert go.capabilities.call_resolution == "limited"
    assert go.capabilities.endpoint_resolution is False

    assert java is not None
    assert java.capabilities.production_semantic_baseline is False
    assert java.capabilities.structural_extraction is True
    assert java.capabilities.call_resolution == "limited"
    assert java.capabilities.framework_rules is False


def test_build_language_capability_diagnostics_contains_unknown_fallback():
    diagnostics = build_language_capability_diagnostics(["python", "go", "unknownlang"])

    assert diagnostics["python"]["capabilities"]["production_semantic_baseline"] is True
    assert diagnostics["go"]["capabilities"]["structural_extraction"] is True
    assert diagnostics["unknownlang"]["provider_id"] == "unknown"
    assert diagnostics["unknownlang"]["capabilities"]["structural_extraction"] is False
