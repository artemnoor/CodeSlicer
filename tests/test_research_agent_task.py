import json

from impact_engine.research.agent_task import build_agent_task, write_agent_task


def test_agent_task_is_provider_neutral_and_machine_readable(tmp_path):
    input_pack = {
        "research_request": {"library_name": "fastapi", "ecosystem": "python"},
        "source_plan": [{"url": "https://fastapi.tiangolo.com/", "source_type": "official_docs"}],
    }
    task = build_agent_task(input_pack, workflow_id="wf-1", output_path="candidate_support_pack.json")
    assert task["task_type"] == "impact_engine.support_pack_research"
    assert "OpenAI" not in task["system_prompt"]
    assert "Never invent APIs" in task["system_prompt"]
    assert task["output_contract"]["format"] == "support_pack.json"

    path = write_agent_task(tmp_path, input_pack, "wf-1")
    assert json.loads((tmp_path / "agent_task.json").read_text(encoding="utf-8"))["workflow_id"] == "wf-1"
    assert (tmp_path / "agent_system_prompt.txt").exists()
