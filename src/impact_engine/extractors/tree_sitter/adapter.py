"""Tree-sitter Extractor Adapter. Stage 13."""
import os
import re
from pathlib import Path
from typing import List, Set, Optional
from impact_engine.models import GraphDocument, Node, Edge, Evidence

# Safe tree-sitter imports to support graceful degradation
try:
    import tree_sitter
    import tree_sitter_language_pack
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False


def is_tree_sitter_available() -> bool:
    if not HAS_TREE_SITTER:
        return False
    try:
        # Actually verify that tree_sitter_language_pack can load languages
        _ = tree_sitter_language_pack.get_language("javascript")
        return True
    except Exception:
        return False


def get_supported_tree_sitter_languages() -> List[str]:
    if not is_tree_sitter_available():
        return []
    return ["javascript", "typescript", "go", "java"]


def get_node_text(node) -> str:
    if not node:
        return ""
    return node.text.decode("utf-8") if isinstance(node.text, bytes) else str(node.text)


def collect_decorators(node) -> List[str]:
    decs = []
    for c in node.children:
        if c.type == "decorator":
            decs.append(get_node_text(c).strip())
        elif c.type == "modifiers":
            for gc in c.children:
                if gc.type in ("annotation", "marker_annotation"):
                    decs.append(get_node_text(gc).strip())
    return decs


def find_java_package(root_node) -> str:
    for child in root_node.children:
        if child.type == "package_declaration":
            for c in child.children:
                if c.type in ("scoped_identifier", "identifier"):
                    return get_node_text(c).strip()
    return ""


def find_go_package(root_node) -> str:
    for child in root_node.children:
        if child.type == "package_clause":
            for c in child.children:
                if c.type == "package_identifier":
                    return get_node_text(c).strip()
    return "main"


def walk_js_ts(node, file_path, rel_path, graph, scope="", imports=None):
    if imports is None:
        imports = set()
    node_type = node.type
    
    # 1. Imports
    if node_type == "import_statement":
        source_node = None
        for child in node.children:
            if child.type == "string":
                source_node = child
                break
        if source_node:
            src_val = get_node_text(source_node).strip('"\'')
            imports.add(src_val)
            
    # 2. Class
    elif node_type == "class_declaration":
        name_node = None
        for child in node.children:
            if child.type in ("identifier", "type_identifier"):
                name_node = child
                break
        if name_node:
            class_name = get_node_text(name_node)
            class_id = f"{scope}.{class_name}" if scope else class_name
            decs = collect_decorators(node)
            graph.add_node(Node(
                id=class_id,
                kind="CLASS",
                name=class_name,
                properties={"file": rel_path, "line": node.start_point[0] + 1, "decorators": decs, "scope": class_id}
            ))
            for child in node.children:
                walk_js_ts(child, file_path, rel_path, graph, scope=class_id, imports=imports)
            return

    # 3. Functions
    elif node_type in ("function_declaration", "generator_function_declaration"):
        name_node = None
        for child in node.children:
            if child.type == "identifier":
                name_node = child
                break
        if name_node:
            func_name = get_node_text(name_node)
            func_id = f"{scope}.{func_name}" if scope else func_name
            decs = collect_decorators(node)
            graph.add_node(Node(
                id=func_id,
                kind="METHOD",
                name=func_name,
                properties={"file": rel_path, "line": node.start_point[0] + 1, "decorators": decs, "scope": func_id}
            ))
            for child in node.children:
                walk_js_ts(child, file_path, rel_path, graph, scope=func_id, imports=imports)
            return

    # 4. Methods
    elif node_type == "method_definition":
        name_node = None
        for child in node.children:
            if child.type in ("property_identifier", "private_property_identifier"):
                name_node = child
                break
        if name_node:
            method_name = get_node_text(name_node)
            method_id = f"{scope}.{method_name}" if scope else method_name
            decs = collect_decorators(node)
            graph.add_node(Node(
                id=method_id,
                kind="METHOD",
                name=method_name,
                properties={"file": rel_path, "line": node.start_point[0] + 1, "decorators": decs, "scope": method_id}
            ))
            for child in node.children:
                walk_js_ts(child, file_path, rel_path, graph, scope=method_id, imports=imports)
            return

    # 5. Calls
    elif node_type == "call_expression":
        func_child = None
        for child in node.children:
            func_child = child
            break
            
        if func_child:
            line_no = node.start_point[0] + 1
            col_no = node.start_point[1]
            call_id = f"call_expr:{rel_path}:{line_no}:{col_no}"
            
            call_name = ""
            receiver = ""
            method_name = ""
            
            if func_child.type == "identifier":
                call_name = get_node_text(func_child)
            elif func_child.type == "member_expression":
                obj_node = func_child.child_by_field_name("object")
                prop_node = func_child.child_by_field_name("property")
                if obj_node and prop_node:
                    receiver = get_node_text(obj_node)
                    method_name = get_node_text(prop_node)
                    call_name = f"{receiver}.{method_name}"
            
            # Extract arguments
            args = []
            arguments_node = None
            for child in node.children:
                if child.type == "arguments":
                    arguments_node = child
                    break
            if arguments_node:
                for arg_child in arguments_node.children:
                    if arg_child.type not in ("(", ")", ","):
                        args.append(get_node_text(arg_child).strip())
                        
            if call_name:
                graph.add_node(Node(
                    id=call_id,
                    kind="CALL_EXPR",
                    name=call_name,
                    properties={
                        "file": rel_path,
                        "line": line_no,
                        "scope": scope,
                        "call_name": call_name,
                        "receiver": receiver,
                        "method_name": method_name,
                        "args": args
                    }
                ))
                
                if scope:
                    edge_id = f"ts_static_call__{scope}__{call_name}__{line_no}"
                    graph.add_edge(Edge(
                        id=edge_id,
                        kind="CALLS",
                        from_node=scope,
                        to_node=call_name,
                        source="EXTRACTED",
                        confidence=0.60,
                        evidence=[Evidence(
                            file=rel_path,
                            line=line_no,
                            description=f"Static tree-sitter call: {call_name}"
                        )],
                        properties={"extractor_id": "tree_sitter"}
                    ))

    for child in node.children:
        walk_js_ts(child, file_path, rel_path, graph, scope=scope, imports=imports)


def walk_go(node, file_path, rel_path, graph, scope="", imports=None, package_name="main"):
    if imports is None:
        imports = set()
    node_type = node.type
    
    if node_type == "import_spec":
        path_node = None
        for child in node.children:
            if child.type == "interpreted_string_literal":
                path_node = child
                break
        if path_node:
            imports.add(get_node_text(path_node).strip('"'))
            
    elif node_type == "function_declaration":
        name_node = None
        for child in node.children:
            if child.type == "identifier":
                name_node = child
                break
        if name_node:
            func_name = get_node_text(name_node)
            func_id = f"{package_name}.{func_name}" if package_name else func_name
            graph.add_node(Node(
                id=func_id,
                kind="METHOD",
                name=func_name,
                properties={"file": rel_path, "line": node.start_point[0] + 1}
            ))
            for child in node.children:
                walk_go(child, file_path, rel_path, graph, scope=func_id, imports=imports, package_name=package_name)
            return

    elif node_type == "method_declaration":
        receiver_type = ""
        method_name = ""
        
        name_node = None
        receiver_node = None
        for child in node.children:
            if child.type == "field_identifier":
                name_node = child
            elif child.type == "parameter_list" and receiver_node is None:
                receiver_node = child
                
        if name_node:
            method_name = get_node_text(name_node)
            
        if receiver_node:
            for param in receiver_node.children:
                if param.type == "parameter_declaration":
                    type_node = None
                    for c in param.children:
                        if c.type in ("pointer_type", "type_identifier"):
                            type_node = c
                            break
                    if type_node:
                        receiver_type = get_node_text(type_node).replace("*", "").strip()
                        
        if method_name:
            receiver_str = receiver_type if receiver_type else "Receiver"
            func_id = f"{package_name}.{receiver_str}.{method_name}" if package_name else f"{receiver_str}.{method_name}"
            graph.add_node(Node(
                id=func_id,
                kind="METHOD",
                name=method_name,
                properties={"file": rel_path, "line": node.start_point[0] + 1}
            ))
            for child in node.children:
                walk_go(child, file_path, rel_path, graph, scope=func_id, imports=imports, package_name=package_name)
            return

    elif node_type == "call_expression":
        func_child = None
        for child in node.children:
            func_child = child
            break
            
        if func_child:
            line_no = node.start_point[0] + 1
            col_no = node.start_point[1]
            call_id = f"call_expr:{rel_path}:{line_no}:{col_no}"
            
            call_name = ""
            receiver = ""
            method_name = ""
            
            if func_child.type == "identifier":
                call_name = get_node_text(func_child)
            elif func_child.type == "selector_expression":
                obj_node = func_child.child_by_field_name("operand")
                field_node = func_child.child_by_field_name("field")
                if obj_node and field_node:
                    receiver = get_node_text(obj_node)
                    method_name = get_node_text(field_node)
                    call_name = f"{receiver}.{method_name}"
                    
            if call_name:
                graph.add_node(Node(
                    id=call_id,
                    kind="CALL_EXPR",
                    name=call_name,
                    properties={
                        "file": rel_path,
                        "line": line_no,
                        "scope": scope,
                        "call_name": call_name,
                        "receiver": receiver,
                        "method_name": method_name
                    }
                ))
                
                if scope:
                    edge_id = f"ts_static_call__{scope}__{call_name}__{line_no}"
                    graph.add_edge(Edge(
                        id=edge_id,
                        kind="CALLS",
                        from_node=scope,
                        to_node=call_name,
                        source="EXTRACTED",
                        confidence=0.60,
                        evidence=[Evidence(
                            file=rel_path,
                            line=line_no,
                            description=f"Static Go call: {call_name}"
                        )],
                        properties={"extractor_id": "tree_sitter"}
                    ))

    for child in node.children:
        walk_go(child, file_path, rel_path, graph, scope=scope, imports=imports, package_name=package_name)


def walk_java(node, file_path, rel_path, graph, scope="", imports=None, package_name=""):
    if imports is None:
        imports = set()
    node_type = node.type
    if node_type == "import_declaration":
        for child in node.children:
            if child.type in ("scoped_identifier", "identifier"):
                imports.add(get_node_text(child))
                break

    if node_type == "class_declaration":
        name_node = None
        for child in node.children:
            if child.type == "identifier":
                name_node = child
                break
        if name_node:
            class_name = get_node_text(name_node)
            class_id = f"{package_name}.{class_name}" if package_name else class_name
            decs = collect_decorators(node)
            graph.add_node(Node(
                id=class_id,
                kind="CLASS",
                name=class_name,
                properties={"file": rel_path, "line": node.start_point[0] + 1, "decorators": decs}
            ))
            for child in node.children:
                walk_java(child, file_path, rel_path, graph, scope=class_id, imports=imports, package_name=package_name)
            return

    elif node_type == "method_declaration":
        name_node = None
        for child in node.children:
            if child.type == "identifier":
                name_node = child
                break
        if name_node:
            method_name = get_node_text(name_node)
            method_id = f"{scope}.{method_name}" if scope else method_name
            decs = collect_decorators(node)
            graph.add_node(Node(
                id=method_id,
                kind="METHOD",
                name=method_name,
                properties={"file": rel_path, "line": node.start_point[0] + 1, "decorators": decs}
            ))
            for child in node.children:
                walk_java(child, file_path, rel_path, graph, scope=method_id, imports=imports, package_name=package_name)
            return

    elif node_type == "method_invocation":
        receiver = ""
        method_name = ""
        
        object_node = node.child_by_field_name("object")
        name_node = node.child_by_field_name("name")

        if name_node:
            method_name = get_node_text(name_node)
        if object_node:
            receiver = get_node_text(object_node)

        call_name = f"{receiver}.{method_name}" if receiver else method_name
        
        if call_name:
            line_no = node.start_point[0] + 1
            col_no = node.start_point[1]
            call_id = f"call_expr:{rel_path}:{line_no}:{col_no}"
            
            graph.add_node(Node(
                id=call_id,
                kind="CALL_EXPR",
                name=call_name,
                properties={
                    "file": rel_path,
                    "line": line_no,
                    "scope": scope,
                    "call_name": call_name,
                    "receiver": receiver,
                    "method_name": method_name
                }
            ))
            
            if scope:
                edge_id = f"ts_static_call__{scope}__{call_name}__{line_no}"
                graph.add_edge(Edge(
                    id=edge_id,
                    kind="CALLS",
                    from_node=scope,
                    to_node=call_name,
                    source="EXTRACTED",
                    confidence=0.60,
                    evidence=[Evidence(
                        file=rel_path,
                        line=line_no,
                        description=f"Static Java call: {call_name}"
                    )],
                    properties={"extractor_id": "tree_sitter"}
                ))

    for child in node.children:
        walk_java(child, file_path, rel_path, graph, scope=scope, imports=imports, package_name=package_name)



def _add_file_and_module(graph: GraphDocument, rel_path: str, file_name: str, module_id: str) -> None:
    graph.add_node(Node(id=f"file:{rel_path}", kind="FILE", name=file_name, properties={"path": rel_path}))
    graph.add_node(Node(id=module_id, kind="MODULE", name=module_id[7:] if module_id.startswith("module:") else module_id, properties={"file": rel_path}))
    graph.add_edge(Edge(
        id=f"{module_id}__CONTAINS__file:{rel_path}", kind="CONTAINS", from_node=module_id, to_node=f"file:{rel_path}",
        source="EXTRACTED", confidence=0.60,
        evidence=[Evidence(file=rel_path, line=1, description="File mapped to module by local fallback extractor")],
        properties={"extractor_id": "tree_sitter_fallback"}
    ))


def _line_for_offset(content: str, offset: int) -> int:
    return content.count("\n", 0, max(0, offset)) + 1


def _emit_fallback_import(graph: GraphDocument, rel_path: str, module_id: str, imp: str, line: int) -> None:
    graph.add_edge(Edge(
        id=f"{module_id}__IMPORTS__module:{imp}", kind="IMPORTS", from_node=module_id, to_node=f"module:{imp}",
        source="EXTRACTED", confidence=0.60,
        evidence=[Evidence(file=rel_path, line=line, description=f"Fallback import detection: {imp}")],
        properties={"extractor_id": "tree_sitter_fallback"}
    ))


def _emit_fallback_call(graph: GraphDocument, rel_path: str, scope: str, call_name: str, line: int, col: int, lang: str, extractor_id: str = "tree_sitter_fallback") -> None:
    call_id = f"call_expr:{rel_path}:{line}:{col}"
    receiver = ""
    method_name = call_name
    if "." in call_name:
        receiver, method_name = call_name.rsplit(".", 1)
    graph.add_node(Node(
        id=call_id, kind="CALL_EXPR", name=call_name,
        properties={"file": rel_path, "line": line, "scope": scope, "call_name": call_name, "receiver": receiver, "method_name": method_name, "extractor_id": extractor_id}
    ))
    graph.add_edge(Edge(
        id=f"fallback_static_call__{scope}__{call_name}__{line}__{col}", kind="CALLS",
        from_node=scope, to_node=call_name, source="EXTRACTED", confidence=0.50,
        evidence=[Evidence(file=rel_path, line=line, description=f"Static {lang} fallback call: {call_name}")],
        properties={"extractor_id": extractor_id}
    ))


def _strip_comments_and_strings_minimal(content: str) -> str:
    # Keep positions stable enough for line reporting; protects import/method regexes from most string noise.
    content = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), content, flags=re.S)
    content = re.sub(r"//.*", "", content)
    return content


def _find_matching_brace(content: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(content)):
        ch = content[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(content) - 1


def _fallback_extract_js_ts(file_path: Path, rel_path: str, lang_name: str, graph: GraphDocument) -> None:
    content = file_path.read_text(encoding="utf-8")
    clean = _strip_comments_and_strings_minimal(content)
    module_id = f"module:{rel_path.rsplit('.', 1)[0]}"
    _add_file_and_module(graph, rel_path, file_path.name, module_id)

    for m in re.finditer(r"import\s+(?:[^'\"]+?\s+from\s+)?['\"]([^'\"]+)['\"]", content):
        _emit_fallback_import(graph, rel_path, module_id, m.group(1), _line_for_offset(content, m.start()))

    declared_ranges = []
    for cm in re.finditer(r"(?:export\s+)?class\s+([A-Za-z_$][\w$]*)[^\{]*\{", clean):
        class_name = cm.group(1)
        class_id = class_name
        start_brace = clean.find("{", cm.end() - 1)
        end_brace = _find_matching_brace(clean, start_brace)
        body = content[start_brace + 1:end_brace]
        body_abs = start_brace + 1
        declared_ranges.append((cm.start(), end_brace))
        graph.add_node(Node(id=class_id, kind="CLASS", name=class_name, properties={"file": rel_path, "line": _line_for_offset(content, cm.start()), "scope": class_id, "extractor_id": "tree_sitter_fallback"}))
        graph.add_edge(Edge(id=f"{module_id}__DECLARES__{class_id}", kind="DECLARES", from_node=module_id, to_node=class_id, source="EXTRACTED", confidence=0.60, evidence=[Evidence(file=rel_path, line=_line_for_offset(content, cm.start()), description=f"Fallback class declaration: {class_name}")], properties={"extractor_id": "tree_sitter_fallback"}))
        for mm in re.finditer(r"(?:public\s+|private\s+|protected\s+|async\s+|static\s+)*([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{", body):
            method_name = mm.group(1)
            if method_name in {"if", "for", "while", "switch", "catch", "function"}:
                continue
            m_abs = body_abs + mm.start()
            m_open = body_abs + mm.end() - 1
            m_close = _find_matching_brace(content, m_open)
            method_body = content[m_open + 1:m_close]
            method_id = f"{class_id}.{method_name}"
            line = _line_for_offset(content, m_abs)
            graph.add_node(Node(id=method_id, kind="METHOD", name=method_name, properties={"file": rel_path, "line": line, "scope": method_id, "extractor_id": "tree_sitter_fallback"}))
            graph.add_edge(Edge(id=f"{class_id}__DECLARES__{method_id}", kind="DECLARES", from_node=class_id, to_node=method_id, source="EXTRACTED", confidence=0.60, evidence=[Evidence(file=rel_path, line=line, description=f"Fallback method declaration: {method_id}")], properties={"extractor_id": "tree_sitter_fallback"}))
            for call in re.finditer(r"(?<![\w$\.])([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\(", method_body):
                call_name = call.group(1)
                if call_name in {"if", "for", "while", "switch", "catch", "return", "function", "constructor"} or call_name == method_name:
                    continue
                c_abs = m_open + 1 + call.start()
                _emit_fallback_call(graph, rel_path, method_id, call_name, _line_for_offset(content, c_abs), c_abs - content.rfind("\n", 0, c_abs) - 1, lang_name)

    # top-level functions outside classes
    for fm in re.finditer(r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{", clean):
        if any(start <= fm.start() <= end for start, end in declared_ranges):
            continue
        name = fm.group(1)
        func_id = name
        line = _line_for_offset(content, fm.start())
        graph.add_node(Node(id=func_id, kind="METHOD", name=name, properties={"file": rel_path, "line": line, "scope": func_id, "extractor_id": "tree_sitter_fallback"}))
        graph.add_edge(Edge(id=f"{module_id}__DECLARES__{func_id}", kind="DECLARES", from_node=module_id, to_node=func_id, source="EXTRACTED", confidence=0.60, evidence=[Evidence(file=rel_path, line=line, description=f"Fallback function declaration: {name}")], properties={"extractor_id": "tree_sitter_fallback"}))


def _fallback_extract_go(file_path: Path, rel_path: str, graph: GraphDocument) -> None:
    content = file_path.read_text(encoding="utf-8")
    pkg_m = re.search(r"^\s*package\s+(\w+)", content, flags=re.M)
    package_name = pkg_m.group(1) if pkg_m else "main"
    module_id = f"module:{package_name}"
    _add_file_and_module(graph, rel_path, file_path.name, module_id)
    for im in re.finditer(r"import\s+(?:\([^)]*?['\"]([^'\"]+)['\"][^)]*?\)|['\"]([^'\"]+)['\"])", content, flags=re.S):
        imp = im.group(1) or im.group(2)
        if imp:
            _emit_fallback_import(graph, rel_path, module_id, imp, _line_for_offset(content, im.start()))
    for fm in re.finditer(r"func\s+(?:\(([^)]*)\)\s*)?([A-Za-z_]\w*)\s*\([^)]*\)\s*\{", content):
        receiver = fm.group(1) or ""
        name = fm.group(2)
        receiver_type = ""
        if receiver:
            parts = receiver.replace("*", " ").split()
            if parts:
                receiver_type = parts[-1]
        scope = f"{package_name}.{receiver_type}.{name}" if receiver_type else f"{package_name}.{name}"
        line = _line_for_offset(content, fm.start())
        graph.add_node(Node(id=scope, kind="METHOD", name=name, properties={"file": rel_path, "line": line, "scope": scope, "receiver_type": receiver_type, "extractor_id": "tree_sitter_fallback"}))
        graph.add_edge(Edge(id=f"{module_id}__DECLARES__{scope}", kind="DECLARES", from_node=module_id, to_node=scope, source="EXTRACTED", confidence=0.60, evidence=[Evidence(file=rel_path, line=line, description=f"Fallback Go function declaration: {scope}")], properties={"extractor_id": "tree_sitter_fallback"}))
        close = _find_matching_brace(content, content.find("{", fm.end()-1))
        body = content[content.find("{", fm.end()-1)+1:close]
        for call in re.finditer(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*\(", body):
            call_name = call.group(1)
            if call_name in {"if", "for", "switch", "return", name}:
                continue
            c_abs = content.find("{", fm.end()-1)+1+call.start()
            _emit_fallback_call(graph, rel_path, scope, call_name, _line_for_offset(content, c_abs), c_abs - content.rfind("\n", 0, c_abs) - 1, "go")


def _fallback_extract_java(file_path: Path, rel_path: str, graph: GraphDocument) -> None:
    content = file_path.read_text(encoding="utf-8")
    pkg_m = re.search(r"^\s*package\s+([\w.]+)\s*;", content, flags=re.M)
    package_name = pkg_m.group(1) if pkg_m else ""
    module_id = f"module:{rel_path.rsplit('.', 1)[0]}"
    _add_file_and_module(graph, rel_path, file_path.name, module_id)
    for im in re.finditer(r"^\s*import\s+([\w.]+)\s*;", content, flags=re.M):
        _emit_fallback_import(graph, rel_path, module_id, im.group(1), _line_for_offset(content, im.start()))
    for cm in re.finditer(r"class\s+([A-Za-z_]\w*)[^\{]*\{", content):
        class_name = cm.group(1)
        class_id = f"{package_name}.{class_name}" if package_name else class_name
        start_brace = content.find("{", cm.end() - 1)
        end_brace = _find_matching_brace(content, start_brace)
        body = content[start_brace+1:end_brace]
        body_abs = start_brace + 1
        line = _line_for_offset(content, cm.start())
        graph.add_node(Node(id=class_id, kind="CLASS", name=class_name, properties={"file": rel_path, "line": line, "scope": class_id, "extractor_id": "tree_sitter_fallback"}))
        graph.add_edge(Edge(id=f"{module_id}__DECLARES__{class_id}", kind="DECLARES", from_node=module_id, to_node=class_id, source="EXTRACTED", confidence=0.60, evidence=[Evidence(file=rel_path, line=line, description=f"Fallback Java class declaration: {class_id}")], properties={"extractor_id": "tree_sitter_fallback"}))
        for mm in re.finditer(r"(?:public|private|protected|static|final|synchronized|\s)+[\w<>\[\]]+\s+([A-Za-z_]\w*)\s*\([^)]*\)\s*\{", body):
            method_name = mm.group(1)
            method_id = f"{class_id}.{method_name}"
            m_abs = body_abs + mm.start()
            m_open = body_abs + mm.end() - 1
            m_close = _find_matching_brace(content, m_open)
            method_body = content[m_open+1:m_close]
            line = _line_for_offset(content, m_abs)
            graph.add_node(Node(id=method_id, kind="METHOD", name=method_name, properties={"file": rel_path, "line": line, "scope": method_id, "extractor_id": "tree_sitter_fallback"}))
            graph.add_edge(Edge(id=f"{class_id}__DECLARES__{method_id}", kind="DECLARES", from_node=class_id, to_node=method_id, source="EXTRACTED", confidence=0.60, evidence=[Evidence(file=rel_path, line=line, description=f"Fallback Java method declaration: {method_id}")], properties={"extractor_id": "tree_sitter_fallback"}))
            for call in re.finditer(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*\(", method_body):
                call_name = call.group(1)
                if call_name in {"if", "for", "while", "switch", "catch", "return", "new", method_name}:
                    continue
                c_abs = m_open + 1 + call.start()
                _emit_fallback_call(graph, rel_path, method_id, call_name, _line_for_offset(content, c_abs), c_abs - content.rfind("\n", 0, c_abs) - 1, "java")


def fallback_extract_tree_sitter_file(file_path: Path, rel_path: str, lang_name: str, graph: GraphDocument, reason: str | None = None) -> None:
    diagnostics = graph.metadata.setdefault("tree_sitter_diagnostics", [])
    diagnostics.append({
        "file": rel_path,
        "language": lang_name,
        "status": "fallback",
        "reason": reason or "tree-sitter parser unavailable",
        "extractor_id": "tree_sitter_fallback",
        "parser_runtime": "fallback_regex"
    })
    if lang_name in ("javascript", "typescript"):
        _fallback_extract_js_ts(file_path, rel_path, lang_name, graph)
    elif lang_name == "go":
        _fallback_extract_go(file_path, rel_path, graph)
    elif lang_name == "java":
        _fallback_extract_java(file_path, rel_path, graph)


def extract_tree_sitter_file(file_path: Path, rel_path: str, lang_name: str, graph: GraphDocument) -> None:
    diagnostics = graph.metadata.setdefault("tree_sitter_diagnostics", [])
    
    if is_tree_sitter_available():
        try:
            lang = tree_sitter_language_pack.get_language(lang_name)
            parser = tree_sitter.Parser(lang)
            content = file_path.read_text(encoding="utf-8")
            tree = parser.parse(bytes(content, "utf-8"))
            
            # Add FILE node
            graph.add_node(Node(
                id=f"file:{rel_path}",
                kind="FILE",
                name=file_path.name,
                properties={"path": rel_path, "extractor_id": "tree_sitter"}
            ))
            
            imports = set()
            
            if lang_name in ("javascript", "typescript"):
                walk_js_ts(tree.root_node, file_path, rel_path, graph, imports=imports)
                mod_id = f"module:{rel_path.rsplit('.', 1)[0]}"
            elif lang_name == "go":
                pkg = find_go_package(tree.root_node)
                walk_go(tree.root_node, file_path, rel_path, graph, imports=imports, package_name=pkg)
                mod_id = f"module:{pkg}"
            elif lang_name == "java":
                pkg = find_java_package(tree.root_node)
                walk_java(tree.root_node, file_path, rel_path, graph, imports=imports, package_name=pkg)
                mod_id = f"module:{rel_path.rsplit('.', 1)[0]}"
            else:
                diagnostics.append({
                    "file": rel_path,
                    "language": lang_name,
                    "status": "skipped",
                    "reason": f"Unsupported language: {lang_name}",
                    "extractor_id": "tree_sitter",
                    "parser_runtime": "tree-sitter-language-pack"
                })
                return
                
            # Add MODULE node mapping if not added by parser
            if not any(n.id == mod_id for n in graph.nodes):
                graph.add_node(Node(
                    id=mod_id,
                    kind="MODULE",
                    name=mod_id[7:] if mod_id.startswith("module:") else mod_id,
                    properties={"file": rel_path, "extractor_id": "tree_sitter"}
                ))
                
            # Add IMPORTS edges
            for imp in imports:
                edge_id = f"{mod_id}__IMPORTS__module:{imp}"
                graph.add_edge(Edge(
                    id=edge_id,
                    kind="IMPORTS",
                    from_node=mod_id,
                    to_node=f"module:{imp}",
                    source="EXTRACTED",
                    confidence=1.0,
                    evidence=[],
                    properties={"extractor_id": "tree_sitter"}
                ))
                
            diagnostics.append({
                "file": rel_path,
                "language": lang_name,
                "status": "native",
                "reason": "Parsed successfully using native tree-sitter",
                "extractor_id": "tree_sitter",
                "parser_runtime": "tree-sitter-language-pack"
            })
            return
        except Exception as e:
            errors = graph.metadata.setdefault("tree_sitter_errors", [])
            if isinstance(errors, list):
                errors.append(f"Error parsing file {rel_path} ({lang_name}): {str(e)}")
            reason = f"Native parsing error: {str(e)}"
            fallback_extract_tree_sitter_file(file_path, rel_path, lang_name, graph, reason=reason)
            return
    else:
        reason = "tree-sitter packages or runtime unavailable"
        fallback_extract_tree_sitter_file(file_path, rel_path, lang_name, graph, reason=reason)


def extract_tree_sitter_project(project_path: str | Path, languages: List[str] | None = None, files: List[str] | None = None) -> GraphDocument:
    graph = GraphDocument()

    root = Path(project_path).resolve()
    if not root.exists():
        return graph

    if languages is None:
        languages = get_supported_tree_sitter_languages()
        if not languages:
            languages = ["javascript", "typescript", "go", "java"]

    lang_ext_map = {
        "javascript": [".js", ".jsx"],
        "typescript": [".ts", ".tsx"],
        "go": [".go"],
        "java": [".java"]
    }
    selected = {str(item).replace("\\", "/") for item in files or []}

    # Gather matching files
    from impact_engine.scope import iter_project_files
    for p in iter_project_files(root):
        parts = p.relative_to(root).parts
        if any(part.startswith(".") or part in {
            "__pycache__", "venv", "env", "node_modules", "external_tools",
            "dist", "build", "coverage", ".impact_engine"
        } for part in parts):
            continue
            
        if p.is_file():
            suffix = p.suffix.lower()
            rel_path = str(p.relative_to(root).as_posix())
            if files is not None and rel_path not in selected:
                continue
            for lang in languages:
                if lang in lang_ext_map and suffix in lang_ext_map[lang]:
                    extract_tree_sitter_file(p, rel_path, lang, graph)
                    break

    # Determine aggregate tree_sitter_status
    diagnostics = graph.metadata.get("tree_sitter_diagnostics", [])
    if not diagnostics:
        if not is_tree_sitter_available():
            graph.metadata["tree_sitter_status"] = "unavailable"
        else:
            graph.metadata["tree_sitter_status"] = "native"
    else:
        statuses = {d["status"] for d in diagnostics}
        if "fallback" in statuses and "native" in statuses:
            graph.metadata["tree_sitter_status"] = "partial_native"
        elif "native" in statuses:
            graph.metadata["tree_sitter_status"] = "native"
        elif "fallback" in statuses:
            graph.metadata["tree_sitter_status"] = "partial_local_fallback"
        else:
            graph.metadata["tree_sitter_status"] = "native"

    return graph
