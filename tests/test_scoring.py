import math

from impact_engine.impact import impact_path, impact_query
from impact_engine.models import Edge, GraphDocument, Node
from impact_engine.scoring import (
    ImpactScoringConfig,
    chain_confidence,
    impact_score,
    token_saving_report,
)


def test_chain_confidence_uses_geometric_mean():
    assert chain_confidence([0.81, 0.81]) == 0.81
    assert math.isclose(chain_confidence([0.90, 0.81]), math.sqrt(0.90 * 0.81))


def test_impact_score_is_transparent_and_distance_aware():
    assert math.isclose(impact_score(1.4, 0.8, 2, 0.85), 1.4 * 0.8 * (0.85 ** 2))


def test_token_saving_requires_measured_values():
    assert token_saving_report(None, None)["status"] == "not_measured"
    report = token_saving_report(128000, 41000)
    assert report["status"] == "measured"
    assert math.isclose(report["saving_percent"], 67.97)


def test_impact_query_exposes_ranking_and_chain_confidence():
    graph = GraphDocument(
        nodes=[
            Node("source", "FUNCTION", "source"),
            Node("target", "ROUTE", "target"),
        ],
        edges=[
            Edge("e1", "CALLS", "source", "target", "INFERRED", 0.81),
        ],
    )
    result = impact_query(
        graph,
        target="source",
        direction="downstream",
        full_context_tokens=100,
        selected_context_tokens=40,
    )
    assert result["impact_ranking"][0]["node_id"] == "target"
    assert result["impact_ranking"][0]["path_confidence"] == 0.81
    assert result["impact_ranking"][0]["confidence_status"] == "Высокая вероятность"
    assert result["context_efficiency"]["saving_percent"] == 60.0
    assert result["scoring"]["formula"].startswith("ImpactScore")
    assert result["scoring"]["compact"]


def test_impact_path_exposes_chain_confidence():
    graph = GraphDocument(
        nodes=[Node("a", "FUNCTION", "a"), Node("b", "FUNCTION", "b")],
        edges=[Edge("e", "CALLS", "a", "b", "EXTRACTED", 0.9)],
    )
    result = impact_path(graph, "a", "b")
    assert result["chain_confidence"] == 0.9
    assert result["chain_status"] == "Подтверждена"


def test_scoring_configuration_is_not_ui_hardcoded():
    config = ImpactScoringConfig.from_dict({"decay": 0.7, "criticality_by_kind": {"ROUTE": 2.0}})
    assert config.decay == 0.7
    assert config.criticality_by_kind["ROUTE"] == 2.0
