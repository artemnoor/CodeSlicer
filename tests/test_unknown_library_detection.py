import pytest
from pathlib import Path
from impact_engine.support_packs.detection import detect_unknown_libraries_core


def test_unknown_library_detection(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    
    py_file = app_dir / "main.py"
    py_file.write_text("""
from __future__ import annotations
import app.services
import requests
import rare_requests_adapter
import os
""", encoding="utf-8")
    
    original_exists = Path.exists
    # Part 1: support pack for requests is absent
    def mock_exists_absent(self):
        if self.name == "support_packs":
            return False
        return original_exists(self)
        
    monkeypatch.setattr(Path, "exists", mock_exists_absent)
    
    unknowns = detect_unknown_libraries_core(str(tmp_path))
    
    assert "__future__" not in unknowns
    assert "app" not in unknowns
    assert "os" not in unknowns
    assert "requests" not in unknowns
    assert "rare_requests_adapter" in unknowns

    # Part 2: support pack for rare_requests_adapter is present
    monkeypatch.setattr(Path, "exists", original_exists)
    support_pack_dir = tmp_path / "support_packs" / "python" / "rare_requests_adapter"
    support_pack_dir.mkdir(parents=True)
    (support_pack_dir / "support_pack.json").write_text("{}", encoding="utf-8")
    cwd = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        unknowns_with_pack = detect_unknown_libraries_core(str(tmp_path))
    finally:
        os.chdir(cwd)
    assert "rare_requests_adapter" not in unknowns_with_pack


def test_unknown_library_detection_understands_nested_support_pack_layout_and_packages(tmp_path):
    app_dir = tmp_path / "backend" / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "main.py").write_text(
        """
from app.services import orders
from fastapi import FastAPI
from copy import deepcopy
import rare_lib
""",
        encoding="utf-8",
    )

    support_pack_dir = tmp_path / "support_packs" / "python" / "fastapi"
    support_pack_dir.mkdir(parents=True)
    (support_pack_dir / "support_pack.json").write_text("{}", encoding="utf-8")

    cwd = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        unknowns = detect_unknown_libraries_core(str(tmp_path / "backend"))
    finally:
        os.chdir(cwd)

    assert "app" not in unknowns
    assert "copy" not in unknowns
    assert "fastapi" not in unknowns
    assert "rare_lib" in unknowns


def test_unknown_library_detection_uses_hygiene_dependency_classifier(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "main.py").write_text(
        """
import uuid
from pydantic import BaseModel
import orbitlane
""",
        encoding="utf-8",
    )

    unknowns = detect_unknown_libraries_core(str(tmp_path))

    assert "uuid" not in unknowns
    assert "pydantic" not in unknowns
    assert "orbitlane" in unknowns


def test_declared_non_common_dependency_still_requires_support_pack_research(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
dependencies = ["unknown-custom-lib>=1.0.0", "pydantic>=2"]
""",
        encoding="utf-8",
    )
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text(
        """
import unknown_custom_lib
import pydantic
""",
        encoding="utf-8",
    )

    unknowns = detect_unknown_libraries_core(str(tmp_path))

    assert "unknown_custom_lib" in unknowns
    assert "pydantic" not in unknowns


def test_declared_only_unknown_dependency_requires_research(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
dependencies = ["unknown-graph-mapper-sdk>=0.0.7", "pydantic>=2"]
""",
        encoding="utf-8",
    )
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print('no imports')\n", encoding="utf-8")

    unknowns = detect_unknown_libraries_core(str(tmp_path))

    assert "unknown-graph-mapper-sdk" in unknowns
    assert "pydantic" not in unknowns


def test_unknown_library_detection_is_polyglot_and_nested_manifest_aware(tmp_path):
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "go-service").mkdir()
    (tmp_path / "java-service" / "src" / "main" / "java").mkdir(parents=True)

    (tmp_path / "frontend" / "package.json").write_text(
        """
{"dependencies":{"@unknown/contract-shadow-client":"1.0.0","react":"18.0.0"},"devDependencies":{"@testing-library/react":"1.0.0"}}
""",
        encoding="utf-8",
    )
    (tmp_path / "frontend" / "tsconfig.json").write_text(
        """
{"compilerOptions":{"paths":{"@api/*":["api/*"]}}}
""",
        encoding="utf-8",
    )
    (tmp_path / "frontend" / "src" / "client.ts").write_text(
        "import x from '@unknown/contract-shadow-client'\nimport React from 'react'\nimport '@testing-library/react'\nimport api from '@api/accounts'\n",
        encoding="utf-8",
    )
    (tmp_path / "go-service" / "go.mod").write_text(
        "module example.com/app\nrequire github.com/unknown/impact-shadow-go v0.1.0\n",
        encoding="utf-8",
    )
    (tmp_path / "go-service" / "main.go").write_text(
        'package main\nimport "github.com/unknown/impact-shadow-go/pkg"\nimport "fmt"\n',
        encoding="utf-8",
    )
    (tmp_path / "java-service" / "pom.xml").write_text(
        """
<project><dependencies><dependency><groupId>dev.unknown</groupId><artifactId>impact-shadow-java</artifactId><version>1</version></dependency></dependencies></project>
""",
        encoding="utf-8",
    )
    (tmp_path / "java-service" / "src" / "main" / "java" / "App.java").write_text(
        "import dev.unknown.shadow.Client;\nimport java.util.List;\nclass App {}\n",
        encoding="utf-8",
    )

    unknowns = detect_unknown_libraries_core(str(tmp_path))

    assert "@unknown/contract-shadow-client" in unknowns
    assert "github.com/unknown/impact-shadow-go" in unknowns
    assert "dev.unknown:impact-shadow-java" in unknowns
    assert "react" not in unknowns
    assert "@testing-library/react" not in unknowns
    assert "@api/accounts" not in unknowns
    assert "fmt" not in unknowns
    assert "java.util.List" not in unknowns
