import json
import hashlib
from pathlib import Path

import pytest

from impact_engine.adapters.joern import parse_joern_artifact
from impact_engine.adapters.joern_real_validation import (
    build_real_validation_report,
    load_real_manifest,
    normalize_joern_flow_export,
    run_real_corpus_validation,
    _sanitized_interchange,
    validate_real_manifest,
)
from impact_engine.adapters.registry import AdapterRegistry
from impact_engine.adapters import joern_real_validation as validation


ROOT = Path(__file__).parents[1]
REAL_FIXTURES = ROOT / "tests" / "fixtures" / "joern" / "real_corpus"
REAL_REPORTS = ROOT / "tests" / "fixtures" / "joern" / "real_vulnerability_reports"
MANIFEST = ROOT / "benchmarks" / "joern" / "real_corpus_manifest.json"


def test_real_manifest_is_pinned_and_bounded():
    manifest = load_real_manifest(MANIFEST)
    assert manifest["schema_version"] == "CodeSlicerJoernRealCorpusManifest/v1"
    assert {case["language"] for case in manifest["cases"]} == {"C", "Java"}
    assert all(len(case["commit_sha"]) == 40 for case in manifest["cases"])
    assert all(case["url"].startswith("https://") for case in manifest["cases"])
    assert all("source" in case and "sink" in case for case in manifest["cases"])
    assert all(case["expected"]["source_selector"]["file_suffix"] for case in manifest["cases"])
    assert all(case["expected"]["sink_selector"].get("file_suffix") for case in manifest["cases"])
    assert all(case["materialization"]["output_relative"] == case["project_subpath"] for case in manifest["cases"])


def test_real_manifest_queries_write_bounded_json_to_local_output():
    manifest = load_real_manifest(MANIFEST)
    for case in manifest["cases"]:
        query = (MANIFEST.parent / case["commands"]["query_file"]).read_text(encoding="utf-8")
        assert "reachableByFlows" in query
        assert "#> output" in query
        assert "|> output" not in query


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda data: data["cases"][0].update({"url": "https://evil.invalid/?token=secret"}), "manifest url"),
        (lambda data: data["cases"][0].update({"commit_sha": "short"}), "commit_sha"),
        (lambda data: data["cases"][0]["commands"].update({"frontend_args": ["--output", "https://remote"]}), "network URL"),
    ],
)
def test_manifest_rejects_untrusted_inputs(mutation, message):
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    mutation(data)
    with pytest.raises(ValueError, match=message):
        validate_real_manifest(data)


def test_normalize_joern_flow_export_discards_raw_ids_and_properties(tmp_path):
    source = tmp_path / "flow.json"
    target = tmp_path / "normalized.json"
    source.write_text(json.dumps([{"elements": [
         {"id": "GRAPH_SECRET_NODE_9A", "nodeType": "Call", "tracked": "fread(input)", "file": "src/main.c", "lineNumber": 3},
        {"id": "GRAPH_SECRET_SINK_9A", "nodeType": "Call", "file": "src/main.c", "lineNumber": 8, "properties": {"token": "SECRET_SHOULD_DROP"}},
    ]}]), encoding="utf-8")
    normalize_joern_flow_export(source, target)
    rendered = target.read_text(encoding="utf-8")
    assert "GRAPH_SECRET" not in rendered
    assert "SECRET_SHOULD_DROP" not in rendered
    normalized = json.loads(rendered)
    assert normalized["paths"][0]["confidence"] == "confirmed"
    assert normalized["vertices"][0]["properties"]["FILENAME"] == "src/main.c"
    assert normalized["vertices"][0]["properties"]["NAME"] == "fread"


def test_sanitized_interchange_removes_absolute_paths(tmp_path):
    source = tmp_path / "converted.json"
    target = tmp_path / "safe.json"
    payload = json.loads((REAL_FIXTURES / "confirmed_flow.json").read_text(encoding="utf-8"))
    payload["metadata"]["project_path"] = str(tmp_path / "private-project")
    payload["metadata"]["source_artifact"] = str(tmp_path / "raw-graphson.json")
    source.write_text(json.dumps(payload), encoding="utf-8")
    _sanitized_interchange(source, target)
    assert str(tmp_path) not in target.read_text(encoding="utf-8")


@pytest.mark.parametrize(("fixture", "expected"), [("confirmed_flow.json", "confirmed"), ("unresolved_flow.json", "unresolved")])
def test_sanitized_checked_in_outputs_preserve_confirmed_vs_unresolved(tmp_path, fixture, expected):
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / fixture
    source.write_text((REAL_FIXTURES / fixture).read_text(encoding="utf-8"), encoding="utf-8")
    overlay = AdapterRegistry(str(project)).import_artifact("joern", str(source))["overlay"]
    assert overlay["taint_paths"][0]["resolution"] == expected
    assert overlay["privacy"]["network_used"] is False


def test_report_is_bounded_and_has_no_absolute_paths_or_raw_external_ids(tmp_path):
    project = tmp_path / "secret-project"
    project.mkdir()
    source = tmp_path / "confirmed.json"
    source.write_text((REAL_FIXTURES / "confirmed_flow.json").read_text(encoding="utf-8"), encoding="utf-8")
    overlay = AdapterRegistry(str(project)).import_artifact("joern", str(source))["overlay"]
    case = load_real_manifest(MANIFEST)["cases"][0]
    case["expected"]["confirmed_path_ids"] = []
    case["expected"]["source_selector"] = None
    case["expected"]["sink_selector"] = None
    report = build_real_validation_report(case, overlay, command_status={"frontend": {"status": "ok"}, "query": {"status": "ok"}, "convert": {"status": "ok"}}, elapsed_ms=1.0)
    rendered = json.dumps(report, ensure_ascii=False)
    assert report["status"] == "ok", report
    assert report["observed"]["confirmed"] == 1
    assert str(tmp_path) not in rendered
    assert "GRAPH_SECRET" not in rendered
    assert "source" not in report["privacy"]
    assert report["privacy"]["raw_graphson_ids_stored"] is False


def test_no_path_observed_is_failed_not_safe():
    case = load_real_manifest(MANIFEST)["cases"][0]
    report = build_real_validation_report(case, None, command_status={"frontend": {"status": "ok"}, "query": {"status": "ok"}, "convert": {"status": "ok"}}, elapsed_ms=1.0)
    assert report["status"] == "failed"
    assert any(item["code"] == "no_path_observed" for item in report["diagnostics"])


def test_semantic_source_sink_selectors_are_required_for_real_confirmation():
    case = {
        "case_id": "semantic-case",
        "language": "C",
        "expected": {
            "confirmed_paths": 1,
            "required_locations": True,
            "source_selector": {"kinds": ["CALL"], "name_exact": "read_input", "file_suffix": "main.c"},
            "sink_selector": {"kinds": ["CALL"], "name_exact": "system", "file_suffix": "main.c"},
            "min_steps": 1,
        },
    }
    overlay = {
        "freshness": {"status": "fresh", "verified": True},
        "nodes": [
            {"id": "source", "kind": "CALL", "name": "read_input", "file": "src/main.c"},
            {"id": "step", "kind": "CALL", "name": "sanitize", "file": "src/main.c"},
            {"id": "sink", "kind": "CALL", "name": "system", "file": "src/main.c"},
        ],
        "taint_paths": [{"id": "path", "source": "source", "steps": ["step"], "sink": "sink", "resolution": "confirmed", "locations": [{"file": "src/main.c", "range": {"start_line": 2, "end_line": 2}}, {"file": "src/main.c", "range": {"start_line": 4, "end_line": 4}}]}],
        "diagnostics": [],
    }
    report = build_real_validation_report(case, overlay, command_status={}, elapsed_ms=1.0)
    assert report["status"] == "ok", report
    assert report["observed"]["semantic_matches"]["paths"] == 1

    overlay["nodes"][2]["name"] = "execve"
    report = build_real_validation_report(case, overlay, command_status={}, elapsed_ms=1.0)
    assert report["status"] == "failed"
    assert any(item["code"] == "expected_sink_selector_unmatched" for item in report["diagnostics"])


def test_runner_is_explicit_local_and_passes_flow_through_convert(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    joern_dir = tmp_path / "joern"
    joern_dir.mkdir()
    for name in ("joern", "joern-parse", "impact-engine"):
        (joern_dir / name).write_text("local test double", encoding="utf-8")
    query_file = tmp_path / "query.sc"
    query_file.write_text("importCpg(cpgFile)\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "CodeSlicerJoernRealCorpusManifest/v1",
        "cases": [{
            "case_id": "local-case", "language": "C", "url": "https://example.com/corpus", "commit_sha": "0123456789abcdef0123456789abcdef01234567", "license": "MIT", "project_subpath": ".",
            "materialized_source": {"url": "https://example.com/source.tar.gz", "artifact_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"},
            "source": {"description": "input", "query": "source"}, "sink": {"description": "sink", "query": "sink"},
            "commands": {"frontend_args": ["--output", "{cpg_output}", "{project}"], "query_file": "query.sc", "query_args": ["--script", "{query_file}", "--param", "output={query_output}"]},
            "expected": {"confirmed_paths": 1, "required_locations": True}
        }]
    }), encoding="utf-8")
    calls = []

    def fake_run(argv, *, timeout, env):
        calls.append(argv)
        if Path(argv[0]).name == "joern" and "adapters" not in argv:
            output_arg = next(item.strip('"').split("=", 1)[1] for item in argv if item.strip('"').startswith("output="))
            Path(output_arg).write_text(json.dumps([{"elements": [
                {"nodeType": "Call", "file": "src/input.c", "lineNumber": 2},
                {"nodeType": "Call", "file": "src/input.c", "lineNumber": 5},
            ]}]), encoding="utf-8")
        elif "adapters" in argv:
            flow = Path(argv[argv.index("convert") + 1])
            output = Path(argv[argv.index("--output") + 1])
            from impact_engine.adapters.joern_bridge import convert_graphson_file
            convert_graphson_file(flow, project_path=corpus, output_path=output)
        return {"status": "ok", "elapsed_ms": 1.0, "returncode": 0}

    monkeypatch.setattr(validation, "_run_local", fake_run)
    report = run_real_corpus_validation(joern_dir, corpus, manifest, "local-case", impact_engine_path=joern_dir / "impact-engine", output_path=tmp_path / "report.json")
    assert report["status"] == "ok", report
    assert report["observed"]["confirmed"] == 1
    assert any("adapters" in call for call in calls)
    assert all(not any("://" in item for item in call) for call in calls)
    rendered = (tmp_path / "report.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in rendered
    registry = AdapterRegistry(str(corpus))
    assert (corpus / ".codeslicer" / "artifacts" / "joern" / "interchange.json").is_file()
    assert registry.status("joern")["freshness"]["verified"] is True
    assert registry.overlay("joern")["freshness"]["verified"] is True


def test_real_fixture_parser_does_not_invent_edges():
    parsed = parse_joern_artifact(REAL_FIXTURES / "unresolved_flow.json")
    assert parsed["taint_paths"][0]["resolution"] == "unresolved"
    assert parsed["edges"] == []


@pytest.mark.parametrize("filename", [
    "vul4c-cve-2017-7607.json",
    "vul4j-10-cve-2013-2186.json",
])
def test_real_vulnerability_reports_are_sanitized_and_semantically_confirmed(filename):
    report_path = REAL_REPORTS / filename
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rendered = report_path.read_text(encoding="utf-8")
    assert report["schema_version"] == "CodeSlicerJoernRealCorpusReport/v1"
    assert report["status"] == "ok"
    assert report["freshness"] == {"status": "fresh", "verified": True}
    assert report["observed"]["confirmed"] >= 1
    assert report["observed"]["semantic_matches"]["paths"] >= 1
    assert report["privacy"]["network_used"] is False
    assert report["privacy"]["raw_source_stored"] is False
    assert report["privacy"]["raw_graphson_ids_stored"] is False
    assert report["privacy"]["absolute_user_paths_stored"] is False
    assert not any(marker in rendered for marker in ("C:\\Users\\", "D:\\", "GRAPH_SECRET", "SECRET_"))


@pytest.mark.parametrize("filename", [
    "vul4c-cve-2017-7607.json",
    "vul4j-10-cve-2013-2186.json",
])
def test_real_reports_have_runner_provenance_and_match_manifest(filename):
    manifest = load_real_manifest(MANIFEST)
    report = json.loads((REAL_REPORTS / filename).read_text(encoding="utf-8"))
    case_id = report["case"]["case_id"]
    case = next(item for item in manifest["cases"] if item["case_id"] == case_id)
    assert report["status"] == "ok"
    assert isinstance(report["artifact_fingerprint"], str) and len(report["artifact_fingerprint"]) == 64
    assert isinstance(report["elapsed_ms"], (int, float)) and report["elapsed_ms"] > 0
    assert {"frontend", "query", "convert"} <= set(report["commands"])
    assert all(report["commands"][name]["status"] == "ok" for name in ("frontend", "query", "convert"))
    assert report["expected"]["source_selector"] == case["expected"]["source_selector"]
    assert report["expected"]["sink_selector"] == case["expected"]["sink_selector"]
    assert report["expected"]["min_steps"] == case["expected"]["min_steps"]
    assert report["case"]["commit_sha"] == case["commit_sha"]
    assert report["freshness"]["verified"] is True
    if case["materialization"]["kind"] == "archive":
        assert report["materialization"]["artifact_sha256"] == case["materialized_source"]["artifact_sha256"]
    else:
        assert report["materialization"]["source_commit_sha"] == case["materialized_source"]["commit_sha"]
    assert report["materialization"]["status"] == "verified"
    assert report["materialization"]["verified"] is True


def test_materialization_verification_is_local_and_checksum_bound(tmp_path):
    archive = tmp_path / "source.tar.bz2"
    archive.write_bytes(b"local archive fixture")
    project = tmp_path / "materialized" / "project"
    project.mkdir(parents=True)
    case = {
        "project_subpath": "materialized/project",
        "materialization": {
            "kind": "archive",
            "input_relative": "source.tar.bz2",
            "output_relative": "materialized/project",
            "artifact_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        },
    }
    result = validation._verify_materialization(case, tmp_path, project)
    assert result["status"] == "verified"
    assert result["verified"] is True

    case["materialization"]["artifact_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="SHA-256"):
        validation._verify_materialization(case, tmp_path, project)


def test_runner_rejects_missing_declared_materialization(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    case = {
        "project_subpath": "materialized/project",
        "materialization": {
            "kind": "archive",
            "input_relative": "missing.tar.bz2",
            "output_relative": "materialized/project",
            "artifact_sha256": "0" * 64,
        },
    }
    with pytest.raises(FileNotFoundError, match="materialization_required"):
        validation._verify_materialization(case, corpus, corpus / case["project_subpath"])
