from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .models import (
    AssignmentFact,
    CallFact,
    ClassFact,
    DecoratorFact,
    ExportFact,
    FunctionFact,
    ImportFact,
    ReturnFact,
    Symbol,
)


@dataclass
class FactSet:
    symbols: List[Symbol] = field(default_factory=list)
    imports: List[ImportFact] = field(default_factory=list)
    exports: List[ExportFact] = field(default_factory=list)
    assignments: List[AssignmentFact] = field(default_factory=list)
    calls: List[CallFact] = field(default_factory=list)
    returns: List[ReturnFact] = field(default_factory=list)
    functions: List[FunctionFact] = field(default_factory=list)
    classes: List[ClassFact] = field(default_factory=list)
    decorators: List[DecoratorFact] = field(default_factory=list)
    files: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FactSet":
        if not isinstance(data, dict):
            raise TypeError("facts must be a JSON object")
        return cls(
            symbols=[Symbol.from_dict(i) for i in data.get("symbols", [])],
            imports=[ImportFact.from_dict(i) for i in data.get("imports", [])],
            exports=[ExportFact.from_dict(i) for i in data.get("exports", [])],
            assignments=[AssignmentFact.from_dict(i) for i in data.get("assignments", [])],
            calls=[CallFact.from_dict(i) for i in data.get("calls", [])],
            returns=[ReturnFact.from_dict(i) for i in data.get("returns", [])],
            functions=[FunctionFact.from_dict(i) for i in data.get("functions", [])],
            classes=[ClassFact.from_dict(i) for i in data.get("classes", [])],
            decorators=[DecoratorFact.from_dict(i) for i in data.get("decorators", [])],
            files=list(data.get("files", [])),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbols": [i.to_dict() for i in self.symbols],
            "imports": [i.to_dict() for i in self.imports],
            "exports": [i.to_dict() for i in self.exports],
            "assignments": [i.to_dict() for i in self.assignments],
            "calls": [i.to_dict() for i in self.calls],
            "returns": [i.to_dict() for i in self.returns],
            "functions": [i.to_dict() for i in self.functions],
            "classes": [i.to_dict() for i in self.classes],
            "decorators": [i.to_dict() for i in self.decorators],
            "files": list(self.files),
        }

    def validate(self) -> List[str]:
        errors: List[str] = []
        for i, imp in enumerate(self.imports):
            if not imp.module:
                errors.append(f"imports[{i}].module is required")
        for i, assignment in enumerate(self.assignments):
            if not assignment.target:
                errors.append(f"assignments[{i}].target is required")
        for i, call in enumerate(self.calls):
            if not call.function and not (call.receiver and call.method):
                errors.append(f"calls[{i}] requires function or receiver+method")
        for i, fn in enumerate(self.functions):
            if not fn.name:
                errors.append(f"functions[{i}].name is required")
        return errors
