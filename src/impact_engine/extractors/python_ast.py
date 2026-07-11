"""Python AST extractor implementation. Stage 4 complete."""
import ast
from pathlib import Path
from impact_engine.models import GraphDocument, Node, Edge, Evidence


_SKIP_DIRS = {
    ".impact_engine", ".git", ".venv", "venv", "env", "__pycache__",
    "node_modules", "external_tools", "dist", "build", "coverage",
}


class ASTFactExtractor(ast.NodeVisitor):
    def __init__(self, relative_path: str, module_name: str, doc: GraphDocument):
        self.relative_path = relative_path
        self.module_name = module_name
        self.doc = doc
        
        self.current_class = None
        self.current_method = None
        self.scope = module_name
        self.imports = {}

    def _module_node(self):
        module_id = f"module:{self.module_name}"
        return next((n for n in self.doc.nodes if n.id == module_id), None)

    def _record_import_alias(self, alias: str, target: str) -> None:
        self.imports[alias] = target
        module_node = self._module_node()
        if module_node is not None:
            aliases = module_node.properties.setdefault("import_aliases", {})
            aliases[alias] = target

    def add_fact_node(self, node_id: str, kind: str, name: str, properties: dict) -> None:
        self.doc.add_node(Node(
            id=node_id,
            kind=kind,
            name=name,
            properties=properties
        ))

    def add_fact_edge(self, edge_id: str, kind: str, from_node: str, to_node: str, lineno: int, description: str) -> None:
        evidence = Evidence(
            description=description,
            file=self.relative_path,
            line=lineno,
            source="EXTRACTED"
        )
        self.doc.add_edge(Edge(
            id=edge_id,
            kind=kind,
            from_node=from_node,
            to_node=to_node,
            source="EXTRACTED",
            confidence=1.0,
            evidence=[evidence]
        ))

    def visit_ClassDef(self, node: ast.ClassDef):
        class_name = node.name
        parent_class = self.current_class
        
        if self.current_class:
            full_class_name = f"{self.current_class}.{class_name}"
        else:
            full_class_name = class_name
            
        class_id = f"class:{self.module_name}.{full_class_name}"
        
        old_scope = self.scope
        self.scope = f"{self.module_name}.{full_class_name}"
        self.current_class = full_class_name
        
        self.add_fact_node(
            node_id=class_id,
            kind="CLASS",
            name=class_name,
            properties={
                "module": self.module_name,
                "class": full_class_name,
                "bases": [self.imports.get(ast.unparse(base), f"{self.module_name}.{ast.unparse(base)}") for base in node.bases],
            }
        )
        
        if parent_class:
            parent_class_id = f"class:{self.module_name}.{parent_class}"
            edge_id = f"{parent_class_id}__DECLARES__{class_id}"
            self.add_fact_edge(edge_id, "DECLARES", parent_class_id, class_id, node.lineno, f"Class {class_name} declared in class {parent_class}")
        else:
            module_id = f"module:{self.module_name}"
            edge_id = f"{module_id}__DECLARES__{class_id}"
            self.add_fact_edge(edge_id, "DECLARES", module_id, class_id, node.lineno, f"Class {class_name} declared in module {self.module_name}")
            
        self.generic_visit(node)
        
        self.scope = old_scope
        self.current_class = parent_class

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._visit_func(node)

    def _visit_func(self, node: ast.AST):
        func_name = node.name
        old_method = self.current_method
        old_scope = self.scope
        
        if self.current_class:
            self.scope = f"{self.module_name}.{self.current_class}.{func_name}"
            method_id = f"method:{self.scope}"
            kind = "METHOD"
        else:
            self.scope = f"{self.module_name}.{func_name}"
            method_id = f"method:{self.scope}"
            kind = "METHOD"
            
        self.current_method = func_name

        decorators = []
        for dec in getattr(node, "decorator_list", []):
            try:
                decorators.append("@" + ast.unparse(dec))
            except Exception:
                pass

        properties = {
            "module": self.module_name,
            "class": self.current_class,
            "name": func_name,
            "scope": self.scope,
            "file": self.relative_path,
            "line": node.lineno
        }
        if decorators:
            properties["decorators"] = decorators

        # Parse parameter type annotations
        if hasattr(node, "args") and hasattr(node.args, "args"):
            param_order = []
            for arg in node.args.args:
                if arg.arg != "self":
                    param_order.append(arg.arg)
                    if arg.annotation:
                        try:
                            ann_str = ast.unparse(arg.annotation)
                            fq_name = self.imports.get(ann_str)
                            if not fq_name:
                                fq_name = f"{self.module_name}.{ann_str}"
                            properties[f"param_type:{arg.arg}"] = fq_name
                        except Exception:
                            pass
            if param_order:
                properties["param_order"] = param_order
        if getattr(node, "returns", None) is not None:
            try:
                return_text = ast.unparse(node.returns)
                properties["return_type"] = self.imports.get(return_text, f"{self.module_name}.{return_text}")
            except Exception:
                pass
                
        # Parse parameter defaults (e.g. Depends(get_order_service))
        if hasattr(node, "args") and node.args.defaults:
            num_args = len(node.args.args)
            num_defaults = len(node.args.defaults)
            for idx, default_node in enumerate(node.args.defaults):
                param_idx = num_args - num_defaults + idx
                if param_idx >= 0 and param_idx < num_args:
                    arg_name = node.args.args[param_idx].arg
                    try:
                        def_str = ast.unparse(default_node)
                        properties[f"param_default:{arg_name}"] = def_str
                    except Exception:
                        pass

        self.add_fact_node(
            node_id=method_id,
            kind=kind,
            name=func_name,
            properties=properties
        )
        
        if self.current_class:
            class_id = f"class:{self.module_name}.{self.current_class}"
            # Propagate param types from __init__ to the parent class node properties
            if func_name == "__init__":
                class_node = next((n for n in self.doc.nodes if n.id == class_id), None)
                if class_node:
                    for k, v in properties.items():
                        if k.startswith("param_type:"):
                            class_node.properties[k] = v
            edge_id = f"{class_id}__DECLARES__{method_id}"
            self.add_fact_edge(edge_id, "DECLARES", class_id, method_id, node.lineno, f"Method {func_name} declared in class {self.current_class}")
        else:
            module_id = f"module:{self.module_name}"
            edge_id = f"{module_id}__DECLARES__{method_id}"
            self.add_fact_edge(edge_id, "DECLARES", module_id, method_id, node.lineno, f"Function {func_name} declared in module {self.module_name}")
            
        self.generic_visit(node)
        
        self.current_method = old_method
        self.scope = old_scope

    def visit_Import(self, node: ast.Import):
        module_id = f"module:{self.module_name}"
        for name in node.names:
            alias = name.asname or name.name
            self._record_import_alias(alias, name.name)
            target_module_id = f"module:{name.name}"
            edge_id = f"{module_id}__IMPORTS__{target_module_id}"
            self.add_fact_edge(edge_id, "IMPORTS", module_id, target_module_id, node.lineno, f"Module {self.module_name} imports {name.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            module_id = f"module:{self.module_name}"
            if node.level:
                base_parts = self.module_name.split(".") if self.relative_path.endswith("__init__.py") else self.module_name.split(".")[:-1]
                package_parts = base_parts[: max(0, len(base_parts) - node.level + 1)]
                resolved_module = ".".join(package_parts + node.module.split("."))
            else:
                resolved_module = node.module
            for name in node.names:
                alias = name.asname or name.name
                self._record_import_alias(alias, f"{resolved_module}.{name.name}")
            target_module_id = f"module:{resolved_module}"
            edge_id = f"{module_id}__IMPORTS__{target_module_id}"
            self.add_fact_edge(edge_id, "IMPORTS", module_id, target_module_id, node.lineno, f"Module {self.module_name} imports from {node.module}")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        if self.current_method:
            parent_id = f"method:{self.scope}"
        else:
            parent_id = f"module:{self.scope}"

        method_id = parent_id
        
        for target in node.targets:
            target_str = ast.unparse(target)
            
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                target_kind = "self_attribute"
            else:
                target_kind = "local"
                
            value_str = ast.unparse(node.value)
            
            props = {
                "target": target_str,
                "value": value_str,
                "scope": self.scope,
                "target_kind": target_kind
            }
            
            if isinstance(node.value, ast.Call):
                call_name = ast.unparse(node.value.func)
                props["call_name"] = call_name
                kw_args = {}
                for kw in node.value.keywords:
                    if kw.arg:
                        kw_args[kw.arg] = ast.unparse(kw.value)
                props["keyword_args"] = kw_args
                if node.value.args:
                    props["args"] = [ast.unparse(arg) for arg in node.value.args]
                
            assignment_id = f"assignment:{self.scope}:{node.lineno}:{target_str}"
            
            self.add_fact_node(
                node_id=assignment_id,
                kind="ASSIGNMENT",
                name=f"{target_str} = {value_str}",
                properties=props
            )
            
            edge_id = f"{method_id}__CONTAINS__{assignment_id}"
            self.add_fact_edge(
                edge_id=edge_id,
                kind="CONTAINS",
                from_node=method_id,
                to_node=assignment_id,
                lineno=node.lineno,
                description=f"Method contains assignment to {target_str}"
            )
            
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Attribute):
            receiver = ast.unparse(node.func.value)
            method_name = node.func.attr
            call_name = ast.unparse(node.func)
        else:
            receiver = None
            method_name = None
            call_name = ast.unparse(node.func)
            
        args = [ast.unparse(arg) for arg in node.args]
        kw_args = {}
        for kw in node.keywords:
            if kw.arg:
                kw_args[kw.arg] = ast.unparse(kw.value)
                
        props = {
            "scope": self.scope,
            "call_name": call_name,
            "args": args,
            "keyword_args": kw_args,
            "file": self.relative_path,
            "line": node.lineno,
        }
        if receiver is not None:
            props["receiver"] = receiver
        if method_name is not None:
            props["method_name"] = method_name
            
        call_id = f"call:{self.scope}:{node.lineno}:{call_name}"
        
        self.add_fact_node(
            node_id=call_id,
            kind="CALL_EXPR",
            name=f"{call_name}(...)",
            properties=props
        )
        
        if self.current_method:
            parent_id = f"method:{self.scope}"
            desc = f"Method contains call to {call_name}"
        else:
            parent_id = f"module:{self.scope}"
            desc = f"Module contains call to {call_name}"
            
        edge_id = f"{parent_id}__CONTAINS__{call_id}"
        self.add_fact_edge(
            edge_id=edge_id,
            kind="CONTAINS",
            from_node=parent_id,
            to_node=call_id,
            lineno=node.lineno,
            description=desc
        )
        
        self.generic_visit(node)


def extract_project(path: str | Path, files: list[str] | None = None) -> GraphDocument:
    root_path = Path(path).resolve()
    doc = GraphDocument(metadata={"extractor": "python_ast", "status": "extracted", "path": str(root_path)})
    
    py_files = []
    if root_path.is_file():
        if root_path.suffix == ".py":
            py_files.append(root_path)
    else:
        selected = {str(item).replace("\\", "/") for item in files or []}
        for p in root_path.rglob("*.py"):
            parts = p.relative_to(root_path).parts
            if any(part.startswith(".") or part in _SKIP_DIRS for part in parts):
                continue
            if files is not None and str(p.relative_to(root_path).as_posix()) not in selected:
                continue
            py_files.append(p)
            
    py_files.sort()
    
    for filepath in py_files:
        if root_path.is_file():
            rel_path = filepath.name
            module_name = filepath.stem
        else:
            rel_path = filepath.relative_to(root_path).as_posix()
            module_parts = list(filepath.relative_to(root_path).with_suffix("").parts)
            if module_parts and module_parts[-1] == "__init__":
                module_parts.pop()
            module_name = ".".join(module_parts)
        
        file_id = f"file:{rel_path}"
        doc.add_node(Node(
            id=file_id,
            kind="FILE",
            name=rel_path,
            properties={"path": rel_path}
        ))
        
        module_id = f"module:{module_name}"
        doc.add_node(Node(
            id=module_id,
            kind="MODULE",
            name=module_name,
            properties={"name": module_name}
        ))
        
        edge_id = f"{file_id}__CONTAINS__{module_id}"
        doc.add_edge(Edge(
            id=edge_id,
            kind="CONTAINS",
            from_node=file_id,
            to_node=module_id,
            source="EXTRACTED",
            confidence=1.0,
            evidence=[Evidence(
                description=f"File {rel_path} contains module {module_name}",
                file=rel_path,
                line=1,
                source="EXTRACTED"
            )]
        ))
        
        try:
            content = filepath.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(filepath))
            extractor = ASTFactExtractor(rel_path, module_name, doc)
            extractor.visit(tree)
        except Exception as e:
            doc.metadata[f"error_{rel_path}"] = str(e)
            
    return doc
