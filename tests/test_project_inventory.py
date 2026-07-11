import pytest
from pathlib import Path
import json
from impact_engine.inventory.scanner import scan_project_inventory


def test_project_inventory_scanner(tmp_path):
    # 1. Create a mock project structure
    # Directories
    (tmp_path / "app" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "repositories").mkdir(parents=True, exist_ok=True)
    
    # Python files
    (tmp_path / "app" / "services" / "order_service.py").write_text("""
from __future__ import annotations
import os
from app.repositories import OrderRepository  # Local import
import requests  # External import
""", encoding="utf-8")
    
    # Requirements.txt
    (tmp_path / "requirements.txt").write_text("""
requests>=2.28.0
pytest==7.0.0
# Comment
""", encoding="utf-8")
    
    # package.json
    (tmp_path / "package.json").write_text(json.dumps({
        "dependencies": {
            "lodash": "^4.17.21"
        }
    }), encoding="utf-8")
    
    # run scan
    inv = scan_project_inventory(tmp_path)
    
    # Assert package manifests
    assert "requirements.txt" in inv.package_manifests
    assert "package.json" in inv.package_manifests
    
    # Assert declared dependencies
    assert "requests" in inv.declared_dependencies
    assert "pytest" in inv.declared_dependencies
    assert "lodash" in inv.declared_dependencies
    
    # Assert local modules
    assert "app" in inv.local_modules
    
    # Assert external imports (must contain requests, but NOT app and NOT os/future)
    assert "requests" in inv.external_imports
    assert "app" not in inv.external_imports
    assert "os" not in inv.external_imports
    assert "__future__" not in inv.external_imports


def test_project_inventory_scans_nested_polyglot_manifests_and_imports(tmp_path):
    (tmp_path / "backend" / "app").mkdir(parents=True)
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "go-service").mkdir()
    (tmp_path / "java-service" / "src" / "main" / "java").mkdir(parents=True)

    (tmp_path / "backend" / "pyproject.toml").write_text(
        """
[project]
dependencies = ["orbitlane>=1", "pydantic>=2"]
""",
        encoding="utf-8",
    )
    (tmp_path / "backend" / "app" / "main.py").write_text("import orbitlane\nimport uuid\n", encoding="utf-8")
    (tmp_path / "frontend" / "package.json").write_text(
        json.dumps({"dependencies": {"@unknown/contract-shadow-client": "^1.0.0", "react": "^18.0.0"}}),
        encoding="utf-8",
    )
    (tmp_path / "frontend" / "tsconfig.json").write_text(
        json.dumps({"compilerOptions": {"paths": {"@api/*": ["api/*"]}}}),
        encoding="utf-8",
    )
    (tmp_path / "frontend" / "src" / "api.ts").write_text(
        "import client from '@unknown/contract-shadow-client'\nimport React from 'react'\n",
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

    inv = scan_project_inventory(tmp_path)

    assert "backend/pyproject.toml" in inv.package_manifests
    assert "frontend/package.json" in inv.package_manifests
    assert "frontend/tsconfig.json" in inv.package_manifests
    assert "go-service/go.mod" in inv.package_manifests
    assert "java-service/pom.xml" in inv.package_manifests
    assert "orbitlane" in inv.declared_dependencies_by_ecosystem["python"]
    assert "@unknown/contract-shadow-client" in inv.declared_dependencies_by_ecosystem["typescript"]
    assert "github.com/unknown/impact-shadow-go" in inv.declared_dependencies_by_ecosystem["go"]
    assert "dev.unknown:impact-shadow-java" in inv.declared_dependencies_by_ecosystem["java"]
    assert "@api" in inv.local_modules_by_ecosystem["typescript"]
    assert "orbitlane" in inv.external_imports_by_ecosystem["python"]
    assert "@unknown/contract-shadow-client" in inv.external_imports_by_ecosystem["typescript"]
    assert "github.com/unknown/impact-shadow-go/pkg" in inv.external_imports_by_ecosystem["go"]
    assert "dev.unknown.shadow.Client" in inv.external_imports_by_ecosystem["java"]
