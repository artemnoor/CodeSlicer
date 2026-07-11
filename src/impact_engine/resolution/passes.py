"""Contracts for decomposing the precision resolver without duplicate logic."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass
class ResolutionContext:
    graph: Any
    raw_facts: Any = None
    symbol_index: Any = None
    import_index: Any = None
    dependency_keys: set[str] = field(default_factory=set)
    support_packs: list[Any] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    configuration: dict[str, Any] = field(default_factory=dict)
    variable_types: dict[tuple[str, str], str] = field(default_factory=dict)
    field_types: dict[tuple[str, str], str] = field(default_factory=dict)
    parameter_types: dict[tuple[str, str], str] = field(default_factory=dict)
    evidences: dict[tuple, list[Any]] = field(default_factory=dict)
    ambiguous_variables: dict[tuple[str, str], list[str]] = field(default_factory=dict)

@dataclass
class ResolutionPassResult:
    pass_id: str
    created_edges: list[Any] = field(default_factory=list)
    updated_nodes: list[Any] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

@dataclass(frozen=True)
class ResolutionPassDefinition:
    pass_id: str
    handler: Callable[..., ResolutionPassResult]
    produced_edge_kinds: tuple[str, ...]

# These definitions are intentionally empty until the corresponding blocks in
# engine.py are extracted. Registering a wrapper around resolve_graph would be
# incorrect and would break selective execution guarantees.
PASS_IDS = (
    "constructor_provider_binding_pass",
    "field_binding_propagation_pass",
    "import_alias_resolution_pass",
    "call_target_resolution_pass",
    "route_handler_resolution_pass",
    "nested_object_resolution_pass",
    "support_pack_resolution_pass",
    "unknown_region_resolution_pass",
)
