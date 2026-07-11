from __future__ import annotations

from typing import Dict, Iterable, List

from .bindings import BindingResolver
from .facts import FactSet
from .models import DataFlowFact, Evidence, Recipe


class DataFlowEngine:
    """Creates lightweight interprocedural dataflow facts."""

    def __init__(self, facts: FactSet, bindings: BindingResolver, recipes: Iterable[Recipe] = ()) -> None:
        self.facts = facts
        self.bindings = bindings
        self.recipes = list(recipes)
        self.function_params: Dict[str, List[str]] = {fn.name: list(fn.params) for fn in facts.functions}
        for fn in facts.functions:
            if fn.qualified_name:
                self.function_params[fn.qualified_name] = list(fn.params)

    def build(self) -> List[DataFlowFact]:
        flows: Dict[str, DataFlowFact] = {}

        def add(flow: DataFlowFact) -> None:
            flows[flow.id or ""] = flow

        for call in self.facts.calls:
            callee = call.function
            if not callee:
                continue
            params = self.function_params.get(callee, [])
            for index, arg in enumerate(call.args):
                if index < len(params):
                    ev = Evidence("arg_to_param", f"argument {index} flows to {callee}.{params[index]}", call.file, call.line, call.id)
                    add(DataFlowFact(str(arg), f"{callee}.{params[index]}", "ARG_TO_PARAM", 0.95, [ev]))

        for assignment in self.facts.assignments:
            if "." in assignment.target and assignment.value is not None:
                kind = "FIELD_TO_FIELD" if "." in str(assignment.value) else "VALUE_TO_FIELD"
                ev = Evidence("field_flow", f"{assignment.value} flows to {assignment.target}", assignment.file, assignment.line, assignment.id)
                add(DataFlowFact(str(assignment.value), assignment.target, kind, 0.95, [ev]))

        for ret in self.facts.returns:
            for key, value in ret.object_keys.items():
                ev = Evidence("return_object", f"{ret.function} returns key {key}", ret.file, ret.line, ret.id)
                add(DataFlowFact(str(value), f"{ret.function}.return.{key}", "RETURN_KEY_TO_SYMBOL", 0.95, [ev]))

        for assignment in self.facts.assignments:
            if assignment.value_kind == "destructure":
                ev = Evidence("destructure", f"{assignment.target} destructured from {assignment.value}.{assignment.key or assignment.target}", assignment.file, assignment.line, assignment.id)
                add(DataFlowFact(str(assignment.value), assignment.target, "DESTRUCTURE_BINDING", 0.9, [ev]))

        return sorted(flows.values(), key=lambda f: f.id or "")
