import json
from pathlib import Path

import pytest

from impact_engine.adapters.joern import parse_joern_artifact
from impact_engine.adapters.joern_bridge import convert_graphson, convert_graphson_file
from impact_engine.adapters.registry import AdapterRegistry


ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "joern" / "graphson"


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    return project


@pytest.mark.parametrize(("fixture", "language"), [("x42_c_graphson.json", "C"), ("x42_java_graphson.json", "Java")])
def test_graphson_wrappers_and_supported_nodes_edges_are_converted(tmp_path, fixture, language):
    project = _project(tmp_path)
    output = tmp_path / f"{language}.interchange.json"
    result = convert_graphson_file(FIXTURES / fixture, project_path=project, output_path=output)
    converted = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "converted"
    assert converted["schema_version"] == "CodeSlicerJoernInterchange/v1"
    assert {node["kind"] for node in converted["nodes"]} >= {"METHOD", "CALL", "FILE"}
    assert {edge["source_kind"] for edge in converted["edges"]} >= {"AST", "CALL", "REACHING_DEF"}
    assert len(converted["edges"]) >= 4
    assert converted["taint_paths"]
    assert all(node["id"].startswith("joern_vertex_") for node in converted["nodes"])
    assert all("@type" not in json.dumps(node) and "@value" not in json.dumps(node) for node in converted["nodes"])


@pytest.mark.parametrize("fixture", ["x42_c_graphson.json", "x42_java_graphson.json"])
def test_graphson_convert_import_enable_e2e_has_real_overlay_nodes_edges_and_confirmed_explicit_path(tmp_path, fixture):
    project = _project(tmp_path)
    output = tmp_path / "interchange.json"
    convert_graphson_file(FIXTURES / fixture, project_path=project, output_path=output)
    registry = AdapterRegistry(str(project))
    imported = registry.import_artifact("joern", str(output))
    assert imported["adapter"]["status"] == "imported"
    registry.set_enabled("joern", True)
    overlay = registry.overlay("joern")
    assert overlay is not None
    assert overlay["availability"] == "ready"
    assert overlay["nodes"]
    assert overlay["edges"]
    assert any(edge.get("source_kind") == "REACHING_DEF" for edge in overlay["edges"])
    assert overlay["taint_paths"][0]["resolution"] == "confirmed"
    assert overlay["privacy"]["network_used"] is False


def test_ast_cfg_and_reaching_def_do_not_create_security_taint_path(tmp_path):
    project = _project(tmp_path)
    data = json.loads((FIXTURES / "x42_c_graphson.json").read_text(encoding="utf-8"))
    data["@value"].pop("taint_paths")
    converted = convert_graphson(data, project_path=project, artifact_path=tmp_path / "graphson.json")
    assert converted["taint_paths"] == []
    assert any(item["code"] == "joern_bridge_no_explicit_taint_paths" for item in converted["diagnostics"])
    assert all(edge["confidence"] == "likely" for edge in converted["edges"])


def test_unresolved_graphson_edges_are_aggregated_without_raw_identifiers(tmp_path):
    project = _project(tmp_path)
    data = json.loads((FIXTURES / "x42_c_graphson.json").read_text(encoding="utf-8"))
    edges = data["@value"]["edges"]
    edges.extend([
        {"id": "EDGE_SECRET_1", "label": "UNSUPPORTED_KIND", "outV": {"@value": 1}, "inV": {"@value": 2}},
        {"id": "EDGE_SECRET_2", "label": "UNSUPPORTED_KIND", "outV": {"@value": 2}, "inV": {"@value": 3}},
        {"id": "EDGE_SECRET_3", "label": "CALL", "outV": {"@value": 99999}, "inV": {"@value": 1}},
    ])

    converted = convert_graphson(data, project_path=project, artifact_path=tmp_path / "graphson.json")
    matching = [item for item in converted["diagnostics"] if item["code"] == "joern_bridge_edge_unresolved"]

    assert len(matching) == 1
    assert matching[0]["count"] == 3
    assert matching[0]["examples"] == ["unresolved_endpoint", "unsupported_edge_kind"]
    rendered = json.dumps(converted, ensure_ascii=False)
    assert "EDGE_SECRET_1" not in rendered
    assert "EDGE_SECRET_2" not in rendered
    assert "EDGE_SECRET_3" not in rendered


def test_embedded_cpgql_path_result_is_supported_without_inventing_security_edges(tmp_path):
    project = _project(tmp_path)
    query_result = {
        "@type": "g:List",
        "@value": [{
            "source": {"id": 1, "label": "IDENTIFIER", "properties": {"NAME": [{"value": "input"}], "FILENAME": [{"value": "src/query.c"}], "LINE_NUMBER": [{"value": 3}]}},
            "steps": [],
            "sink": {"id": 2, "label": "CALL", "properties": {"NAME": [{"value": "system"}], "FILENAME": [{"value": "src/query.c"}], "LINE_NUMBER": [{"value": 7}]}},
            "confidence": "confirmed"
        }]
    }
    converted = convert_graphson(query_result, project_path=project, artifact_path=tmp_path / "query.json")
    assert len(converted["nodes"]) == 2
    assert converted["taint_paths"][0]["resolution"] == "unresolved"
    assert converted["edges"] == []


def test_bridge_drops_unknown_nested_properties_and_does_not_store_full_source(tmp_path):
    project = _project(tmp_path)
    data = json.loads((FIXTURES / "x42_c_graphson.json").read_text(encoding="utf-8"))
    data["@value"]["vertices"][1]["properties"]["TOKEN"] = [{"@value": {"id": 999, "value": "GRAPHSON_SECRET_7F"}}]
    data["@value"]["vertices"][1]["properties"]["CODE"] = [{"@value": {"id": 998, "value": "password=GRAPHSON_SECRET_7F"}}]
    converted = convert_graphson(data, project_path=project, artifact_path=tmp_path / "graphson.json")
    rendered = json.dumps(converted, ensure_ascii=False)
    assert "GRAPHSON_SECRET_7F" not in rendered
    assert "TOKEN" not in rendered
    assert "@type" not in rendered and "@value" not in rendered


def test_bridge_rejects_relative_paths_and_unsupported_shape(tmp_path):
    project = _project(tmp_path)
    with pytest.raises(ValueError, match="absolute local path"):
        convert_graphson_file("relative.json", project_path=project, output_path=tmp_path / "out.json")
    with pytest.raises(ValueError, match="unsupported GraphSON"):
        convert_graphson({"vertices": [], "edges": []}, project_path=project, artifact_path=tmp_path / "graphson.json")


def test_bridge_output_remains_parseable_by_existing_parser(tmp_path):
    project = _project(tmp_path)
    output = tmp_path / "interchange.json"
    convert_graphson_file(FIXTURES / "x42_java_graphson.json", project_path=project, output_path=output)
    parsed = parse_joern_artifact(output)
    assert parsed["availability"] == "ready"
    assert parsed["nodes"]
    assert parsed["edges"]
    assert parsed["taint_paths"][0]["confidence"] == "confirmed"
