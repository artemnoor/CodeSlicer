from __future__ import annotations

import pytest
import json
import threading

from impact_engine.approvals import ApprovalStore
from impact_engine.cli import main
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
