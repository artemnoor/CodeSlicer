from __future__ import annotations

import json
from pathlib import Path

from impact_engine.adapters.lsp import preflight_lsp
from impact_engine.build_context import find_compile_commands, inspect_build_context
from impact_engine.languages.registry import detect_languages


def _cpp_project(tmp_path: Path) -> Path:
    project = tmp_path / "cpp-project"
    (project / "build").mkdir(parents=True)
    (project / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\n", encoding="utf-8")
    (project / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    return project


def test_cpp_language_detection_and_missing_database_quality(tmp_path: Path):
    project = _cpp_project(tmp_path)
    assert detect_languages(project) == ["cpp"]
    context = inspect_build_context(project)
    assert context["build_systems"] == ["cmake"]
    assert context["compile_commands"]["status"] == "incomplete"
    assert context["semantic_quality"]["level"] == "limited"
    assert "compile_commands.json is missing" in context["semantic_quality"]["reasons"]


def test_compilation_database_is_read_from_build_without_scanning_build_as_source(tmp_path: Path):
    project = _cpp_project(tmp_path)
    database = project / "build" / "compile_commands.json"
    database.write_text(json.dumps([
        {"directory": str(project), "arguments": ["clang++", "-std=c++20", "-c", "main.cpp"], "file": "main.cpp"},
        {"directory": str(project), "arguments": ["clang++", "-O2", "-c", "main.cpp"], "file": "main.cpp"},
    ]), encoding="utf-8")
    assert find_compile_commands(project) == database.resolve()
    context = inspect_build_context(project)
    assert context["compile_commands"]["status"] == "available"
    assert context["compile_commands"]["ambiguous_translation_units"] == 1
    assert context["semantic_quality"]["level"] == "limited"
    assert context["compile_commands"]["fingerprint"]


def test_lsp_preflight_is_no_write_and_reports_cpp_readiness(tmp_path: Path):
    project = _cpp_project(tmp_path)
    before = sorted(project.rglob("*"))
    report = preflight_lsp(project)
    assert report["languages"] == ["cpp"]
    assert report["server"]["family"] == "clangd"
    assert report["server"]["status"] == "not_configured"
    assert report["index"]["status"] == "cold"
    assert report["network_used"] is False
    assert sorted(project.rglob("*")) == before
