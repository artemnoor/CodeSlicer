from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from impact_engine.remote_registry import (
    LanguageProfileRecord,
    RegistryClient,
    RegistryConfig,
    ResearchRequestRecord,
)
from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.remote_registry.sync import sync_registry_for_inventory
from impact_engine.remote_registry.worker import process_local_research_queue


def _minimal_pack(library: str = "examplelib") -> dict:
    return {
        "library": library,
        "version_range": ">=1.0",
        "language": "python",
        "ecosystem": "python",
        "status": "experimental",
        "trust_level": "experimental",
        "sources": [{"type": "docs", "url": "https://example.com/docs"}],
        "patterns": [],
        "edge_rules": [
            {
                "id": "example.rule",
                "match": {"kind": "decorator"},
                "emit": {
                    "kind": "CALLS",
                    "source": "SUPPORT_PACK",
                    "confidence": 0.6,
                    "description": "example",
                },
            }
        ],
        "confidence_rules": [],
        "playground_cases": [],
    }


def test_registry_client_caches_language_profiles_and_support_packs(tmp_path):
    client = RegistryClient(RegistryConfig(cache_root=str(tmp_path / "cache")))

    profile_path = client.cache_language_profile(
        LanguageProfileRecord(
            id="python",
            display_name="Python",
            parser_kind="python_ast",
            capabilities={"call_resolution": True},
        )
    )
    assert profile_path.endswith("languages/python/language_profile.json")
    assert client.get_cached_language_profile("python")["parser_kind"] == "python_ast"

    result = client.cache_support_pack(_minimal_pack())
    assert result["status"] == "cached"
    cached = client.get_cached_support_pack("python", "examplelib")
    assert cached is not None
    assert cached["library"] == "examplelib"


def test_registry_client_uses_local_sqlite_as_source_of_truth(tmp_path):
    client = RegistryClient(
        RegistryConfig(
            cache_root=str(tmp_path / "cache"),
            local_db_path=str(tmp_path / "impact_registry.sqlite"),
        )
    )
    result = client.cache_support_pack(_minimal_pack("sqlitepack"))
    assert result["status"] == "cached"
    assert client.connection_status()["mode"] == "sqlite"
    assert client.pull_support_pack("python", "sqlitepack")["source"] == "local_db"
    assert (tmp_path / "impact_registry.sqlite").exists()


def test_registry_client_persists_research_request_in_sqlite_and_export(tmp_path):
    client = RegistryClient(
        RegistryConfig(
            cache_root=str(tmp_path / "cache"),
            local_db_path=str(tmp_path / "impact_registry.sqlite"),
        )
    )
    result = client.create_research_request(
        ResearchRequestRecord(ecosystem="python", library_name="newlib")
    )
    assert result["status"] == "queued_local_db"
    assert Path(result["path"]).exists()


def test_registry_client_builds_support_pack_record_with_checksum(tmp_path):
    client = RegistryClient(RegistryConfig(cache_root=str(tmp_path / "cache")))
    record = client.support_pack_record_from_pack(_minimal_pack(), version="1.2.3")

    assert record.pack_key == "python/examplelib"
    assert record.library_id == "python/examplelib"
    assert record.version == "1.2.3"
    assert len(record.checksum_sha256) == 64
    assert record.source_urls == ["https://example.com/docs"]


def test_registry_client_creates_local_research_request_without_remote_credentials(tmp_path):
    client = RegistryClient(RegistryConfig(cache_root=str(tmp_path / "cache")))
    result = client.create_research_request(
        ResearchRequestRecord(ecosystem="python", library_name="unknownlib")
    )

    assert result["status"] == "queued_local"
    assert Path(result["path"]).exists()
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert payload["library_name"] == "unknownlib"


def test_registry_cli_status_and_cache_pack(tmp_path):
    pack_path = tmp_path / "support_pack.json"
    pack_path.write_text(json.dumps(_minimal_pack()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "impact_engine.cli",
            "--json",
            "registry",
            "cache-pack",
            str(pack_path),
        ],
        cwd=Path(__file__).parent.parent,
        timeout=30,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    data = json.loads(completed.stdout)
    assert data["status"] == "cached"


def test_registry_sync_pulls_cached_pack_without_research_request(tmp_path):
    client = RegistryClient(RegistryConfig(cache_root=str(tmp_path / "cache")))
    client.cache_support_pack(_minimal_pack("mysterylibx"))

    inventory = {
        "external_imports_by_ecosystem": {"python": ["mysterylibx"]},
        "declared_dependencies_by_ecosystem": {"python": ["mysterylibx"]},
        "dev_dependencies_by_ecosystem": {},
        "local_modules_by_ecosystem": {},
    }
    result = sync_registry_for_inventory(
        inventory,
        support_pack_root=tmp_path / "empty_packs",
        create_research_requests=True,
        client=client,
    )

    assert result["status"] == "ok"
    assert result["pulled"] == [{"ecosystem": "python", "library": "mysterylibx", "source": "cache"}]
    assert result["research_requests"] == []


def test_analyze_remote_registry_creates_research_request_for_missing_pack(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        "[project]\nname='sample'\nversion='0.1.0'\ndependencies=['unknownlib>=1']\n",
        encoding="utf-8",
    )
    (project / "main.py").write_text("import unknownlib\n\nunknownlib.run()\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = analyze_project_core(str(project), enable_remote_registry=True)

    registry = result["graph"]["metadata"]["local_registry"]
    assert registry["status"] == "missing_packs"
    assert {"ecosystem": "python", "library": "unknownlib"} in registry["missing"]
    request_path = tmp_path / ".impact_engine" / "registry_cache" / "research_requests" / "python" / "unknownlib" / "request.json"
    assert request_path.exists()


def test_registry_worker_prepares_local_research_queue(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("import unknownlib\nunknownlib.run()\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    client = RegistryClient(RegistryConfig(cache_root=str(tmp_path / ".impact_engine" / "registry_cache")))
    client.create_research_request(ResearchRequestRecord(ecosystem="python", library_name="unknownlib"))

    result = process_local_research_queue(project_path=str(project), cache_root=tmp_path / ".impact_engine" / "registry_cache")

    assert result["status"] == "ok"
    assert result["processed"] == 1
    assert result["items"][0]["status"] == "prepared"
    assert (tmp_path / ".impact_engine" / "research_workflows" / result["items"][0]["workflow_id"] / "ai_input.json").exists()


def test_registry_lifecycle_status_and_documentation_change_detection(tmp_path):
    client = RegistryClient(RegistryConfig(
        cache_root=str(tmp_path / "cache"),
        local_db_path=str(tmp_path / "impact_registry.sqlite"),
    ))
    simulated = client.simulate_library_lifecycle("python", "lifecyclelib", "https://example.com/docs")
    assert simulated["status"] == "ok"
    assert simulated["library"]["library"]["status"] == "research_requested"
    assert simulated["library"]["library"]["docs_url"] == "https://example.com/docs"

    first = client.record_documentation_check("python", "lifecyclelib", "https://example.com/docs", "hash-1")
    second = client.record_documentation_check("python", "lifecyclelib", "https://example.com/docs", "hash-2")
    assert first["changed"] is False
    assert second["changed"] is True
    assert client.revalidation_candidates()


def test_registry_support_pack_approval_transition(tmp_path):
    client = RegistryClient(RegistryConfig(
        cache_root=str(tmp_path / "cache"),
        local_db_path=str(tmp_path / "impact_registry.sqlite"),
    ))
    client.cache_support_pack(_minimal_pack("approvable"))
    result = client.approve_support_pack("python/approvable@1.0.0", "verified_on_fixture", "qa", "fixture passed")
    assert result["status"] == "ok"
    assert result["trust_level"] == "verified_on_fixture"
