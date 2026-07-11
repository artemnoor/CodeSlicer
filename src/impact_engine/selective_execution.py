"""Planning/execution contracts for provenance-aware incremental resolution."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

@dataclass
class ResolverExecutionPlan:
    resolvers_to_run: list[str] = field(default_factory=list)
    resolvers_to_skip: list[str] = field(default_factory=list)
    affected_fact_ids: list[str] = field(default_factory=list)
    affected_dependency_keys: list[str] = field(default_factory=list)
    edges_to_remove: list[str] = field(default_factory=list)
    nodes_to_refresh: list[str] = field(default_factory=list)
    required_context_fact_ids: list[str] = field(default_factory=list)
    fallback_reasons: list[str] = field(default_factory=list)
    def to_dict(self): return asdict(self)

@dataclass
class ResolverExecutionResult:
    executed_resolvers: list[str] = field(default_factory=list)
    skipped_resolvers: list[str] = field(default_factory=list)
    edges_removed: list[str] = field(default_factory=list)
    edges_created: list[str] = field(default_factory=list)
    edges_reused: list[str] = field(default_factory=list)
    unexpected_resolvers_executed: list[str] = field(default_factory=list)
    full_pipeline_called: bool = False
    post_processing_stages: list[str] = field(default_factory=list)
    def to_dict(self): return asdict(self)

class ResolverContextBuilder:
    def __init__(self, facts: list[dict[str, Any]]):
        self.facts = list(facts)
    def build(self, fact_ids: list[str], dependency_keys: list[str]) -> list[dict[str, Any]]:
        ids=set(fact_ids); keys=set(dependency_keys)
        result=[]
        for fact in self.facts:
            if fact.get("fact_id") in ids or any(key in {f"file:{fact.get('file')}", f"symbol:{fact.get('canonical_subject')}", f"symbol:{fact.get('canonical_target')}"} for key in keys):
                result.append(fact)
        return sorted(result, key=lambda item: str(item.get("fact_id", "")))

def execute_handlers(plan: ResolverExecutionPlan, handlers: dict[str, Callable[[list[dict[str, Any]]], list[dict[str, Any]]]], context: list[dict[str, Any]]) -> ResolverExecutionResult:
    result=ResolverExecutionResult(skipped_resolvers=sorted(plan.resolvers_to_skip), edges_removed=sorted(plan.edges_to_remove))
    for resolver_id in sorted(plan.resolvers_to_run):
        handler=handlers.get(resolver_id)
        if handler is None:
            result.skipped_resolvers.append(resolver_id)
            continue
        result.executed_resolvers.append(resolver_id)
        for edge in handler(context) or []:
            if edge.get("id"): result.edges_created.append(str(edge["id"]))
    result.executed_resolvers=sorted(set(result.executed_resolvers))
    result.skipped_resolvers=sorted(set(result.skipped_resolvers))
    result.unexpected_resolvers_executed=sorted(set(result.executed_resolvers)-set(plan.resolvers_to_run))
    if result.unexpected_resolvers_executed:
        raise AssertionError(f"unexpected selective resolvers: {result.unexpected_resolvers_executed}")
    return result
