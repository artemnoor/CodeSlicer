"""Provider-neutral task contract for any AI library researcher agent."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RESEARCH_AGENT_SYSTEM_PROMPT = """You are an AI Library Researcher for Impact Engine.

Your job is to transform a bounded research input pack into one deterministic
support_pack.json. Read the supplied input pack first. You may browse the
listed HTTPS primary sources and official repository examples/tests if your
runtime has network access. Never invent APIs and never treat a package name
match as semantic evidence.

Research order:
1. Project usage examples and detected imports.
2. Official documentation for public semantics.
3. Official repository source, examples, and tests for actual behavior.
4. Package registry only for package/version metadata.

Every rule must be deterministic, have a stable id, and cite an evidence URL
from the input source plan or fetched corpus. Record unsupported, unavailable,
and unverified behaviors in coverage_limitations. Keep trust_level at
experimental unless fixture and real-project validation are already present.

Rule authoring contract:
- Use `decorator_entrypoint`, `constructor_injection`, `framework_route`,
  `test_target_pattern`, or `method_call_alias` only when the rule is backed by
  an official source and a runnable fixture.
- `method_call_alias` accepts `match.method` as a string or list, and may use
  `match.receiver` or `match.receiver_type`. Its `emit.to` is optional when
  the rule identifies an external library call; the engine then emits a
  deterministic `external:<library>.<method>` target. Do not omit `emit.to`
  for ordinary `standard` rules.
- Do not encode name similarity as a semantic edge. Prefer explicit receiver,
  decorator, import, parameter type, route, or provider evidence.
- Include rule_version and matched-pattern details when known; every generated
  edge must remain explainable through source URLs and local fixture evidence.

Return exactly one JSON object: support_pack.json. Do not return Markdown,
prose, code fences, or a second file. The host Impact Engine will validate the
object, run fixtures, apply trust caps, and store it in its registry.
"""


def build_agent_task(input_pack: dict[str, Any], *, workflow_id: str, output_path: str) -> dict[str, Any]:
    request = input_pack.get("research_request", {})
    return {
        "task_type": "impact_engine.support_pack_research",
        "protocol_version": "1.0",
        "workflow_id": workflow_id,
        "library": request.get("library_name"),
        "ecosystem": request.get("ecosystem"),
        "system_prompt": RESEARCH_AGENT_SYSTEM_PROMPT,
        "input_pack": input_pack,
        "output_contract": {
            "format": "support_pack.json",
            "path": output_path,
            "must_be_json_object": True,
            "validation_command": f"impact-engine research validate {workflow_id} --support-pack <path>",
            "install_command": f"impact-engine research install {workflow_id} --support-pack <path>",
        },
    }


def write_agent_task(workflow_dir: str | Path, input_pack: dict[str, Any], workflow_id: str) -> str:
    root = Path(workflow_dir)
    output_path = str((root / "candidate_support_pack.json").as_posix())
    task = build_agent_task(input_pack, workflow_id=workflow_id, output_path=output_path)
    path = root / "agent_task.json"
    path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "agent_system_prompt.txt").write_text(RESEARCH_AGENT_SYSTEM_PROMPT, encoding="utf-8")
    return str(path.as_posix())
