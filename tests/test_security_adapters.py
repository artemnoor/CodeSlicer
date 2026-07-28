from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from impact_engine.adapters.registry import AdapterRegistry
from impact_engine.adapters.security import MAX_SECURITY_REPORT_BYTES, build_security_overlay, map_security_overlay, parse_security_report
from impact_engine.local_api import LocalApiState, create_server
from impact_engine.models import GraphDocument, Node
from impact_engine.review import build_review_report


FIXTURES = Path(__file__).parent / "fixtures" / "security"


def test_security_manifests_discover_without_changing_historical_adapter_order(tmp_path):
    adapters = AdapterRegistry(tmp_path).list()
    assert [item["id"] for item in adapters][:3] == ["graphify", "asyncapi", "lsp"]
    assert {item["id"] for item in adapters} >= {"cyclonedx", "spdx", "sarif", "graphify", "scip", "otel"}
    assert all(item["enabled"] is False for item in adapters if item["id"] in {"cyclonedx", "spdx", "sarif"})


@pytest.mark.parametrize("adapter_id, report, expected_format", [
    ("cyclonedx", FIXTURES / "npm" / "cyclonedx.json", "cyclonedx"),
    ("spdx", FIXTURES / "python" / "spdx.json", "spdx"),
    ("cyclonedx", FIXTURES / "dotnet" / "cyclonedx.json", "cyclonedx"),
    ("sarif", FIXTURES / "sarif" / "exact.sarif", "sarif"),
])
def test_supported_security_reports_parse(adapter_id, report, expected_format):
    parsed = parse_security_report(report, adapter_id)
    assert parsed["format"] == expected_format
    assert parsed["summary"]["components"] or parsed["summary"]["findings"]


def test_cyclonedx_exact_package_mapping_and_security_redaction(tmp_path):
    registry = AdapterRegistry(tmp_path)
    imported = registry.import_artifact("cyclonedx", (FIXTURES / "npm" / "cyclonedx.json").resolve())
    overlay = imported["overlay"]
    assert overlay["privacy"]["network_used"] is False
    assert overlay["summary"]["findings"] == 1
    assert overlay["summary"]["severity"] == {"high": 1}
    assert "SECRET FULL DESCRIPTION" not in json.dumps(overlay)
    stored = tmp_path / ".codeslicer" / "artifacts" / "cyclonedx" / "report.json"
    assert stored.is_file()
    stored_text = stored.read_text(encoding="utf-8")
    assert "SECRET FULL DESCRIPTION" not in stored_text
    assert '"source_report_path"' in stored_text
    graph = GraphDocument(nodes=[Node("dep", "EXTERNAL_LIBRARY", "axios", {"package_name": "axios", "version": "1.6.0", "ecosystem": "npm", "lockfile": "package-lock.json"})])
    mapped = map_security_overlay(overlay, graph)
    package = next(item for item in mapped["nodes"] if item["kind"] == "PACKAGE" and item["name"] == "axios")
    assert package["mapping"] == {"status": "confirmed", "strategy": "exact ecosystem + name + version + manifest/lockfile", "canonical_node_id": "dep"}


def test_spdx_python_and_dotnet_components_are_local_evidence():
    python_overlay = build_security_overlay(parse_security_report(FIXTURES / "python" / "spdx.json", "spdx"), "python-spdx.json", adapter_id="spdx")
    dotnet_overlay = build_security_overlay(parse_security_report(FIXTURES / "dotnet" / "cyclonedx.json", "cyclonedx"), "dotnet.json", adapter_id="cyclonedx")
    assert any(node["properties"].get("ecosystem") == "pypi" for node in python_overlay["nodes"] if node["kind"] == "PACKAGE")
    assert any(node["properties"].get("ecosystem") == "nuget" for node in dotnet_overlay["nodes"] if node["kind"] == "PACKAGE")
    assert all(edge["kind"] in {"COMPONENT_PACKAGE", "PACKAGE_VERSION", "HAS_LICENSE", "DECLARED_IN", "LOCKED_BY", "DEPENDS_ON", "FINDING_AFFECTS_COMPONENT", "FINDING_POINTS_TO_CODE"} for edge in dotnet_overlay["edges"])


def test_sarif_exact_range_confirmed_wrong_range_unresolved_and_message_redacted():
    parsed = parse_security_report(FIXTURES / "sarif" / "exact.sarif", "sarif")
    overlay = build_security_overlay(parsed, "exact.sarif", adapter_id="sarif")
    assert "TOKEN=SHOULD_NOT_APPEAR" not in json.dumps(overlay)
    assert next(location for finding in parsed["findings"] for location in finding["locations"])["range"] == {"start_line": 10, "start_column": 5, "end_line": 10, "end_column": 18}
    graph = GraphDocument(nodes=[Node("code", "FUNCTION", "orders", {"file": "src/orders.py", "range": {"start_line": 10, "start_column": 5, "end_line": 10, "end_column": 18}, "rule_id": "SEC001"})])
    mapped = map_security_overlay(overlay, graph)
    code = next(item for item in mapped["nodes"] if item["kind"] == "AFFECTED_FILE_RANGE")
    assert code["mapping"]["status"] == "confirmed"
    code["properties"]["range"]["start_line"] = 11
    wrong = map_security_overlay(mapped, graph)
    wrong_code = next(item for item in wrong["nodes"] if item["kind"] == "AFFECTED_FILE_RANGE")
    assert wrong_code["mapping"]["status"] in {"unresolved", "likely"}


def test_sarif_extension_is_accepted_by_the_generic_optional_adapter_import(tmp_path):
    registry = AdapterRegistry(tmp_path)
    imported = registry.import_artifact("sarif", (FIXTURES / "sarif" / "exact.sarif").resolve())
    assert imported["status"] == "imported"
    assert registry.set_enabled("sarif", True)["status"] == "ready"


def test_name_only_and_ambiguous_package_mapping_are_not_confirmed():
    overlay = build_security_overlay(parse_security_report(FIXTURES / "npm" / "cyclonedx.json", "cyclonedx"), "report.json", adapter_id="cyclonedx")
    name_only = GraphDocument(nodes=[Node("dep", "EXTERNAL_LIBRARY", "axios", {"package_name": "axios", "ecosystem": "npm"})])
    mapped = map_security_overlay(overlay, name_only)
    package = next(item for item in mapped["nodes"] if item["kind"] == "PACKAGE" and item["name"] == "axios")
    assert package["mapping"]["status"] == "likely"
    ambiguous = GraphDocument(nodes=[
        Node("one", "EXTERNAL_LIBRARY", "axios", {"package_name": "axios", "version": "1.6.0", "ecosystem": "npm", "lockfile": "package-lock.json"}),
        Node("two", "EXTERNAL_LIBRARY", "axios", {"package_name": "axios", "version": "1.6.0", "ecosystem": "npm", "lockfile": "package-lock.json"}),
    ])
    ambiguous_result = map_security_overlay(overlay, ambiguous)
    ambiguous_package = next(item for item in ambiguous_result["nodes"] if item["kind"] == "PACKAGE" and item["name"] == "axios")
    assert ambiguous_package["mapping"]["status"] == "unresolved"


def test_invalid_oversized_and_nonlocal_reports_are_safe(tmp_path):
    registry = AdapterRegistry(tmp_path)
    with pytest.raises(ValueError, match="absolute local"):
        registry.import_artifact("sarif", "report.json")
    with pytest.raises(ValueError, match="absolute local"):
        registry.import_artifact("sarif", "https://example.test/report.json")
    malformed = tmp_path / "bad.json"
    malformed.write_text("{bad", encoding="utf-8")
    result = registry.import_artifact("sarif", malformed.resolve())
    assert any(item["code"] == "malformed_json" for item in result["overlay"]["diagnostics"])
    unsupported = tmp_path / "unsupported.json"
    unsupported.write_text(json.dumps({"version": "1.0"}), encoding="utf-8")
    result = registry.import_artifact("sarif", unsupported.resolve())
    assert any(item["code"] == "unsupported_format" for item in result["overlay"]["diagnostics"])
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"{" + b"x" * MAX_SECURITY_REPORT_BYTES)
    result = registry.import_artifact("sarif", oversized.resolve())
    assert any(item["code"] == "oversized_report" for item in result["overlay"]["diagnostics"])


def test_stale_security_report_and_review_are_unchanged(tmp_path):
    source = tmp_path / "report.json"
    source.write_text((FIXTURES / "npm" / "cyclonedx.json").read_text(encoding="utf-8"), encoding="utf-8")
    registry = AdapterRegistry(tmp_path)
    registry.import_artifact("cyclonedx", source.resolve())
    registry.set_enabled("cyclonedx", True)
    before = build_review_report(str(tmp_path), graph=GraphDocument(metadata={"project_path": str(tmp_path)}), diff_text="", refresh="never")
    source.write_text(source.read_text(encoding="utf-8").replace("1.6.0", "1.6.1"), encoding="utf-8")
    assert registry.status("cyclonedx")["status"] == "stale"
    after = build_review_report(str(tmp_path), graph=GraphDocument(metadata={"project_path": str(tmp_path)}), diff_text="", refresh="never")
    assert (before["risk"], before["top_impacts"], before["test_recommendations"]) == (after["risk"], after["top_impacts"], after["test_recommendations"])


def test_security_api_lifecycle_and_frontend_contract(tmp_path):
    state = LocalApiState(str(tmp_path), "support_packs")
    server = create_server("127.0.0.1", 0, str(tmp_path), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()

    def call(path, payload=None):
        request = Request(f"http://127.0.0.1:{server.server_port}{path}", method="POST" if payload is not None else "GET", data=json.dumps(payload).encode() if payload is not None else None, headers={"Content-Type": "application/json"} if payload is not None else {})
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read())

    try:
        initial = call("/api/adapters")
        assert any(item["id"] == "cyclonedx" and item["enabled"] is False for item in initial["adapters"])
        imported = call("/api/adapters/cyclonedx/import", {"project_path": str(tmp_path), "artifact_path": str((FIXTURES / "npm" / "cyclonedx.json").resolve())})
        assert imported["privacy"]["network_used"] is False
        enabled = call("/api/adapters/cyclonedx/enable", {"project_path": str(tmp_path)})
        assert enabled["adapter"]["status"] == "ready"
        architecture = call("/api/architecture", {"project_path": str(tmp_path)})
        assert architecture["security"]["cyclonedx"]["findings"] == 1
        assert call("/api/adapters/cyclonedx/disable", {"project_path": str(tmp_path)})["status"] == "ok"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    app = Path(__file__).parents[1] / "frontend" / "app.js"
    client = Path(__file__).parents[1] / "frontend" / "api-client.js"
    html = Path(__file__).parents[1] / "frontend" / "index.html"
    assert "Security / SBOM" in html.read_text(encoding="utf-8")
    assert "CycloneDX" in app.read_text(encoding="utf-8")
    assert "cyclonedxImport" in client.read_text(encoding="utf-8")


def test_security_cli_import_enable_disable_status(tmp_path):
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    report = str((FIXTURES / "npm" / "cyclonedx.json").resolve())
    project = str(tmp_path.resolve())

    def run(*args):
        completed = subprocess.run([sys.executable, "-m", "impact_engine.cli", *args, "--json"], cwd=Path(__file__).parents[1], env=environment, capture_output=True, text=True, timeout=30)
        assert completed.returncode == 0, completed.stderr or completed.stdout
        return json.loads(completed.stdout)

    assert run("adapters", "cyclonedx", "import", project, report)["import_status"] == "imported"
    assert run("adapters", "cyclonedx", "enable", project)["adapter"]["status"] == "ready"
    assert run("adapters", "cyclonedx", "status", project)["adapter"]["enabled"] is True
    assert run("adapters", "cyclonedx", "disable", project)["adapter"]["enabled"] is False
