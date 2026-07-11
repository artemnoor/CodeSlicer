"""Research request and input pack schema representations. Stage 14."""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any
import datetime


@dataclass
class ResearchRequest:
    ecosystem: str
    library_name: str
    detected_imports: List[str] = field(default_factory=list)
    manifest_source: str = "pyproject.toml"
    candidate_docs_urls: List[str] = field(default_factory=list)
    candidate_github_urls: List[str] = field(default_factory=list)
    candidate_registry_urls: List[str] = field(default_factory=list)
    source_plan: List[Dict[str, Any]] = field(default_factory=list)
    examples_needed: List[str] = field(default_factory=list)
    detected_project_usage_examples: List[str] = field(default_factory=list)
    expected_support_pack_schema_version: str = "v1"
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchInputPack:
    research_request: Dict[str, Any]
    fetched_pages: List[Dict[str, Any]] = field(default_factory=list)
    source_plan: List[Dict[str, Any]] = field(default_factory=list)
    source_coverage: Dict[str, Any] = field(default_factory=dict)
    detected_project_usage_examples: List[str] = field(default_factory=list)
    required_output_schema: Dict[str, Any] = field(default_factory=dict)
    validation_rules: List[str] = field(default_factory=list)
    forbidden_behaviors: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Default required schema
        self.required_output_schema = {
            "library": "string",
            "version_range": "string",
            "language": "string",
            "edge_rules": [
                {
                    "id": "string",
                    "type": "string (decorator_entrypoint, constructor_injection, method_call_alias, framework_route, test_target_pattern, standard)",
                    "match": "object",
                    "emit": "object"
                }
            ],
            "required_metadata": ["trust_level", "sources", "coverage_limitations"],
        }
        
        # Default rules
        self.validation_rules = [
            "Every rule must have a valid non-empty 'id'",
            "Ecosystem/library must match the research request",
            "Every rule must include a valid 'evidence_ref' in matching edge properties pointing to a source URL or usage example",
            "No prose-only rules",
            "Rule types must be deterministic (decorator_entrypoint, constructor_injection, method_call_alias, framework_route, test_target_pattern, or standard)",
            "Use official documentation and repository tests/examples as primary evidence",
            "Declare unsupported or unverified behaviors in coverage_limitations",
            "Do not assign trusted status without fixture and real-project validation"
        ]
        
        # Forbidden behaviors
        self.forbidden_behaviors = [
            "Do not invent APIs",
            "Output valid support_pack.json only",
            "No prose or explanation outside support_pack.json",
            "Deterministic rules only",
            "Do not treat a library name match as semantic evidence"
        ]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
