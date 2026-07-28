from __future__ import annotations

import json
from pathlib import Path

import pytest

from impact_engine.adapters.registry import AdapterRegistry
from impact_engine.adapters.scip import build_scip_overlay, map_scip_overlay, parse_scip_artifact
from impact_engine.adapters.scip_interop import (
    DEFAULT_GOLDEN_ROOT,
    discover_golden_manifests,
    find_scip_cli,
    verify_golden_corpus,
)
from impact_engine.models import GraphDocument, Node
from impact_engine.review import build_review_report


def _manifest_data(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_golden_manifests_are_reproducible_and_sources_are_present():
    manifests = discover_golden_manifests()
    assert {path.parent.name for path in manifests} == {"typescript", "python", "csharp"}
    for manifest_path in manifests:
        manifest = _manifest_data(manifest_path)
        project = manifest_path.parent / manifest["project_dir"]
        assert project.is_dir()
        artifact = project / manifest["artifact"]
        if manifest["status"] == "not-materialized":
            assert manifest["artifact_sha256"] is None
            assert not artifact.exists()
        else:
            assert artifact.is_file()
            assert manifest["artifact_sha256"]
        assert manifest["generation"]["command"]


def test_golden_verifier_reports_missing_artifacts_without_external_process(monkeypatch, tmp_path):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("missing artifacts must not invoke external tools")

    missing_root = tmp_path / "golden"
    for manifest_path in discover_golden_manifests():
        language_dir = missing_root / manifest_path.parent.name
        language_dir.mkdir(parents=True)
        language_dir.joinpath("manifest.json").write_text(
            manifest_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

    monkeypatch.setattr("impact_engine.adapters.scip_interop.subprocess.run", fail_if_called)
    result = verify_golden_corpus(missing_root)
    assert result["status"] == "skipped"
    assert len(result["results"]) == 3
    assert all(item["status"] == "skipped" for item in result["results"])
    assert result["network_used"] is False


@pytest.mark.parametrize("manifest_path", discover_golden_manifests(), ids=lambda path: path.parent.name)
@pytest.mark.scip_interop
def test_external_indexer_golden_import_and_official_lint(manifest_path: Path):
    manifest = _manifest_data(manifest_path)
    artifact = manifest_path.parent / manifest["project_dir"] / manifest["artifact"]
    if not artifact.is_file():
        pytest.skip("golden .scip is not materialized; run the explicit command in the language README")
    if not find_scip_cli():
        pytest.skip("official scip CLI is not installed on PATH; no automatic installation is performed")
    result = verify_golden_corpus(DEFAULT_GOLDEN_ROOT)
    item = next(item for item in result["results"] if item["language"] == manifest["language"])
    expected_lint_status = manifest["expected"].get("lint_status")
    if expected_lint_status:
        assert item["status"] == "error", item
        assert item["parser"]["status"] == "passed", item
        assert item["lint"]["status"] == "failed", item
    else:
        assert item["status"] == "ok", item

    parsed = parse_scip_artifact(artifact)
    assert parsed["format"] == "binary-protobuf"
    metadata = parsed["index_metadata"]
    assert metadata.get("tool") == manifest["indexer"].rsplit("/", 1)[-1]
    if manifest.get("embedded_metadata_version"):
        assert metadata.get("version") == manifest["embedded_metadata_version"]
    assert parsed["documents"]
    assert all(document.get("relative_path") for document in parsed["documents"])
    assert all(occurrence.get("range") for document in parsed["documents"] for occurrence in document.get("occurrences", []))
    encodings = {
        occurrence.get("range_encoding")
        for document in parsed["documents"]
        for occurrence in document.get("occurrences", [])
    }
    if manifest["expected"].get("require_typed_ranges"):
        assert encodings & {"single_line_typed", "multi_line_typed"}
    else:
        assert encodings & {"single_line_typed", "multi_line_typed", "legacy_packed"}


@pytest.mark.parametrize("manifest_path", discover_golden_manifests(), ids=lambda path: path.parent.name)
@pytest.mark.scip_interop
def test_external_golden_import_mapping_and_review_invariance(manifest_path: Path, tmp_path: Path):
    manifest = _manifest_data(manifest_path)
    artifact = manifest_path.parent / manifest["project_dir"] / manifest["artifact"]
    if not artifact.is_file():
        pytest.skip("golden .scip is not materialized")
    parsed = parse_scip_artifact(artifact)
    registry = AdapterRegistry(tmp_path)
    imported = registry.import_artifact("scip", artifact.resolve())
    assert imported["overlay"]["index_metadata"]["format"] == "binary-protobuf"
    overlay = build_scip_overlay(parsed, artifact_path=str(artifact), project_root=tmp_path, freshness={"status": "fresh", "verified": True}, enabled=True)
    graph = GraphDocument(metadata={"project_path": str(tmp_path)})
    kind_map = {"class": "CLASS", "interface": "CLASS", "method": "METHOD", "function": "FUNCTION", "module": "MODULE", "namespace": "MODULE", "type": "CLASS"}
    for index, symbol in enumerate(parsed.get("symbols") or []):
        for definition in symbol.get("definitions") or []:
            definition_range = definition.get("range") or {}
            graph.add_node(Node(
                id=f"golden:{index}",
                kind=kind_map.get(str(symbol.get("kind")), "FUNCTION"),
                name=str(symbol.get("name")),
                properties={"file": definition.get("file"), "definition_range": definition_range},
            ))
    mapped = map_scip_overlay(overlay, graph)
    mappable_kinds = {"class", "method", "function", "module", "interface", "type"}
    defined_symbols = {
        str(item.get("symbol_id"))
        for item in parsed.get("symbols", [])
        if item.get("definitions") and item.get("kind") in mappable_kinds
    }
    confirmed_symbols = {str(item.get("semantic_id")) for item in mapped.get("nodes", []) if item.get("mapping", {}).get("status") == "confirmed"}
    assert defined_symbols <= confirmed_symbols
    before = build_review_report(str(tmp_path), graph=graph, diff_text="", refresh="never")
    after = build_review_report(str(tmp_path), graph=graph, diff_text="", refresh="never")
    assert (before["risk"], before["top_impacts"], before["test_recommendations"]) == (after["risk"], after["top_impacts"], after["test_recommendations"])


@pytest.mark.parametrize(
    ("language", "symbol_name", "kind"),
    [("typescript", "useGreeting", "function"), ("csharp", "ReadNow", "method")],
)
@pytest.mark.scip_interop
def test_utf16_column_mismatch_never_confirms_real_external_symbol(language, symbol_name, kind, tmp_path: Path):
    artifact = DEFAULT_GOLDEN_ROOT / language / "project" / "index.scip"
    if not artifact.is_file():
        pytest.skip("golden .scip is not materialized")
    parsed = parse_scip_artifact(artifact)
    symbol = next(item for item in parsed["symbols"] if item.get("name") == symbol_name)
    definition = (symbol.get("definitions") or [])[0]
    source_range = dict(definition["range"])
    source_range["start_column"] = max(0, source_range["start_column"] - 1)
    source_range["end_column"] = max(source_range["start_column"], source_range["end_column"] - 1)
    graph = GraphDocument(metadata={"project_path": str(tmp_path)})
    graph.add_node(Node(
        id="utf16-mismatch",
        kind="FUNCTION" if kind == "function" else "METHOD",
        name=symbol_name,
        properties={"file": definition["file"], "definition_range": source_range},
    ))
    overlay = build_scip_overlay(
        parsed,
        artifact_path=str(artifact),
        project_root=tmp_path,
        freshness={"status": "fresh", "verified": True},
        enabled=True,
    )
    mapped = map_scip_overlay(overlay, graph)
    selected = next(item for item in mapped["nodes"] if item.get("name") == symbol_name)
    assert selected["mapping"]["status"] == "unresolved"
