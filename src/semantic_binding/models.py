from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
import hashlib
import json
from typing import Any, Dict, List, Optional


def stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}"


def _clean_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def _dataclass_to_dict(obj: Any) -> Any:
    if is_dataclass(obj):
        result = {}
        for f in fields(obj):
            value = getattr(obj, f.name)
            if value is None:
                continue
            result[f.name] = _dataclass_to_dict(value)
        return result
    if isinstance(obj, list):
        return [_dataclass_to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): _dataclass_to_dict(v) for k, v in sorted(obj.items(), key=lambda item: str(item[0]))}
    return obj


def _known_kwargs(cls: type, data: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in allowed}


@dataclass
class Evidence:
    kind: str
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    fact_id: Optional[str] = None
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = stable_id("ev", self.kind, self.message, self.file, self.line, self.fact_id)

    def to_dict(self) -> Dict[str, Any]:
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Evidence":
        return cls(**_known_kwargs(cls, data))


@dataclass
class Symbol:
    name: str
    qualified_name: Optional[str] = None
    kind: str = "symbol"
    file: Optional[str] = None
    line: Optional[int] = None
    type_name: Optional[str] = None
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.qualified_name is None:
            self.qualified_name = self.name
        if self.id is None:
            self.id = stable_id("sym", self.qualified_name, self.kind, self.file, self.line)

    def to_dict(self) -> Dict[str, Any]:
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Symbol":
        return cls(**_known_kwargs(cls, data))


@dataclass
class ImportFact:
    module: str
    name: Optional[str] = None
    alias: Optional[str] = None
    file: Optional[str] = None
    line: Optional[int] = None
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = stable_id("imp", self.module, self.name, self.alias, self.file, self.line)

    @property
    def local_name(self) -> str:
        if self.alias:
            return self.alias
        if self.name:
            return self.name
        return self.module.rsplit(".", 1)[-1]

    @property
    def target_name(self) -> str:
        return f"{self.module}.{self.name}" if self.name else self.module

    def to_dict(self) -> Dict[str, Any]:
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImportFact":
        return cls(**_known_kwargs(cls, data))


@dataclass
class ExportFact:
    name: str
    target: Optional[str] = None
    module: Optional[str] = None
    file: Optional[str] = None
    line: Optional[int] = None
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = stable_id("exp", self.module, self.name, self.target, self.file, self.line)

    def to_dict(self) -> Dict[str, Any]:
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExportFact":
        return cls(**_known_kwargs(cls, data))


@dataclass
class AssignmentFact:
    target: str
    value: Any = None
    value_kind: str = "symbol"
    file: Optional[str] = None
    line: Optional[int] = None
    caller: Optional[str] = None
    key: Optional[str] = None
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    type_name: Optional[str] = None
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = stable_id("asg", self.target, self.value, self.value_kind, self.file, self.line, self.key, self.args, self.kwargs)

    def to_dict(self) -> Dict[str, Any]:
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssignmentFact":
        return cls(**_known_kwargs(cls, data))


@dataclass
class CallFact:
    caller: Optional[str] = None
    function: Optional[str] = None
    receiver: Optional[str] = None
    method: Optional[str] = None
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    file: Optional[str] = None
    line: Optional[int] = None
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = stable_id("call", self.caller, self.function, self.receiver, self.method, self.args, self.kwargs, self.file, self.line)

    @property
    def callee_name(self) -> Optional[str]:
        if self.function:
            return self.function
        if self.receiver and self.method:
            return f"{self.receiver}.{self.method}"
        return self.method

    def to_dict(self) -> Dict[str, Any]:
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CallFact":
        return cls(**_known_kwargs(cls, data))


@dataclass
class ReturnFact:
    function: str
    value: Any = None
    value_kind: str = "symbol"
    object_keys: Dict[str, Any] = field(default_factory=dict)
    file: Optional[str] = None
    line: Optional[int] = None
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = stable_id("ret", self.function, self.value, self.value_kind, self.object_keys, self.file, self.line)

    def to_dict(self) -> Dict[str, Any]:
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReturnFact":
        return cls(**_known_kwargs(cls, data))


@dataclass
class FunctionFact:
    name: str
    qualified_name: Optional[str] = None
    params: List[str] = field(default_factory=list)
    file: Optional[str] = None
    line: Optional[int] = None
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.qualified_name is None:
            self.qualified_name = self.name
        if self.id is None:
            self.id = stable_id("fn", self.qualified_name, self.file, self.line, self.params)

    def to_dict(self) -> Dict[str, Any]:
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FunctionFact":
        return cls(**_known_kwargs(cls, data))


@dataclass
class ClassFact:
    name: str
    qualified_name: Optional[str] = None
    methods: List[str] = field(default_factory=list)
    file: Optional[str] = None
    line: Optional[int] = None
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.qualified_name is None:
            self.qualified_name = self.name
        if self.id is None:
            self.id = stable_id("cls", self.qualified_name, self.file, self.line, self.methods)

    def method_qualified_name(self, method: str) -> str:
        return f"{self.name}.{method}"

    def to_dict(self) -> Dict[str, Any]:
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClassFact":
        return cls(**_known_kwargs(cls, data))


@dataclass
class DecoratorFact:
    target: str
    decorator: Optional[str] = None
    receiver: Optional[str] = None
    method: Optional[str] = None
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    file: Optional[str] = None
    line: Optional[int] = None
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = stable_id("dec", self.target, self.decorator, self.receiver, self.method, self.args, self.kwargs, self.file, self.line)

    def to_dict(self) -> Dict[str, Any]:
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecoratorFact":
        return cls(**_known_kwargs(cls, data))


@dataclass
class Binding:
    source: str
    target: str
    kind: str
    confidence: float = 1.0
    evidence: List[Evidence] = field(default_factory=list)
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = stable_id("bind", self.source, self.target, self.kind)

    def to_dict(self) -> Dict[str, Any]:
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Binding":
        known = _known_kwargs(cls, data)
        known["evidence"] = [Evidence.from_dict(e) if isinstance(e, dict) else e for e in known.get("evidence", [])]
        return cls(**known)


@dataclass
class DataFlowFact:
    source: str
    target: str
    kind: str
    confidence: float = 1.0
    evidence: List[Evidence] = field(default_factory=list)
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = stable_id("flow", self.source, self.target, self.kind)

    def to_dict(self) -> Dict[str, Any]:
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DataFlowFact":
        known = _known_kwargs(cls, data)
        known["evidence"] = [Evidence.from_dict(e) if isinstance(e, dict) else e for e in known.get("evidence", [])]
        return cls(**known)


@dataclass
class ResolvedEdge:
    source: str
    target: str
    kind: str
    confidence: float = 1.0
    method: Optional[str] = None
    path: Optional[str] = None
    evidence: List[Evidence] = field(default_factory=list)
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = stable_id("edge", self.source, self.target, self.kind, self.method, self.path)

    def to_dict(self) -> Dict[str, Any]:
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResolvedEdge":
        known = _known_kwargs(cls, data)
        known["evidence"] = [Evidence.from_dict(e) if isinstance(e, dict) else e for e in known.get("evidence", [])]
        return cls(**known)


@dataclass
class Recipe:
    id: str
    type: str
    constructor: Optional[str] = None
    prefix_kwarg: Optional[str] = None
    include_method: Optional[str] = None
    decorator_methods: List[str] = field(default_factory=list)
    sink_functions: List[str] = field(default_factory=list)
    wrapper_functions: List[str] = field(default_factory=list)
    method_by_wrapper: Dict[str, str] = field(default_factory=dict)
    providers: Dict[str, str] = field(default_factory=dict)
    path_builder_functions: List[str] = field(default_factory=list)
    method_by_sink: Dict[str, str] = field(default_factory=dict)
    decorators: List[str] = field(default_factory=list)
    options: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Recipe":
        known = _known_kwargs(cls, data)
        return cls(**known)


@dataclass
class ResolutionResult:
    symbols: List[Symbol] = field(default_factory=list)
    bindings: List[Binding] = field(default_factory=list)
    dataflow: List[DataFlowFact] = field(default_factory=list)
    resolved_edges: List[ResolvedEdge] = field(default_factory=list)
    diagnostics: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbols": [s.to_dict() for s in sorted(self.symbols, key=lambda s: s.id or "")],
            "bindings": [b.to_dict() for b in sorted(self.bindings, key=lambda b: b.id or "")],
            "dataflow": [d.to_dict() for d in sorted(self.dataflow, key=lambda d: d.id or "")],
            "resolved_edges": [e.to_dict() for e in sorted(self.resolved_edges, key=lambda e: e.id or "")],
            "diagnostics": sorted(set(self.diagnostics)),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResolutionResult":
        return cls(
            symbols=[Symbol.from_dict(i) for i in data.get("symbols", [])],
            bindings=[Binding.from_dict(i) for i in data.get("bindings", [])],
            dataflow=[DataFlowFact.from_dict(i) for i in data.get("dataflow", [])],
            resolved_edges=[ResolvedEdge.from_dict(i) for i in data.get("resolved_edges", [])],
            diagnostics=list(data.get("diagnostics", [])),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)
