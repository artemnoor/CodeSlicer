import json
import hashlib
from pathlib import Path

import pytest

from impact_engine.adapters.joern_benchmark import (
    aggregate_joern_benchmark,
    discover_local_joern_corpus,
    run_joern_benchmark,
    validate_golden_case,
)
from impact_engine.models import GraphDocument, Node


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "joern"


def _artifact(tmp_path: Path, name: str) -> tuple[Path, Path]:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    source = tmp_path / name
    source.write_text((FIXTURES / name).read_text(encoding="utf-8").replace("__PROJECT__", project.as_posix()), encoding="utf-8")
    return project, source


def _case(project: Path, source: Path, *, language: str = "C++", confirmed: list[str] | None = None) -> dict:
    return {
        "schema_version": "CodeSlicerJoernGoldenCase/v1",
        "case_id": f"{language.lower().replace('+', 'p')}-baseline",
        "language": language,
        "project_path": str(project),
        "artifact_path": str(source),
        "source_artifact_fingerprint": hashlib.sha256(source.read_bytes()).hexdigest(),
        "expected": {
            "confirmed_path_ids": confirmed or [],
            "likely_path_ids": [],
            "unresolved_path_ids": [],
            "dangerous_call_node_ids": [],
        },
        "prohibited_false_positive_paths": [],
        "required_evidence_locations": True,
    }


def test_benchmark_is_deterministic_bounded_and_review_invariant(tmp_path):
    project, source = _artifact(tmp_path, "c_taint.json")
    graph = GraphDocument(metadata={"project_path": str(project)})
    graph.add_node(Node(id="root", kind="PROJECT", name="project"))
    graph_path = project / ".impact_engine" / "graph.json"
    graph_path.parent.mkdir()
    graph_path.write_text(json.dumps(graph.to_dict()), encoding="utf-8")
    case = _case(project, source, confirmed=["c-path-1"])

    first = run_joern_benchmark(project, source, case=case, max_nodes=1, max_edges=1, max_paths=1)
    second = run_joern_benchmark(project, source, case=case, max_nodes=1, max_edges=1, max_paths=1)
    first_report = json.loads(json.dumps(first["report"]))
    second_report = json.loads(json.dumps(second["report"]))
    first_latency = first_report["metrics"].pop("bounded_investigate_latency_ms")
    second_latency = second_report["metrics"].pop("bounded_investigate_latency_ms")
    assert first_report == second_report
    assert first_latency >= 0 and second_latency >= 0
    report = first["report"]
    assert report["golden_case"] == {"fingerprint_provided": True, "fingerprint_matches": True}
    assert report["metrics"]["confirmed_taint_path_precision"] == 1.0
    assert report["metrics"]["confirmed_taint_path_recall"] == 1.0
    assert report["metrics"]["false_confirmed_count"] == 0
    assert report["metrics"]["privacy_leak_count"] == 0
    assert report["bounded_context"]["bounded"] is True
    assert report["review_invariance"] == {"status": "checked", "invariant": True}
    assert Path(first["report_path"]).is_file()
    stored = json.loads(Path(first["report_path"]).read_text(encoding="utf-8"))
    assert "taint_paths" not in stored and "nodes" not in stored and "c-path-1" not in json.dumps(stored)


@pytest.mark.parametrize(("fixture", "language", "path_id"), [("c_taint.json", "C++", "c-path-1"), ("java_taint.json", "Java", "java-path-1")])
def test_valid_language_baselines_are_confirmed(tmp_path, fixture, language, path_id):
    project, source = _artifact(tmp_path, fixture)
    result = run_joern_benchmark(project, source, case=_case(project, source, language=language, confirmed=[path_id]))
    assert result["report"]["resolution"]["confirmed"] == 1
    assert result["report"]["metrics"]["false_confirmed_count"] == 0


def test_negative_stale_export_is_diagnostic_and_not_confirmed(tmp_path):
    project, source = _artifact(tmp_path, "c_taint.json")
    result = run_joern_benchmark(project, source, case=_case(project, source, confirmed=["c-path-1"]))
    source.write_text(source.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8")
    measured = aggregate_joern_benchmark(project, source, case=_case(project, source, confirmed=["c-path-1"]))
    assert measured["freshness"] == {"status": "stale", "verified": False}
    assert measured["resolution"]["confirmed"] == 0
    assert "joern_taint_freshness_unverified" in measured["diagnostics"]["codes"]
    assert result["report"]["resolution"]["confirmed"] == 1


def test_incomplete_and_dangerous_call_cases_are_not_false_confirmed(tmp_path):
    project, source = _artifact(tmp_path, "incomplete.json")
    incomplete = run_joern_benchmark(project, source, case=_case(project, source, confirmed=[]))
    assert incomplete["report"]["resolution"]["confirmed"] == 0
    assert incomplete["report"]["resolution"]["unresolved"] == 1
    assert "joern_taint_path_incomplete" in incomplete["report"]["diagnostics"]["codes"]

    project, source = _artifact(tmp_path, "dangerous_call.json")
    dangerous = run_joern_benchmark(project, source, case=_case(project, source, confirmed=[]))
    assert dangerous["report"]["resolution"]["confirmed"] == 0
    assert dangerous["report"]["resolution"]["dangerous_call_findings"] == 1


def test_discovery_separates_synthetic_fixtures_and_reports_blocked_real_corpus(tmp_path):
    result = discover_local_joern_corpus([FIXTURES], include_synthetic=True)
    assert result["status"] == "blocked"
    assert result["synthetic_candidates"]
    assert result["real_candidates"] == []


def test_discovery_prunes_vendor_build_and_corpus_directories_by_default(tmp_path):
    payload = {"schema_version": "CodeSlicerJoernInterchange/v1", "metadata": {"project_path": str(tmp_path)}}
    for directory in ("node_modules", "build", "tests/fixtures", "corpus"):
        target = tmp_path / directory / "export.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload), encoding="utf-8")
    result = discover_local_joern_corpus([tmp_path])
    assert result["status"] == "blocked"
    assert result["candidate_count"] == 0
    assert result["scanned_files"] == 0


def test_discovery_reports_max_files_bound(tmp_path):
    for name in ("first.json", "second.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    result = discover_local_joern_corpus([tmp_path], max_files=1, timeout_seconds=10)
    assert result["stopped_reason"] == "max_files"
    assert result["scanned_files"] == 1
    assert any("--max-files" in item for item in result["diagnostics"])


def test_golden_case_rejects_secret_like_ids_and_relative_paths(tmp_path):
    project, source = _artifact(tmp_path, "c_taint.json")
    case = _case(project, source, confirmed=["JOERN_SECRET_ID"])
    with pytest.raises(ValueError, match="unsafe identifier"):
        validate_golden_case(case)
    case["project_path"] = "relative-project"
    with pytest.raises(ValueError, match="absolute local path"):
        validate_golden_case(case)


def test_benchmark_has_no_network_or_subprocess_execution(tmp_path):
    project, source = _artifact(tmp_path, "java_taint.json")
    result = run_joern_benchmark(project, source, case=_case(project, source, language="Java", confirmed=["java-path-1"]))
    assert result["report"]["privacy"] == {"mode": "local-only", "network_used": False, "joern_invoked": False, "raw_overlay_stored_in_result": False}
