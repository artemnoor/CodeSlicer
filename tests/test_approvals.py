from __future__ import annotations

import pytest

from impact_engine.approvals import ApprovalStore
from impact_engine.mcp.server import connect_managed_tool, request_action_approval


def test_approval_is_one_time_and_bound_to_its_payload(tmp_path):
    store = ApprovalStore(tmp_path)
    pending = store.request("managed_tool.run", {"tool_id": "graphify", "argv": ["--help"]})
    approved = store.approve(pending["approval_id"])
    store.consume(pending["approval_id"], approved["approval_token"], "managed_tool.run", {"tool_id": "graphify", "argv": ["--help"]})

    try:
        store.consume(pending["approval_id"], approved["approval_token"], "managed_tool.run", {"tool_id": "graphify", "argv": ["--help"]})
    except ValueError as exc:
        assert "approval" in str(exc)
    else:
        raise AssertionError("approval token must not be reusable")


def test_mcp_connect_rejects_a_plain_confirmation_boolean(tmp_path):
    pending = request_action_approval(
        str(tmp_path), "managed_tool.connect", {"tool_id": "graphify", "ref": ""},
    )
    assert pending["status"] == "pending_approval"
    with pytest.raises(TypeError):
        connect_managed_tool(str(tmp_path), "graphify", confirmed=True)  # type: ignore[call-arg]
