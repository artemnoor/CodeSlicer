"""Support Pack Resolver Hooks and Rule Engine. Stage 14."""
import json
import re
from impact_engine.models import GraphDocument, Node, Edge, Evidence
from impact_engine.support_packs.schema import (
    SUPPORT_PACK_CONFIDENCE_CAPS,
    SUPPORT_PACK_INACTIVE_TRUST_LEVELS,
    SupportPack,
    cap_support_pack_confidence,
    normalize_support_pack_trust_level,
)


def _pack_value(pack, key: str, default=None):
    if isinstance(pack, dict):
        return pack.get(key, default)
    return getattr(pack, key, default)


def _effective_trust_level(pack) -> str:
    status = _pack_value(pack, "status", "")
    trust_level = _pack_value(pack, "trust_level", "")
    # Backward compatibility: legacy raw dict tests often omit status entirely.
    # Real schema-created SupportPack objects still default to experimental.
    if isinstance(pack, dict) and not status and not trust_level:
        return "trusted"
    return normalize_support_pack_trust_level(status, trust_level)


def _cap_confidence_for_pack(pack, confidence: float) -> float:
    effective = _effective_trust_level(pack)
    if isinstance(pack, dict) and not pack.get("status") and not pack.get("trust_level"):
        return min(float(confidence), SUPPORT_PACK_CONFIDENCE_CAPS["trusted"])
    return cap_support_pack_confidence(float(confidence), _pack_value(pack, "status", ""), _pack_value(pack, "trust_level", ""))


def _evidence_to_dicts(edge: Edge) -> list[dict]:
    result = []
    for ev in edge.evidence or []:
        result.append({
            "description": getattr(ev, "description", ""),
            "file": getattr(ev, "file", None),
            "line": getattr(ev, "line", None),
            "source": getattr(ev, "source", ""),
        })
    return result


def _pack_ref(pack, library: str) -> str:
    ecosystem = _pack_value(pack, "ecosystem", "") or _pack_value(pack, "language", "")
    if ecosystem:
        return f"{ecosystem}/{library}"
    return library


def _annotate_support_pack_edge(edge: Edge, pack, library: str, version_range: str, rule: dict | None = None) -> None:
    effective = _effective_trust_level(pack)
    edge.confidence = _cap_confidence_for_pack(pack, edge.confidence)
    rule_id = edge.properties.get("support_pack_rule_id") or (rule or {}).get("id", "")
    resolver_hook = (rule or {}).get("type") or edge.properties.get("resolver_hook_name") or "standard"
    match = (rule or {}).get("match") or {}
    emit = (rule or {}).get("emit") or {}
    matched_pattern = (
        edge.properties.get("matched_pattern")
        or match.get("decorator")
        or match.get("call_name")
        or match.get("method_name")
        or match.get("parameter_type")
        or match.get("node_kind")
        or edge.properties.get("support_pack_matched_pattern")
        or ""
    )
    if not matched_pattern and match:
        # Preserve the exact rule predicate when it is structured (for
        # example method lists plus receiver_type). An empty pattern makes
        # explain-edge provenance incomplete and hides how the edge matched.
        matched_pattern = json.dumps(match, sort_keys=True, ensure_ascii=False)
    rule_version = str((rule or {}).get("version") or (rule or {}).get("rule_version") or "1.0.0")
    edge.properties.setdefault("support_pack_library", library)
    edge.properties.setdefault("support_pack_id", _pack_value(pack, "id", "") or library)
    edge.properties.setdefault("support_pack_version", version_range)
    edge.properties.setdefault("support_pack_rule_id", rule_id)
    edge.properties.setdefault("resolver_hook_name", resolver_hook)
    edge.properties["support_pack_trust_level"] = effective
    if effective in SUPPORT_PACK_CONFIDENCE_CAPS:
        edge.properties["support_pack_confidence_cap"] = SUPPORT_PACK_CONFIDENCE_CAPS[effective]
    edge.properties["support_pack_active"] = effective not in SUPPORT_PACK_INACTIVE_TRUST_LEVELS
    edge.properties["support_pack"] = {
        "support_pack": _pack_ref(pack, library),
        "rule_id": rule_id,
        "rule_version": rule_version,
        "trust_level": effective,
        "resolver_hook": resolver_hook,
        "matched_pattern": matched_pattern,
        "evidence": _evidence_to_dicts(edge),
    }


def apply_support_pack_rules(graph: GraphDocument, packs: list[SupportPack]) -> GraphDocument:
    from impact_engine.resolution.engine import resolve_class_name, module_for_scope, build_symbol_index, get_node_location
    if not packs:
        return graph
    index = build_symbol_index(graph)

    nodes_by_scope = {
        str(node.properties.get("scope")): node
        for node in graph.nodes
        if node.properties.get("scope") and node.properties.get("file")
    }
    modules_by_file = {
        str(node.properties.get("file")): (node.id[7:] if node.id.startswith("module:") else node.id)
        for node in graph.nodes
        if node.kind == "MODULE" and node.properties.get("file")
    }
    module_names = [
        node.id[7:] if node.id.startswith("module:") else node.id
        for node in graph.nodes
        if node.kind == "MODULE"
    ]
    files_by_module: dict[str, str] = {}
    for edge in graph.edges:
        if edge.kind == "CONTAINS" and edge.from_node.startswith("file:"):
            module_id = edge.to_node[7:] if edge.to_node.startswith("module:") else edge.to_node
            files_by_module[module_id] = edge.from_node[5:]
    
    def get_node_language(node, graph) -> str:
        file_path = node.properties.get("file")
        if node.kind == "FILE":
            file_path = node.properties.get("path") or (node.id[5:] if node.id.startswith("file:") else node.id)
        elif node.kind == "MODULE":
            mod_name = node.properties.get("name") or (node.id[7:] if node.id.startswith("module:") else node.id)
            file_path = files_by_module.get(str(mod_name))
        elif not file_path:
            scope = node.properties.get("scope")
            if scope:
                scoped_node = nodes_by_scope.get(str(scope))
                if scoped_node:
                    file_path = scoped_node.properties.get("file")
                if not file_path:
                    curr_mod = module_for_scope(scope, graph)
                    file_path = files_by_module.get(curr_mod)
        if file_path:
            ext = "." + file_path.split(".")[-1].lower() if "." in file_path else ""
            if ext == ".py":
                return "python"
            if ext in (".js", ".jsx", ".ts", ".tsx"):
                return "javascript"
            if ext == ".go":
                return "go"
            if ext == ".java":
                return "java"
        return ""

    def node_file_and_line(node, graph):
        f = node.properties.get("file")
        l = node.properties.get("line")
        if not f:
            f, l = get_node_location(node.id, graph)
        return f, l

    # Collect library imports mapping for imported_library check: module -> set of imported libraries
    imports_map = {}
    for edge in graph.edges:
        if edge.kind == "IMPORTS":
            from_mod = edge.from_node
            to_mod = edge.to_node
            if from_mod.startswith("module:"):
                from_mod = from_mod[7:]
            if to_mod.startswith("module:"):
                to_mod = to_mod[7:]
            imports_map.setdefault(from_mod, set()).add(to_mod)

    # Helper to get the module of a node
    def get_node_module(node) -> str:
        file_path = node.properties.get("file")
        if file_path:
            module_name = modules_by_file.get(str(file_path))
            if module_name:
                return module_name
        scope = node.properties.get("scope") or ""
        if not scope:
            return ""
        longest_module = ""
        for mod_name in module_names:
            if scope == mod_name or scope.startswith(mod_name + "."):
                if len(mod_name) > len(longest_module):
                    longest_module = mod_name
        return longest_module if longest_module else scope.split(".")[0]

    for pack in packs:
        effective_trust_level = _effective_trust_level(pack)
        if isinstance(pack, dict):
            library = pack.get("library", "unknown")
            version_range = pack.get("version_range", "unknown")
            pack_language = pack.get("language", "")
            edge_rules = pack.get("edge_rules", [])
        else:
            library = getattr(pack, "library", "unknown")
            version_range = getattr(pack, "version_range", "unknown")
            pack_language = getattr(pack, "language", "")
            edge_rules = getattr(pack, "edge_rules", [])

        if effective_trust_level in SUPPORT_PACK_INACTIVE_TRUST_LEVELS:
            graph.metadata.setdefault("support_pack_skipped", []).append({
                "library": library,
                "version_range": version_range,
                "trust_level": effective_trust_level,
                "reason": "inactive trust level is not used during normal analyze",
            })
            continue

        if not edge_rules:
            continue

        edge_ids_before_pack = {edge.id for edge in graph.edges}
        rule_lookup = {str(rule.get("id", "")): rule for rule in edge_rules if isinstance(rule, dict)}

        if pack_language:
            nodes_to_process = []
            for n in graph.nodes:
                node_lang = get_node_language(n, graph)
                if not node_lang or node_lang == pack_language.lower():
                    nodes_to_process.append(n)
        else:
            nodes_to_process = list(graph.nodes)

        invalid_rules = []

        for rule in edge_rules:
            if not isinstance(rule, dict):
                continue

            rule_id = rule.get("id", "default")
            rule_type = rule.get("type", "standard")
            match = rule.get("match", {})
            emit = rule.get("emit", {})

            # Validation
            validation_errors = []
            if not match:
                validation_errors.append("Missing 'match' configuration")
            if not emit:
                validation_errors.append("Missing 'emit' configuration")
            else:
                if not emit.get("to") and rule_type not in ("decorator_entrypoint", "task_entrypoint", "fastapi_router_resolver", "fastapi_depends_resolver", "dependency_injector_resolver", "react_resolver", "method_call_alias"):
                    validation_errors.append("Emit missing 'to' field")
                if not emit.get("kind"):
                    validation_errors.append("Emit missing 'kind' field")

            if validation_errors:
                invalid_rules.append({
                    "rule_id": rule_id,
                    "errors": validation_errors,
                    "rule": rule
                })
                continue

            # Process different rule types
            if rule_type == "decorator_entrypoint":
                # Match a method/class with a specific decorator
                dec_pattern = match.get("decorator")
                if not dec_pattern:
                    continue
                
                for node in graph.nodes:
                    decs = node.properties.get("decorators", [])
                    matched_dec = None
                    for d in decs:
                        d_clean = d.lstrip("@")
                        pat_clean = dec_pattern.lstrip("@")
                        if d_clean == pat_clean or d_clean.startswith(pat_clean + "(") or d_clean.startswith(pat_clean):
                            matched_dec = d
                            break
                            
                    if matched_dec:
                        # Extract argument value (e.g. route path) if present, e.g. @app.get("/items") -> "/items"
                        path = ""
                        arg_match = re.search(r'\((["\'])(.*?)\1\)', matched_dec)
                        if arg_match:
                            path = arg_match.group(2)
                            
                        from_pattern = emit.get("from", "HTTP GET {path}")
                        to_pattern = emit.get("to", "{scope}")
                        
                        method_scope = node.properties.get("scope") or node.id
                        from_node = from_pattern.replace("{path}", path) if "{path}" in from_pattern else from_pattern
                        to_node = to_pattern.replace("{scope}", method_scope) if "{scope}" in to_pattern else to_pattern
                        
                        # Add entrypoint node to the graph if it doesn't exist
                        if not any(n.id == from_node for n in graph.nodes):
                            from_kind = "ROUTE"
                            graph.add_node(Node(
                                id=from_node,
                                kind=from_kind,
                                name=from_node,
                                properties={"library": library}
                            ))
                            
                        # Emit inferred edge
                        edge_id = f"support_pack_edge__{library}__{rule_id}__{from_node}__{to_node}"
                        
                        # Avoid duplicates
                        if not any(e.id == edge_id for e in graph.edges):
                            graph.add_edge(Edge(
                                id=edge_id,
                                kind=emit.get("kind", "CALLS"),
                                from_node=from_node,
                                to_node=to_node,
                                source="SUPPORT_PACK",
                                confidence=float(emit.get("confidence", 0.90)),
                                evidence=[Evidence(
                                    file=node.properties.get("file"),
                                    line=node.properties.get("line"),
                                    description=f"Resolved via support pack {library}:{rule_id} (decorator matched)"
                                )],
                                properties={
                                    "support_pack_library": library,
                                    "support_pack_version": version_range,
                                    "support_pack_rule_id": rule_id
                                }
                            ))

            elif rule_type == "task_entrypoint":
                dec_pattern = match.get("decorator", "")
                if not dec_pattern:
                    continue
                for node in nodes_to_process:
                    decorators = node.properties.get("decorators", [])
                    if not any(str(item).lstrip("@").startswith(dec_pattern.lstrip("@")) for item in decorators):
                        continue
                    scope = node.properties.get("scope") or node.id
                    target = emit.get("to", f"external:{library}.task:{scope}").replace("{scope}", str(scope))
                    edge_id = f"support_pack_edge__{library}__{rule_id}__{scope}__{target}"
                    if not any(edge.id == edge_id for edge in graph.edges):
                        file_loc, line_loc = node_file_and_line(node, graph)
                        graph.add_edge(Edge(
                            id=edge_id,
                            kind=emit.get("kind", "DEPENDS_ON"),
                            from_node=scope,
                            to_node=target,
                            source="SUPPORT_PACK",
                            confidence=float(emit.get("confidence", 0.80)),
                            evidence=[Evidence(file=file_loc, line=line_loc, description=f"{library} task registration via {dec_pattern}")],
                            properties={"support_pack_library": library, "support_pack_version": version_range, "support_pack_rule_id": rule_id, "resolver_hook_name": rule_type},
                        ))

            elif rule_type == "constructor_injection":
                param_type_pattern = match.get("parameter_type")
                if not param_type_pattern:
                    continue
                
                for node in graph.nodes:
                    # Match if class fields/parameters type match the injection pattern
                    # For Python DI container or class constructor fields
                    injected = False
                    for prop_k, prop_v in node.properties.items():
                        if prop_k.startswith("param_type:") and prop_v == param_type_pattern:
                            injected = True
                            break
                        if prop_k == "receiver_type" and prop_v == param_type_pattern:
                            injected = True
                            break
                            
                    if injected:
                        from_node = node.properties.get("scope") or node.id
                        to_node = emit.get("to", param_type_pattern)
                        edge_id = f"support_pack_edge__{library}__{rule_id}__{from_node}__{to_node}"
                        
                        if not any(e.id == edge_id for e in graph.edges):
                            graph.add_edge(Edge(
                                id=edge_id,
                                kind=emit.get("kind", "CALLS"),
                                from_node=from_node,
                                to_node=to_node,
                                source="SUPPORT_PACK",
                                confidence=float(emit.get("confidence", 0.85)),
                                evidence=[Evidence(
                                    file=node.properties.get("file"),
                                    line=node.properties.get("line"),
                                    description=f"Constructor injection of {param_type_pattern} in {from_node}"
                                )],
                                properties={
                                    "support_pack_library": library,
                                    "support_pack_version": version_range,
                                    "support_pack_rule_id": rule_id
                                }
                            ))

            elif rule_type == "method_call_alias":
                alias_name = match.get("alias_name")
                method_names = match.get("method") or match.get("method_name") or alias_name
                if isinstance(method_names, str):
                    method_names = [method_names]
                receiver = match.get("receiver")
                receiver_type = match.get("receiver_type")
                if not method_names:
                    continue
                
                for node in nodes_to_process:
                    if node.kind != "CALL_EXPR":
                        continue
                    method_name = node.properties.get("method_name") or node.properties.get("call_name", "").rsplit(".", 1)[-1]
                    if method_name not in method_names:
                        continue
                    if receiver and node.properties.get("receiver") != receiver:
                        continue
                    if receiver_type and node.properties.get("receiver_type") != receiver_type:
                        continue
                    imported_library = match.get("imported_library")
                    if imported_library:
                        module_name = get_node_module(node)
                        imported = imports_map.get(module_name, set())
                        if not any(item == imported_library or item.startswith(imported_library + ".") for item in imported):
                            continue
                    from_node = node.properties.get("scope") or node.id
                    target_name = emit.get("to") or f"external:{library}.{method_name}"
                    edge_id = f"support_pack_edge__{library}__{rule_id}__{from_node}__{target_name}"

                    if not any(e.id == edge_id for e in graph.edges):
                        file_loc, line_loc = node_file_and_line(node, graph)
                        graph.add_edge(Edge(
                            id=edge_id,
                            kind=emit.get("kind", "CALLS"),
                            from_node=from_node,
                            to_node=target_name,
                            source="SUPPORT_PACK",
                            confidence=float(emit.get("confidence", 0.80)),
                            evidence=[Evidence(
                                file=file_loc,
                                line=line_loc,
                                description=f"Method call alias: {method_name} maps to {target_name}"
                            )],
                            properties={
                                "support_pack_library": library,
                                "support_pack_version": version_range,
                                "support_pack_rule_id": rule_id
                            }
                        ))

            elif rule_type == "framework_route":
                call_pattern = match.get("call_name")
                if not call_pattern:
                    continue
                
                for node in nodes_to_process:
                    if node.kind == "CALL_EXPR" and node.properties.get("call_name") == call_pattern:
                        from_node = node.properties.get("scope") or node.id
                        to_node = emit.get("to")
                        edge_id = f"support_pack_edge__{library}__{rule_id}__{from_node}__{to_node}"
                        
                        if not any(e.id == edge_id for e in graph.edges):
                            file_loc, line_loc = node_file_and_line(node, graph)
                            graph.add_edge(Edge(
                                id=edge_id,
                                kind=emit.get("kind", "DEPENDS_ON"),
                                from_node=from_node,
                                to_node=to_node,
                                source="SUPPORT_PACK",
                                confidence=float(emit.get("confidence", 0.85)),
                                evidence=[Evidence(
                                    file=file_loc,
                                    line=line_loc,
                                    description=f"Framework client route to {to_node}"
                                )],
                                properties={
                                    "support_pack_library": library,
                                    "support_pack_version": version_range,
                                    "support_pack_rule_id": rule_id
                                }
                            ))

            elif rule_type == "test_target_pattern":
                test_class_pattern = match.get("test_class_name")
                if not test_class_pattern:
                    continue
                
                for node in nodes_to_process:
                    if node.kind == "CLASS" and re.match(test_class_pattern, node.name):
                        # Extract suffix target name, e.g. TestOrderService -> OrderService
                        target_name = emit.get("to")
                        if not target_name:
                            # Heuristically strip "Test"
                            target_name = node.name.replace("Test", "").replace("test_", "")
                        
                        # Find the corresponding class in graph
                        target_node = next((n for n in graph.nodes if n.id == target_name or n.name == target_name), None)
                        if target_node:
                            from_node = node.id
                            to_node = target_node.id
                            edge_id = f"support_pack_edge__{library}__{rule_id}__{from_node}__{to_node}"
                            
                            if not any(e.id == edge_id for e in graph.edges):
                                file_loc, line_loc = node_file_and_line(node, graph)
                                graph.add_edge(Edge(
                                    id=edge_id,
                                    kind=emit.get("kind", "TESTS"),
                                    from_node=from_node,
                                    to_node=to_node,
                                    source="SUPPORT_PACK",
                                    confidence=float(emit.get("confidence", 0.95)),
                                    evidence=[Evidence(
                                        file=file_loc,
                                        line=line_loc,
                                        description=f"Test class {node.name} targets class {to_node}"
                                    )],
                                    properties={
                                        "support_pack_library": library,
                                        "support_pack_version": version_range,
                                        "support_pack_rule_id": rule_id
                                    }
                                ))

            elif rule_type == "fastapi_router_resolver":
                # FastAPI Router prefix and nested include_router prefix resolution hook
                router_prefixes = {}
                # 1. Identify APIRouter prefixes
                for n in nodes_to_process:
                    if n.kind == "ASSIGNMENT":
                        call_name = n.properties.get("call_name", "")
                        if call_name == "APIRouter":
                            kw_args = n.properties.get("keyword_args", {})
                            prefix = kw_args.get("prefix", "").strip("'\"")
                            target = n.properties.get("target", "")
                            scope = n.properties.get("scope", "")
                            if target:
                                router_prefixes[(scope, target)] = prefix

                # 2. Identify included routers
                included_routers = []
                for n in nodes_to_process:
                    if n.kind == "CALL_EXPR":
                        call_name = n.properties.get("call_name", "")
                        if call_name in {"app.include_router", "router.include_router"}:
                            args = n.properties.get("args", [])
                            kw_args = n.properties.get("keyword_args", {})
                            include_prefix = kw_args.get("prefix", "").strip("'\"")
                            if args:
                                router_name = args[0]
                                scope = n.properties.get("scope", "")
                                included_routers.append({
                                    "scope": scope,
                                    "router_name": router_name,
                                    "prefix": include_prefix
                                })

                # 3. Composed prefix route matching
                for edge in list(graph.edges):
                    if edge.properties.get("support_pack_library") == "fastapi":
                        rule_id_prop = edge.properties.get("support_pack_rule_id", "")
                        if "route" in rule_id_prop:
                            parts = edge.from_node.split(" ", 2)
                            if len(parts) >= 3:
                                method = parts[1]
                                path = parts[2]
                                to_node_id = edge.to_node
                                to_node = next((n for n in graph.nodes if n.kind in ("METHOD", "CLASS") and (n.id == to_node_id or n.properties.get("scope") == to_node_id or n.id == f"method:{to_node_id}")), None)
                                if to_node:
                                    decs = to_node.properties.get("decorators", [])
                                    matched_dec = None
                                    for d in decs:
                                        if any(x in d for x in {"@router.", "@app."}):
                                            matched_dec = d
                                            break
                                    if matched_dec:
                                        local_path_match = re.search(r"\((['\"])(.*?)\1\)", matched_dec)
                                        if local_path_match:
                                            path = local_path_match.group(2)
                                        base_router = matched_dec.split(".")[0].strip("@ ")
                                        module_name = to_node.properties.get("module", "")
                                        router_prefix = router_prefixes.get((module_name, base_router), "")
                                        
                                        include_prefix = ""
                                        for inc in included_routers:
                                            if inc["router_name"] == base_router and inc["scope"] == module_name:
                                                include_prefix = inc["prefix"]
                                                break
                                            # Match by import alias mapping
                                            inc_module = module_for_scope(inc["scope"], graph)
                                            for mod_node in graph.nodes:
                                                if mod_node.kind == "MODULE" and mod_node.properties.get("name") == inc_module:
                                                    aliases = mod_node.properties.get("import_aliases", {})
                                                    for alias, target_fqn in aliases.items():
                                                        if alias == inc["router_name"] and target_fqn == f"{module_name}.{base_router}":
                                                            include_prefix = inc["prefix"]
                                                            break
                                        
                                        # Compose path
                                        combined_prefix = ""
                                        if include_prefix:
                                            combined_prefix += include_prefix
                                        if router_prefix:
                                            if combined_prefix.endswith("/") and router_prefix.startswith("/"):
                                                combined_prefix += router_prefix[1:]
                                            elif not combined_prefix.endswith("/") and not router_prefix.startswith("/") and combined_prefix:
                                                combined_prefix += "/" + router_prefix
                                            else:
                                                combined_prefix += router_prefix
                                                
                                        final_path = combined_prefix
                                        if path:
                                            if final_path.endswith("/") and path.startswith("/"):
                                                final_path += path[1:]
                                            elif not final_path.endswith("/") and not path.startswith("/") and final_path:
                                                final_path += "/" + path
                                            else:
                                                final_path += path
                                                
                                        if not final_path.startswith("/"):
                                            final_path = "/" + final_path
                                        final_path = re.sub(r'/{2,}', '/', final_path)
                                        
                                        new_route_id = f"HTTP {method} {final_path}"
                                        
                                        # Redirect the edge
                                        edge.from_node = new_route_id
                                        if combined_prefix:
                                            edge.source = "INFERRED"
                                        else:
                                            edge.source = "SUPPORT_PACK"
                                        edge.properties["resolver_hook_name"] = rule_type
                                        edge.properties["support_pack_id"] = library
                                        
                                        # Ensure the ROUTE node exists
                                        if not any(n.id == new_route_id for n in graph.nodes):
                                            graph.add_node(Node(
                                                id=new_route_id,
                                                kind="ROUTE",
                                                name=new_route_id,
                                                properties={"library": library}
                                            ))

            elif rule_type == "fastapi_depends_resolver":
                # FastAPI Depends provider resolution hook
                for node in nodes_to_process:
                    if node.kind == "METHOD":
                        scope = node.properties.get("scope", "")
                        for key, value in node.properties.items():
                            if key.startswith("param_default:") and "Depends(" in value:
                                match_dep = re.search(r"Depends\(([^)]+)\)", value)
                                if match_dep:
                                    provider = match_dep.group(1).strip()
                                    current_module = module_for_scope(scope, graph)
                                    resolved_provider = resolve_class_name(provider, current_module, index) or f"{current_module}.{provider}"
                                    
                                    edge_id = f"support_pack_edge__{library}__depends__{scope}__{resolved_provider}"
                                    if not any(e.id == edge_id for e in graph.edges):
                                        file_loc, line_loc = node_file_and_line(node, graph)
                                        graph.add_edge(Edge(
                                            id=edge_id,
                                            kind="CALLS",
                                            from_node=scope,
                                            to_node=resolved_provider,
                                            source="INFERRED",
                                            confidence=float(emit.get("confidence", 0.85)),
                                            evidence=[Evidence(
                                                file=file_loc,
                                                line=line_loc,
                                                description=f"FastAPI dependency injection: {scope} handler Depends on provider {resolved_provider}"
                                            )],
                                            properties={
                                                "support_pack_library": library,
                                                "support_pack_id": library,
                                                "support_pack_version": version_range,
                                                "support_pack_rule_id": rule_id,
                                                "resolver_hook_name": rule_type
                                            }
                                        ))

            elif rule_type == "dependency_injector_resolver":
                # dependency-injector providers and container.order_service() resolution hook
                for node in nodes_to_process:
                    if node.kind == "ASSIGNMENT":
                        call_name = node.properties.get("call_name", "")
                        if call_name in {"providers.Singleton", "providers.Factory"}:
                            args = node.properties.get("args", [])
                            if args:
                                provided_class = args[0]
                                target = node.properties.get("target", "")
                                scope = node.properties.get("scope", "")
                                current_module = module_for_scope(scope, graph)
                                resolved_class = resolve_class_name(provided_class, current_module, index) or provided_class
                                container_attr = f"{scope}.{target}" if scope else target
                                
                                # 1. Link Container.attr -> Provided Class
                                edge_id_1 = f"support_pack_edge__{library}__di_binding__{container_attr}__{resolved_class}"
                                if not any(e.id == edge_id_1 for e in graph.edges):
                                    file_loc, line_loc = node_file_and_line(node, graph)
                                    graph.add_edge(Edge(
                                        id=edge_id_1,
                                        kind="DEPENDS_ON",
                                        from_node=container_attr,
                                        to_node=resolved_class,
                                        source="INFERRED",
                                        confidence=float(emit.get("confidence", 0.85)),
                                        evidence=[Evidence(
                                            file=file_loc,
                                            line=line_loc,
                                            description=f"Inferred DI binding: {container_attr} Singleton/Factory provides class {resolved_class}"
                                        )],
                                        properties={
                                            "support_pack_library": library,
                                            "support_pack_id": library,
                                            "support_pack_version": version_range,
                                            "support_pack_rule_id": rule_id,
                                            "resolver_hook_name": rule_type
                                        }
                                    ))
                                    
                                # 2. Link Provided Class -> Dependency Class (constructor Injection)
                                kw_args = node.properties.get("keyword_args", {})
                                for kw, val in kw_args.items():
                                    val_node = next((n for n in graph.nodes if n.kind == "ASSIGNMENT" and n.properties.get("scope") == scope and n.properties.get("target") == val), None)
                                    if val_node:
                                        val_call = val_node.properties.get("call_name", "")
                                        val_args = val_node.properties.get("args", [])
                                        if val_call in {"providers.Singleton", "providers.Factory"} and val_args:
                                            dep_class = resolve_class_name(val_args[0], current_module, index) or val_args[0]
                                            edge_id_2 = f"support_pack_edge__{library}__di_dep__{resolved_class}__{dep_class}"
                                            if not any(e.id == edge_id_2 for e in graph.edges):
                                                file_loc_2, line_loc_2 = node_file_and_line(node, graph)
                                                graph.add_edge(Edge(
                                                    id=edge_id_2,
                                                    kind="DEPENDS_ON",
                                                    from_node=resolved_class,
                                                    to_node=dep_class,
                                                    source="INFERRED",
                                                    confidence=float(emit.get("confidence", 0.80)),
                                                    evidence=[Evidence(
                                                        file=file_loc_2,
                                                        line=line_loc_2,
                                                        description=f"Inferred constructor dependency: {resolved_class} requires {dep_class} injected via {kw}"
                                                    )],
                                                    properties={
                                                        "support_pack_library": library,
                                                        "support_pack_id": library,
                                                        "support_pack_version": version_range,
                                                        "support_pack_rule_id": rule_id,
                                                        "resolver_hook_name": rule_type
                                                    }
                                                ))

                    # 3. Resolve container.order_service() calls to their provided constructor
                    elif node.kind == "CALL_EXPR":
                        call_name = node.properties.get("call_name", "")
                        scope = node.properties.get("scope", "")
                        # Look for calls matching container.attr(...) or self.container.attr(...)
                        if "." in call_name:
                            parts = call_name.split(".")
                            receiver = parts[-2]
                            method_name = parts[-1]
                            # Check if receiver could be a container and method_name is a known di provider
                            # Search the graph for class inheriting from container containing this di provider
                            for n in graph.nodes:
                                if n.kind == "ASSIGNMENT" and n.properties.get("target") == method_name:
                                    val_call = n.properties.get("call_name", "")
                                    val_args = n.properties.get("args", [])
                                    if val_call in {"providers.Singleton", "providers.Factory"} and val_args:
                                        target_class = resolve_class_name(val_args[0], module_for_scope(n.properties.get("scope", ""), graph), index) or val_args[0]
                                        
                                        edge_id_3 = f"support_pack_edge__{library}__di_call__{scope}__{target_class}"
                                        if not any(e.id == edge_id_3 for e in graph.edges):
                                            file_loc_3, line_loc_3 = node_file_and_line(node, graph)
                                            graph.add_edge(Edge(
                                                id=edge_id_3,
                                                kind="CALLS",
                                                from_node=scope,
                                                to_node=target_class,
                                                source="INFERRED",
                                                confidence=float(emit.get("confidence", 0.85)),
                                                evidence=[Evidence(
                                                    file=file_loc_3,
                                                    line=line_loc_3,
                                                    description=f"Inferred DI provider invocation: {call_name} resolves to constructor {target_class}"
                                                )],
                                                properties={
                                                    "support_pack_library": library,
                                                    "support_pack_id": library,
                                                    "support_pack_version": version_range,
                                                    "support_pack_rule_id": rule_id,
                                                    "resolver_hook_name": rule_type
                                                }
                                            ))

            elif rule_type == "react_resolver":
                # React Component, Hook and Fetch resolution hook
                # A. Identify Component and Hook declarations
                for node in nodes_to_process:
                    file_path = node.properties.get("file", "")
                    if any(file_path.endswith(ext) for ext in (".js", ".jsx", ".ts", ".tsx")):
                         if node.kind == "METHOD":
                             name = node.name
                             is_component = name and name[0].isupper()
                             is_hook = name and name.startswith("use") and len(name) > 3 and name[3].isupper()
                             if is_component or is_hook:
                                 node.properties["react_type"] = "component" if is_component else "hook"
                                 
                         # B. Identify hook calls and fetch calls
                         elif node.kind == "CALL_EXPR":
                             call_name = node.properties.get("call_name", "")
                             scope = node.properties.get("scope", "")
                             
                             # 1. Hook Call (Component -> Hook)
                             if call_name.startswith("use") and len(call_name) > 3 and call_name[3].isupper():
                                 edge_id = f"support_pack_edge__{library}__react_hook__{scope}__{call_name}"
                                 if not any(e.id == edge_id for e in graph.edges):
                                     file_loc, line_loc = node_file_and_line(node, graph)
                                     graph.add_edge(Edge(
                                         id=edge_id,
                                         kind="CALLS",
                                         from_node=scope,
                                         to_node=call_name,
                                         source="INFERRED",
                                         confidence=float(emit.get("confidence", 0.65)),
                                         evidence=[Evidence(
                                             file=file_loc,
                                             line=line_loc,
                                             description=f"React Hook invocation: {scope} calls Hook {call_name}"
                                         )],
                                         properties={
                                             "support_pack_library": library,
                                             "support_pack_id": library,
                                             "support_pack_version": version_range,
                                             "support_pack_rule_id": rule_id,
                                             "resolver_hook_name": rule_type
                                         }
                                     ))
                                     
                             # 2. HTTP Fetch Client call (Hook -> Endpoint)
                             elif call_name in {"fetch", "axios.get", "axios.post", "axios.put", "axios.delete", "axios.patch", "client.get", "client.post"}:
                                 args = node.properties.get("args", [])
                                 if args:
                                     path = args[0].strip("'\"")
                                     method = "GET"
                                     if call_name == "fetch" and len(args) > 1:
                                         opt_arg = args[1]
                                         meth_match = re.search(r"method\s*:\s*['\"](\w+)['\"]", opt_arg, re.IGNORECASE)
                                         if meth_match:
                                             method = meth_match.group(1).upper()
                                     elif "." in call_name:
                                         method = call_name.split(".")[1].upper()
                                         
                                     target_route = f"HTTP {method} {path}"
                                     
                                     # HONEST FE/BE Route matching: only connect if route actually exists!
                                     route_exists = any(n.id == target_route for n in graph.nodes if n.kind == "ROUTE")
                                     if route_exists:
                                         edge_id = f"support_pack_edge__{library}__react_fetch__{scope}__{target_route}"
                                         if not any(e.id == edge_id for e in graph.edges):
                                             file_loc, line_loc = node_file_and_line(node, graph)
                                             graph.add_edge(Edge(
                                                 id=edge_id,
                                                 kind="CALLS",
                                                 from_node=scope,
                                                 to_node=target_route,
                                                 source="INFERRED",
                                                 confidence=float(emit.get("confidence", 0.60)),
                                                 evidence=[Evidence(
                                                     file=file_loc,
                                                     line=line_loc,
                                                     description=f"React API client request: {scope} targets HTTP endpoint {target_route}"
                                                 )],
                                                 properties={
                                                     "support_pack_library": library,
                                                     "support_pack_id": library,
                                                     "support_pack_version": version_range,
                                                     "support_pack_rule_id": rule_id,
                                                     "resolver_hook_name": rule_type
                                                 }
                                             ))

                # C. Convert JS/TS local imports/calls to SUPPORT_PACK/INFERRED source
                for edge in list(graph.edges):
                    if edge.source == "EXTRACTED" and edge.kind == "CALLS":
                        from_node = next((n for n in graph.nodes if n.id == edge.from_node), None)
                        if from_node:
                            from_file = from_node.properties.get("file", "")
                            if any(from_file.endswith(ext) for ext in (".js", ".jsx", ".ts", ".tsx")):
                                if edge.to_node in {"fetch", "console", "console.log", "alert"}:
                                    continue
                                if not from_node.properties.get("react_type"):
                                    continue
                                edge.source = "INFERRED"
                                edge.confidence = 0.60
                                edge.properties["support_pack_library"] = library
                                edge.properties["support_pack_id"] = library
                                edge.properties["support_pack_version"] = version_range
                                edge.properties["support_pack_rule_id"] = "react_local_call"
                                edge.properties["resolver_hook_name"] = rule_type

            else:
                # Standard matcher rule engine (Stage 10 V1 compatibility)
                node_kind_pattern = match.get("node_kind")
                call_name_pattern = match.get("call_name")
                receiver_pattern = match.get("receiver")
                receiver_type_pattern = match.get("receiver_type")
                method_name_pattern = match.get("method_name")
                imported_library_pattern = match.get("imported_library")

                for node in nodes_to_process:
                    if node_kind_pattern and node.kind != node_kind_pattern:
                        continue
                    if call_name_pattern and node.properties.get("call_name") != call_name_pattern:
                        continue
                    if receiver_pattern and node.properties.get("receiver") != receiver_pattern:
                        continue
                    if receiver_type_pattern and node.properties.get("receiver_type") != receiver_type_pattern:
                        continue
                    if method_name_pattern and node.properties.get("method_name") != method_name_pattern:
                        continue
                    if imported_library_pattern:
                        mod = get_node_module(node)
                        imports = imports_map.get(mod, set())
                        if imported_library_pattern not in imports:
                            continue

                    from_node = node.properties.get("scope") or node.id
                    to_node = emit.get("to")
                    kind = emit.get("kind")
                    source = emit.get("source", "SUPPORT_PACK")
                    
                    if source == "AI_PROPOSED":
                        continue

                    confidence = emit.get("confidence", 0.8)
                    description = emit.get("description", "Dependency resolved from support pack")
                    edge_id = f"support_pack::{library}::{rule_id}::{from_node}::{to_node}::{kind}"

                    if any(e.id == edge_id for e in graph.edges):
                        continue

                    try:
                        file_loc, line_loc = node_file_and_line(node, graph)
                        new_edge = Edge(
                            id=edge_id,
                            kind=kind,
                            from_node=from_node,
                            to_node=to_node,
                            source="SUPPORT_PACK",
                            confidence=float(confidence),
                            evidence=[Evidence(
                                file=file_loc,
                                line=line_loc,
                                description=description
                            )],
                            properties={
                                "support_pack_library": library,
                                "support_pack_id": library,
                                "support_pack_version": version_range,
                                "support_pack_rule_id": rule_id
                            }
                        )
                        graph.add_edge(new_edge)
                    except Exception:
                        pass

        if invalid_rules:
            meta_key = f"support_pack_validation_errors::{library}"
            graph.metadata[meta_key] = invalid_rules

        for edge in graph.edges:
            if edge.properties.get("support_pack_library") == library or (
                edge.id not in edge_ids_before_pack
                and (edge.id.startswith(f"support_pack_edge__{library}") or edge.id.startswith(f"support_pack::{library}::"))
            ):
                rule = rule_lookup.get(str(edge.properties.get("support_pack_rule_id", "")))
                _annotate_support_pack_edge(edge, pack, library, version_range, rule)

    # A framework rule must never emit an edge without a concrete caller and
    # target. Such edges are not useful hypotheses: they also make serialized
    # GraphDocuments invalid and previously surfaced during incremental reuse.
    invalid_support_edges = [
        edge for edge in graph.edges
        if edge.source == "SUPPORT_PACK"
        and (not edge.from_node.strip() or not edge.to_node.strip())
    ]
    if invalid_support_edges:
        graph.edges = [edge for edge in graph.edges if edge not in invalid_support_edges]
        graph._rebuild_edge_indexes()
        graph.metadata.setdefault("support_pack_invalid_edges", []).extend(
            {
                "edge_id": edge.id,
                "reason": "missing_endpoint",
                "from": edge.from_node,
                "to": edge.to_node,
            }
            for edge in invalid_support_edges
        )

    candidate_groups: dict[tuple[str, str, str], list[Edge]] = {}
    for edge in graph.edges:
        if edge.source != "SUPPORT_PACK":
            continue
        props = edge.properties or {}
        key = (edge.kind, edge.from_node)
        candidate_groups.setdefault(key, []).append(edge)
    for candidates in candidate_groups.values():
        targets = {edge.to_node for edge in candidates}
        if len(targets) < 2:
            continue
        for edge in candidates:
            edge.properties["status"] = "ambiguous"
            edge.properties["resolution_status"] = "ambiguous"
            edge.properties["candidate_count"] = len(targets)
            edge.properties["quality_guard"] = "support_pack_candidate_conflict"
            edge.confidence = min(edge.confidence, 0.55)

    return graph
