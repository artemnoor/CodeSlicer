"""Dataclass models used internally by Runtime Trace Booster.

The public API returns plain JSON-compatible dictionaries. These dataclasses keep
implementation boundaries explicit without introducing runtime dependencies such
as pydantic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Diagnostic:
    level: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RuntimeCall:
    caller: str
    callee: str
    caller_file: str
    caller_line: int
    callee_file: str
    callee_line: int
    test_id: str
    confidence: float = 0.98
    source: str = "RUNTIME_CONFIRMED"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RuntimeTest:
    id: str
    status: str
    file: str
    runtime_calls: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MatchedEdge:
    edge_id: str
    from_: str
    to: str
    kind: str
    runtime_confidence: float
    test_id: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["from"] = data.pop("from_")
        return data
