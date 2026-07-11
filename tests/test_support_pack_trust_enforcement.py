from __future__ import annotations

from impact_engine.models import GraphDocument, Node
from impact_engine.support_packs.resolution import apply_support_pack_rules
from impact_engine.support_packs.rule_engine import apply_support_pack_rule_engine
from impact_engine.support_packs.schema import (
    SUPPORT_PACK_CONFIDENCE_CAPS,
    cap_support_pack_confidence,
    normalize_support_pack_trust_level,
)


def _graph() -> GraphDocument:
    graph = GraphDocument()
    graph.add_node(
        Node(
            id="call-1",
            kind="CALL_EXPR",
            name="framework_call()",
            properties={"call_name": "framework_call", "scope": "app.service.run"},
        )
    )
    return graph


def _pack(status: str, confidence: float = 0.99) -> dict:
    return {
        "library": f"lib_{status}",
        "version_range": ">=1.0",
        "language": "python",
        "status": status,
        "edge_rules": [
            {
                "id": "framework-call",
                "match": {"node_kind": "CALL_EXPR", "call_name": "framework_call"},
                "emit": {
                    "to": "external.framework.target",
                    "kind": "CALLS",
                    "source": "SUPPORT_PACK",
                    "confidence": confidence,
                    "description": "Resolved by trust policy test pack",
                },
            }
        ],
    }


def test_draft_and_staged_support_packs_do_not_emit_edges_in_normal_analyze():
    for status in ("draft", "staged"):
        graph = apply_support_pack_rules(_graph(), [_pack(status)])

        assert graph.edges == []
        assert graph.metadata["support_pack_skipped"] == [
            {
                "library": f"lib_{status}",
                "version_range": ">=1.0",
                "trust_level": status,
                "reason": "inactive trust level is not used during normal analyze",
            }
        ]


def test_active_support_pack_trust_levels_cap_emitted_confidence():
    expected_caps = {
        "experimental": 0.65,
        "verified_on_fixture": 0.80,
        "verified_on_real_project": 0.90,
        "trusted": 0.95,
    }

    for status, expected in expected_caps.items():
        graph = apply_support_pack_rules(_graph(), [_pack(status)])

        edge = graph.edges[0]
        assert edge.confidence == expected
        assert edge.properties["support_pack_trust_level"] == status
        assert edge.properties["support_pack_confidence_cap"] == expected
        assert edge.properties["support_pack_active"] is True


def test_trust_level_overrides_status_for_confidence_policy():
    pack = _pack("experimental", confidence=0.99)
    pack["trust_level"] = "verified_on_real_project"

    graph = apply_support_pack_rules(_graph(), [pack])

    edge = graph.edges[0]
    assert edge.confidence == 0.90
    assert edge.properties["support_pack_trust_level"] == "verified_on_real_project"


def test_legacy_statuses_normalize_to_current_trust_levels():
    assert normalize_support_pack_trust_level("verified") == "verified_on_real_project"
    assert normalize_support_pack_trust_level("official") == "trusted"
    assert cap_support_pack_confidence(0.99, "verified") == SUPPORT_PACK_CONFIDENCE_CAPS["verified_on_real_project"]
    assert cap_support_pack_confidence(0.99, "official") == SUPPORT_PACK_CONFIDENCE_CAPS["trusted"]


def test_rule_engine_metadata_reports_active_and_inactive_packs():
    graph = apply_support_pack_rule_engine(_graph(), [_pack("draft"), _pack("trusted")])

    metadata = graph.metadata["support_pack_rule_engine"]
    assert metadata["packs_loaded"] == 2
    assert metadata["active_packs"] == 1
    assert metadata["inactive_packs"] == 1
    assert metadata["confidence_caps"]["experimental"] == 0.65
    assert metadata["trust_levels"][0]["active"] is False
    assert metadata["trust_levels"][1]["active"] is True
