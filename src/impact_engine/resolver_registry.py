"""Declarative resolver contracts used by incremental orchestration."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Iterable

@dataclass(frozen=True)
class ResolverContract:
    resolver_id: str
    consumed_fact_kinds: tuple[str, ...]
    consumed_dependency_key_prefixes: tuple[str, ...]
    produced_edge_kinds: tuple[str, ...]
    requires_global_context: bool = False

    def to_dict(self): return asdict(self)

RESOLVERS = (
    ResolverContract("import_alias_resolver", ("IMPORT",), ("file:", "module:", "import:"), ("IMPORTS",)),
    ResolverContract("call_target_resolver", ("CALL_SITE", "DECLARATION"), ("symbol:", "method:"), ("CALLS", "RESOLVES_TO")),
    ResolverContract("typed_receiver_resolver", ("CALL_SITE", "TYPE_ANNOTATION", "FIELD_BINDING", "DECLARATION"), ("type:", "method:"), ("CALLS",)),
    ResolverContract("constructor_binding_resolver", ("CONSTRUCTOR_CALL", "ASSIGNMENT", "DECLARATION"), ("type:", "provider:"), ("INSTANCE_OF", "PARAM_BINDS_TO", "FIELD_BINDS_TO")),
    ResolverContract("provider_di_resolver", ("PROVIDER_BINDING", "CONSTRUCTOR_CALL"), ("provider:", "type:"), ("PROVIDED_BY_SUPPORT_PACK", "DEPENDS_ON")),
    ResolverContract("router_composition_resolver", ("ROUTER_INCLUDE", "ROUTE_DECLARATION"), ("route:", "module:"), ("ROUTE_HANDLES",)),
    ResolverContract("route_handler_resolver", ("ROUTE_DECLARATION", "DECLARATION"), ("route:", "symbol:"), ("ROUTE_HANDLES",)),
    ResolverContract("frontend_endpoint_resolver", ("HTTP_CLIENT_CALL", "CALL_SITE"), ("endpoint:", "route:"), ("HTTP_CALLS",)),
    ResolverContract("endpoint_backend_bridge_resolver", ("HTTP_CLIENT_CALL", "ROUTE_DECLARATION"), ("endpoint:", "route:"), ("MATCHES_ENDPOINT", "HTTP_CALLS"), True),
    ResolverContract("support_pack_resolver", ("SUPPORT_PACK_MATCH",), ("support_pack:",), ("PROVIDED_BY_SUPPORT_PACK", "CALLS", "DEPENDS_ON")),
    ResolverContract("unknown_region_resolver", ("CALL_SITE", "IMPORT"), ("file:", "module:", "symbol:"), (), True),
)

def list_resolver_contracts(): return [contract.to_dict() for contract in RESOLVERS]

def select_resolvers(fact_kinds: Iterable[str], dependency_keys: Iterable[str]) -> tuple[list[str], list[str]]:
    kinds=set(fact_kinds); keys=list(dependency_keys); rerun=[]; skipped=[]
    for contract in RESOLVERS:
        matches=bool(kinds.intersection(contract.consumed_fact_kinds)) or any(any(key.startswith(prefix) for prefix in contract.consumed_dependency_key_prefixes) for key in keys)
        (rerun if matches else skipped).append(contract.resolver_id)
    return sorted(rerun), sorted(skipped)
