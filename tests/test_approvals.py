from __future__ import annotations

import pytest
import json
import threading

from impact_engine.approvals import ApprovalStore
from impact_engine.cli import main
from impact_engine.mcp.server import (
    connect_managed_tool,
    investigate,
    managed_tool_help,
    onboard,
    request_action_approval,
    runtime_trace,
)


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


def test_sensitive_mcp_calls_create_their_own_exact_pending_approval(tmp_path):
    """Agents call the target tool once; they never reconstruct approval payloads."""
    cases = [
        (connect_managed_tool(str(tmp_path), "graphify"), "connect_managed_tool", "managed_tool.connect"),
        (managed_tool_help(str(tmp_path), "graphify"), "managed_tool_help", "managed_tool.help"),
        (runtime_trace(str(tmp_path)), "runtime_trace", "runtime_trace"),
        (investigate(str(tmp_path), "missing", runtime_validate=True), "investigate", "investigate.runtime_validate"),
        (onboard(str(tmp_path), graphify_mode="auto"), "onboard", "project.onboard"),
    ]
    for result, tool, action in cases:
        assert result["tool"] == tool
        assert result["status"] == "pending_approval"
        assert result["approval"]["action"] == action
        assert result["approval"]["approval_id"] in result["next_step"]


def test_partial_mcp_approval_credentials_are_rejected_not_replaced(tmp_path):
    result = runtime_trace(str(tmp_path), approval_id="only-an-id")
    assert result["status"] == "error"
    assert "supplied together" in result["error"]


def test_host_listing_redacts_verifier_and_rejects_path_like_ids(tmp_path):
    store = ApprovalStore(tmp_path)
    pending = store.request("runtime_trace", {"argv": ["pytest"]})
    store.approve(pending["approval_id"])

    assert "token_hash" not in store.show(pending["approval_id"])
    assert "token_hash" not in store.list()[0]
    with pytest.raises(ValueError, match="approval_id"):
        store.show("../other")


def test_cli_can_approve_a_pending_request(tmp_path, capsys):
    pending = ApprovalStore(tmp_path).request("runtime_trace", {"argv": ["pytest"]})
    main(["--json", "approvals", "approve", str(tmp_path), pending["approval_id"]])
    response = json.loads(capsys.readouterr().out)
    assert response["status"] == "approved"
    assert response["approval"]["approval_token"]


def test_concurrent_consumption_allows_exactly_one_caller(tmp_path):
    store = ApprovalStore(tmp_path)
    pending = store.request("runtime_trace", {"argv": ["pytest"]})
    approved = store.approve(pending["approval_id"])
    successes: list[bool] = []

    def consume() -> None:
        try:
            store.consume(pending["approval_id"], approved["approval_token"], "runtime_trace", {"argv": ["pytest"]})
            successes.append(True)
        except (ValueError, TimeoutError):
            successes.append(False)

    callers = [threading.Thread(target=consume) for _ in range(2)]
    [caller.start() for caller in callers]
    [caller.join() for caller in callers]
    assert successes.count(True) == 1
