"""Resolution orchestrator engine. Stage 14."""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

from impact_engine.models import GraphDocument, Node, Edge, Evidence
from impact_engine.resolution.symbol_index import build_symbol_index
from impact_engine.resolution.helpers import (
    resolve_class_name,
    get_node_location,
    module_for_scope
)
from impact_engine.nested_object_graph import apply_nested_object_graph_resolution
from impact_engine.support_packs.rule_engine import apply_support_pack_rule_engine


@dataclass
class ResolutionContext:
    variable_types: Dict[Tuple[str, str], str] = field(default_factory=dict)
    field_types: Dict[Tuple[str, str], str] = field(default_factory=dict)
    parameter_types: Dict[Tuple[str, str], str] = field(default_factory=dict)
    evidences: Dict[Tuple, List[Evidence]] = field(default_factory=dict)
    ambiguous_variables: Dict[Tuple[str, str], List[str]] = field(default_factory=dict)


def _edge_exists(graph: GraphDocument, edge_id: str) -> bool:
    """Use the graph's O(1) id index during high-volume resolution passes."""
    graph._ensure_indexes()
    return edge_id in graph._edge_id_index


def _add_exact_function_call(graph: GraphDocument, call: Node, target: str) -> None:
    scope = str(call.properties.get("scope") or "")
    if not scope or not target:
        return
    edge_id = f"exact_calls__{scope}__{target}"
    if _edge_exists(graph, edge_id):
        return
    file_path, line_no = get_node_location(call.id, graph)
    graph.add_edge(Edge(
        id=edge_id,
        kind="CALLS",
        from_node=scope,
        to_node=target,
        source="EXTRACTED",
        confidence=1.0,
        evidence=[Evidence(
            description=f"Exact function symbol resolution: {call.properties.get('call_name')} -> {target}",
            file=file_path,
            line=line_no,
            source="EXTRACTED",
        )],
        properties={
            "resolution_status": "resolved_exact",
            "evidence_class": "static_proven",
            "validation_status": "not_validated",
            "resolver_rule": "python.function_symbol",
        },
    ))
    graph.add_edge(Edge(
        id=f"exact_resolves_to__{call.id}__method:{target}",
        kind="RESOLVES_TO",
        from_node=call.id,
        to_node=f"method:{target}",
        source="EXTRACTED",
        confidence=1.0,
        evidence=[Evidence(
            description=f"Exact callsite target: {call.properties.get('call_name')} -> {target}",
            file=file_path,
            line=line_no,
            source="EXTRACTED",
        )],
        properties={"resolution_status": "resolved_exact", "evidence_class": "static_proven", "validation_status": "not_validated"},
    ))


def resolve_receiver_type(receiver: str, scope: str, context: ResolutionContext, graph: GraphDocument, index) -> Optional[str]:
    # 1. If receiver is "self"
    if receiver == "self":
        if "." in scope:
            parts = scope.split(".")
            return ".".join(parts[:-1])
        return None
        
    # 2. If receiver is a self field (e.g. "self.repository")
    if receiver.startswith("self.") and "." in scope:
        parts = scope.split(".")
        class_name = ".".join(parts[:-1])
        t = context.field_types.get((class_name, receiver))
        if t:
            if (class_name, receiver) in context.ambiguous_variables or (f"{class_name}.__init__", receiver) in context.ambiguous_variables:
                return None
            return t
        init_scope = f"{class_name}.__init__"
        t = context.variable_types.get((init_scope, receiver))
        if t:
            if (init_scope, receiver) in context.ambiguous_variables:
                return None
            return t
            
    # 3. If receiver is a simple variable/name in the current scope
    t = context.variable_types.get((scope, receiver))
    if t:
        return t
        
    # 4. If receiver is a module-level variable (scope is method/function/module)
    current_module = module_for_scope(scope, graph)
    t = context.variable_types.get((current_module, receiver))
    if t:
        return t
        
    # 5. If receiver is a nested attribute (e.g. "container.service")
    if "." in receiver:
        parts = receiver.split(".")
        base = parts[0]
        base_type = resolve_receiver_type(base, scope, context, graph, index)
        if base_type:
            curr_type = base_type
            for prop in parts[1:]:
                prop_key = f"self.{prop}"
                t_prop = context.field_types.get((curr_type, prop_key))
                if not t_prop:
                    init_scope = f"{curr_type}.__init__"
                    t_prop = context.variable_types.get((init_scope, prop_key))
                if not t_prop:
                    t_prop = context.variable_types.get((curr_type, prop))
                if t_prop:
                    curr_type = t_prop
                else:
                    return None
            return curr_type

    return None


def resolve_graph(graph: GraphDocument, support_packs: list | None = None) -> GraphDocument:
    index = build_symbol_index(graph)
    graph.metadata["precision_resolver"] = "active"

    # Extraction of current facts from nodes
    assignments = [n for n in graph.nodes if n.kind == "ASSIGNMENT"]
    calls = [n for n in graph.nodes if n.kind == "CALL_EXPR"]

    context = ResolutionContext()

    # Seed typed function/method parameters from extractor annotations. This lets
    # resolver handle framework-injected parameters such as FastAPI Depends.
    for node in graph.nodes:
        if node.kind != "METHOD":
            continue
        scope = node.properties.get("scope")
        if not scope:
            continue
        for key, value in node.properties.items():
            if not key.startswith("param_type:"):
                continue
            param_name = key.split(":", 1)[1]
            canonical_type = index.canonicalize_class_name(value) or value
            param_key = (scope, param_name)
            if param_key not in context.parameter_types:
                context.parameter_types[param_key] = canonical_type
            if param_key not in context.variable_types:
                context.variable_types[param_key] = canonical_type
                file_path = node.properties.get("file")
                line_no = node.properties.get("line")
                context.evidences[param_key] = [
                    Evidence(
                        description=f"Parameter annotation: {param_name}: {value} in {scope}",
                        file=file_path,
                        line=line_no,
                        source="INFERRED",
                    )
                ]

    # Multi-pass fixpoint inference
    for _ in range(5):
        # Resolve local/imported top-level functions only through exact symbols.
        # There is deliberately no method-name similarity fallback.
        for call in calls:
            if call.properties.get("receiver") or call.properties.get("method_name"):
                continue
            scope = str(call.properties.get("scope") or "")
            call_name = str(call.properties.get("call_name") or "")
            if scope and call_name and "." not in call_name:
                target = index.resolve_function_name(call_name, module_for_scope(scope, graph), scope.rsplit(".", 1)[0])
                if target:
                    _add_exact_function_call(graph, call, target)

        # Pass 1: Direct instantiation assignments (e.g., self.order_repository = OrderRepository())
        for assign in assignments:
            scope = assign.properties.get("scope")
            target = assign.properties.get("target")
            call_name = assign.properties.get("call_name")
            if call_name and scope and target:
                current_module = module_for_scope(scope, graph)
                resolved_type = resolve_class_name(call_name, current_module, index)
                if resolved_type:
                    key = (scope, target)
                    existing_type = context.variable_types.get(key)
                    if existing_type and existing_type != resolved_type:
                        candidates = context.ambiguous_variables.setdefault(key, [existing_type])
                        if resolved_type not in candidates:
                            candidates.append(resolved_type)
                        continue
                    if key not in context.variable_types:
                        context.variable_types[key] = resolved_type
                        file_path, line_no = get_node_location(assign.id, graph)
                        evidence = Evidence(
                            description=f"Direct constructor assignment: {target} = {call_name}()",
                            file=file_path,
                            line=line_no,
                            source="INFERRED"
                        )
                        context.evidences[key] = [evidence]
                        
                        # Add INSTANCE_OF edge explaining this resolution
                        edge_id = f"inferred_instance_of__{assign.id}__class:{resolved_type}"
                        if not _edge_exists(graph, edge_id):
                            graph.add_edge(Edge(
                                id=edge_id,
                                kind="INSTANCE_OF",
                                from_node=assign.id,
                                to_node=f"class:{resolved_type}",
                                source="INFERRED",
                                confidence=0.95,
                                evidence=[evidence]
                            ))

        # Pass 1b: Factory/provider return propagation from exact return annotations.
        for assign in assignments:
            scope = str(assign.properties.get("scope") or "")
            target = str(assign.properties.get("target") or "")
            call_name = str(assign.properties.get("call_name") or "")
            if not scope or not target or not call_name or (scope, target) in context.variable_types:
                continue
            function_target = index.resolve_function_name(call_name, module_for_scope(scope, graph), scope.rsplit(".", 1)[0])
            return_type = index.function_return_types.get(function_target or "")
            if not return_type:
                continue
            resolved_return_type = index.canonicalize_class_name(return_type) or return_type
            context.variable_types[(scope, target)] = resolved_return_type
            file_path, line_no = get_node_location(assign.id, graph)
            context.evidences[(scope, target)] = [Evidence(
                description=f"Factory return propagation: {call_name}() -> {resolved_return_type}",
                file=file_path,
                line=line_no,
                source="INFERRED",
            )]

        # Pass 2: Constructor argument binding
        for assign in assignments:
            scope = assign.properties.get("scope")
            target = assign.properties.get("target")
            call_name = assign.properties.get("call_name")
            keyword_args = assign.properties.get("keyword_args", {})
            positional_args = assign.properties.get("args", [])
            if call_name and scope:
                # Rewrite dependency injector Factory/Singleton calls to match their target class
                if call_name in {"providers.Factory", "providers.Singleton"} and positional_args:
                    call_name = positional_args[0]
                    positional_args = positional_args[1:]
                    
                current_module = module_for_scope(scope, graph)
                resolved_target_type = resolve_class_name(call_name, current_module, index)
                if resolved_target_type:
                    constructor_scope = f"{resolved_target_type}.__init__"
                    constructor_node = next(
                        (
                            n
                            for n in graph.nodes
                            if n.kind == "METHOD"
                            and n.properties.get("scope") == constructor_scope
                        ),
                        None,
                    )
                    param_order = []
                    if constructor_node:
                        raw_param_order = constructor_node.properties.get("param_order", [])
                        if isinstance(raw_param_order, list):
                            param_order = raw_param_order
                    arg_bindings = {}
                    arg_bindings.update(keyword_args or {})
                    for index_pos, arg_val in enumerate(positional_args or []):
                        if index_pos < len(param_order):
                            arg_bindings[param_order[index_pos]] = arg_val

                    if not arg_bindings:
                        continue

                    for param_name, arg_val in arg_bindings.items():
                        arg_type = context.variable_types.get((scope, arg_val))
                        if not arg_type:
                            arg_type = resolve_receiver_type(arg_val, scope, context, graph, index)
                        if arg_type:
                            param_key = (constructor_scope, param_name)
                            if param_key not in context.parameter_types:
                                context.parameter_types[param_key] = arg_type
                                prev_evidence = context.evidences.get((scope, arg_val), [])
                                file_path, line_no = get_node_location(assign.id, graph)
                                evidence = Evidence(
                                    description=f"Constructor keyword binding: {call_name}({param_name}={arg_val}) in {scope}",
                                    file=file_path,
                                    line=line_no,
                                    source="INFERRED"
                                )
                                context.evidences[param_key] = prev_evidence + [evidence]
                                
                                # Add PARAM_BINDS_TO edge
                                edge_id = f"inferred_param_binds__{assign.id}__class:{arg_type}"
                                if not _edge_exists(graph, edge_id):
                                    graph.add_edge(Edge(
                                        id=edge_id,
                                        kind="PARAM_BINDS_TO",
                                        from_node=assign.id,
                                        to_node=f"class:{arg_type}",
                                        source="INFERRED",
                                        confidence=0.90,
                                        evidence=context.evidences[param_key]
                                    ))

        # Pass 3: Parameter-to-field propagation (e.g., self.repository = repository in services.OrderService.__init__)
        for assign in assignments:
            scope = assign.properties.get("scope")
            target = assign.properties.get("target")
            value = assign.properties.get("value")
            if scope and target and value and target.startswith("self.") and "." in scope:
                parts = scope.split(".")
                class_name = ".".join(parts[:-1])
                
                # Case A: Parameter-to-field
                param_key = (scope, value)
                param_type = context.parameter_types.get(param_key)
                if param_type:
                    field_key = (class_name, target)
                    if field_key not in context.field_types:
                        context.field_types[field_key] = param_type
                        prev_evidence = context.evidences.get(param_key, [])
                        file_path, line_no = get_node_location(assign.id, graph)
                        evidence = Evidence(
                            description=f"Parameter-to-field propagation: {target} = {value} in {scope}",
                            file=file_path,
                            line=line_no,
                            source="INFERRED"
                        )
                        context.evidences[field_key] = prev_evidence + [evidence]
                        
                        # Add FIELD_BINDS_TO edge
                        edge_id = f"inferred_field_binds__{assign.id}__class:{param_type}"
                        if not _edge_exists(graph, edge_id):
                            graph.add_edge(Edge(
                                id=edge_id,
                                kind="FIELD_BINDS_TO",
                                from_node=assign.id,
                                to_node=f"class:{param_type}",
                                source="INFERRED",
                                confidence=0.90,
                                evidence=context.evidences[field_key]
                            ))
                
                # Case B: Field-to-field alias propagation (e.g., self.repo = self.repository)
                elif value.startswith("self."):
                    source_field_key = (class_name, value)
                    source_type = context.field_types.get(source_field_key)
                    if source_type:
                        field_key = (class_name, target)
                        if field_key not in context.field_types:
                            context.field_types[field_key] = source_type
                            prev_evidence = context.evidences.get(source_field_key, [])
                            file_path, line_no = get_node_location(assign.id, graph)
                            evidence = Evidence(
                                description=f"Field-to-field alias propagation: {target} = {value} in {scope}",
                                file=file_path,
                                line=line_no,
                                source="INFERRED"
                            )
                            context.evidences[field_key] = prev_evidence + [evidence]
                            
                            # Add FIELD_BINDS_TO edge
                            edge_id = f"inferred_field_binds_alias__{assign.id}__class:{source_type}"
                            if not _edge_exists(graph, edge_id):
                                graph.add_edge(Edge(
                                    id=edge_id,
                                    kind="FIELD_BINDS_TO",
                                    from_node=assign.id,
                                    to_node=f"class:{source_type}",
                                    source="INFERRED",
                                    confidence=0.90,
                                    evidence=context.evidences[field_key]
                                ))

        # Pass 4: Call resolution (e.g., self.repository.save(order))
        for call in calls:
            scope = call.properties.get("scope")
            receiver = call.properties.get("receiver")
            method_name = call.properties.get("method_name")
            if scope and receiver and method_name:
                module_target = index.resolve_module_member(
                    str(receiver), str(method_name), module_for_scope(scope, graph)
                )
                if module_target:
                    _add_exact_function_call(graph, call, module_target)
                    continue
                receiver_type = resolve_receiver_type(receiver, scope, context, graph, index)
                if not receiver_type and str(receiver) == "super()" and "." in str(scope):
                    receiver_type = str(scope).rsplit(".", 1)[0]
                confidence = 0.85 if receiver != "self" else 0.90
                description_prefix = f"Receiver method resolution: {receiver}.{method_name}(...) in {scope}"

                candidate_types: list[str] = []
                if receiver.startswith("self.") and "." in scope:
                    owner = ".".join(scope.split(".")[:-1])
                    candidate_types = context.ambiguous_variables.get((f"{owner}.__init__", receiver), [])
                    if not candidate_types:
                        candidate_types = context.ambiguous_variables.get((f"{owner}.{method_name}", receiver), [])
                if not receiver_type and candidate_types:
                    file_path, line_no = get_node_location(call.id, graph)
                    for candidate in candidate_types:
                        target_symbol = f"{candidate}.{method_name}"
                        graph.add_edge(Edge(
                            id=f"ambiguous_calls__{scope}__{target_symbol}",
                            kind="CALLS",
                            from_node=scope,
                            to_node=target_symbol,
                            source="INFERRED",
                            confidence=0.55,
                            evidence=[Evidence(description=description_prefix, file=file_path, line=line_no, source="INFERRED")],
                            properties={
                                "resolution_status": "ambiguous",
                                "evidence_class": "static_inferred",
                                "validation_status": "not_validated",
                                "candidate_targets": [f"{item}.{method_name}" for item in candidate_types],
                            },
                        ))
                    continue
                
                if receiver_type:
                    call.properties["receiver_type"] = receiver_type
                    from_node_symbol = scope
                    to_node_symbol = index.resolve_method_target(receiver_type, str(method_name)) or f"{receiver_type}.{method_name}"

                    if str(receiver) == "super()" and "." in str(scope):
                        owner = str(scope).rsplit(".", 1)[0]
                        inherited = index.bases_by_class.get(owner, [])
                        if inherited:
                            inherited_target = index.resolve_method_target(inherited[0], str(method_name))
                            if inherited_target:
                                to_node_symbol = inherited_target
                    
                    edge_id = f"inferred_calls__{from_node_symbol}__{to_node_symbol}"
                    if not _edge_exists(graph, edge_id):
                        if receiver == "self":
                            chain_evidence = []
                        else:
                            parts = receiver.split(".")
                            base = parts[0]
                            if receiver.startswith("self.") and "." in scope:
                                parts_scope = scope.split(".")
                                class_name = ".".join(parts_scope[:-1])
                                chain_evidence = context.evidences.get((class_name, receiver), [])
                            else:
                                chain_evidence = context.evidences.get((scope, base), [])
                                if not chain_evidence:
                                    current_module = module_for_scope(scope, graph)
                                    chain_evidence = context.evidences.get((current_module, base), [])
                                    
                        file_path, line_no = get_node_location(call.id, graph)
                        final_evidence = chain_evidence + [
                            Evidence(
                                description=description_prefix,
                                file=file_path,
                                line=line_no,
                                source="INFERRED"
                            )
                        ]
                        
                        # Add semantic CALLS edge
                        graph.add_edge(Edge(
                            id=edge_id,
                            kind="CALLS",
                            from_node=from_node_symbol,
                            to_node=to_node_symbol,
                            source="INFERRED",
                            confidence=confidence,
                            evidence=final_evidence
                        ))
                        
                        # Add structural RESOLVES_TO edge
                        struct_edge_id = f"inferred_resolves_to__{call.id}__method:{to_node_symbol}"
                        if not _edge_exists(graph, struct_edge_id):
                            graph.add_edge(Edge(
                                id=struct_edge_id,
                                kind="RESOLVES_TO",
                                from_node=call.id,
                                to_node=f"method:{to_node_symbol}",
                                source="INFERRED",
                                confidence=confidence,
                                evidence=final_evidence
                            ))

    # Pass 5: Test-to-Route targeting resolution
    for call in calls:
        scope = call.properties.get("scope", "")
        call_name = call.properties.get("call_name", "")
        args = call.properties.get("args", [])
        
        # Check if call is client.post("/orders"), etc.
        if scope and ("test_" in scope or "test" in scope.lower()) and "." in call_name and args:
            parts = call_name.split(".")
            receiver = parts[0]
            method = parts[1].lower()
            if receiver == "client" and method in ("get", "post", "put", "delete", "patch", "options", "head"):
                path_arg = args[0]
                # Strip quotes
                path = path_arg.strip("'\"")
                route_id = f"HTTP {method.upper()} {path}"
                
                # Add route node if not exists
                if not any(n.id == route_id for n in graph.nodes):
                    graph.add_node(Node(
                        id=route_id,
                        name=route_id,
                        kind="ROUTE",
                        properties={"inferred_from_test": True}
                    ))
                    
                edge_id = f"inferred_test_route_edge__{scope}__{route_id}"
                if not _edge_exists(graph, edge_id):
                    file_path, line_no = get_node_location(call.id, graph)
                    graph.add_edge(Edge(
                        id=edge_id,
                        kind="TESTS",
                        from_node=f"method:{scope}",
                        to_node=route_id,
                        source="INFERRED",
                        confidence=0.75,
                        evidence=[Evidence(
                            description=f"Test targeting HTTP route via {call_name}({path_arg})",
                            file=file_path,
                            line=line_no,
                            source="INFERRED"
                        )]
                    ))

    graph = apply_nested_object_graph_resolution(graph)
    return apply_support_pack_rule_engine(graph, support_packs or [])
