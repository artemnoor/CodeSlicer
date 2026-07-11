from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


JsonDict = Dict[str, Any]


def _drop_none(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _drop_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_drop_none(v) for v in obj]
    return obj


def to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return _drop_none(asdict(obj))
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, list):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    return obj


@dataclass(frozen=True)
class ResearchRequest:
    library: str
    ecosystem: str
    project_path: str = "."
    version_range: str = "*"
    allow_network: bool = False
    max_pages: int = 8
    max_page_size_bytes: int = 250_000
    max_total_bytes: int = 1_000_000
    timeout_seconds: float = 8.0

    @classmethod
    def from_dict(cls, data: JsonDict) -> "ResearchRequest":
        return cls(**data)


@dataclass
class ResearchWorkflow:
    workflow_id: str
    request: ResearchRequest
    storage_path: str
    status: str = "created"
    diagnostics: List[str] = field(default_factory=list)


@dataclass
class ResearchSource:
    url: str
    source_type: str
    title: str = ""
    official: bool = False
    priority: int = 50
    reason: str = ""
    local_path: Optional[str] = None

    @classmethod
    def from_dict(cls, data: JsonDict) -> "ResearchSource":
        return cls(**data)


@dataclass
class FetchedPage:
    source_url: str
    source_type: str
    title: str = ""
    content_type: str = "text/plain"
    text_excerpt: str = ""
    status_code: Optional[int] = None
    error: Optional[str] = None
    bytes_read: int = 0
    local_path: Optional[str] = None

    @classmethod
    def from_dict(cls, data: JsonDict) -> "FetchedPage":
        return cls(**data)


@dataclass
class ExtractedExample:
    id: str
    source_url: str
    kind: str
    language: str
    snippet: str
    signals: List[str] = field(default_factory=list)
    confidence: float = 0.5
    context: str = ""

    @classmethod
    def from_dict(cls, data: JsonDict) -> "ExtractedExample":
        return cls(**data)


@dataclass
class ResearchInputPack:
    library: str
    ecosystem: str
    version_range: str
    detected_imports: List[str]
    fetched_source_excerpts: List[JsonDict]
    extracted_examples: List[JsonDict]
    diagnostics: List[str] = field(default_factory=list)


@dataclass
class SupportPackDraft:
    pack: JsonDict


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checked_rules: int = 0

    @classmethod
    def from_dict(cls, data: JsonDict) -> "ValidationResult":
        return cls(**data)
