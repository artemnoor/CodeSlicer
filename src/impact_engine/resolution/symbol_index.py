"""SymbolIndex for symbol lookup optimization. Stage 13."""
from dataclasses import dataclass
from typing import Dict, List, Set, Optional
from impact_engine.models import GraphDocument


@dataclass
class SymbolIndex:
    modules: Set[str]
    classes_by_name: Dict[str, List[str]]
    methods: Set[str]
    imports_by_module: Dict[str, Set[str]]
    import_aliases_by_module: Dict[str, Dict[str, str]]
    functions_by_name: Dict[str, List[str]]
    function_return_types: Dict[str, str]
    bases_by_class: Dict[str, List[str]]

    def canonicalize_class_name(self, type_name: str) -> Optional[str]:
        if not type_name:
            return None
        simple_name = type_name.split(".")[-1]
        candidates = self.classes_by_name.get(simple_name, [])
        if type_name in candidates:
            return type_name
        for candidate in candidates:
            if candidate.endswith(type_name):
                return candidate
        if "." in type_name:
            suffix_without_root = ".".join(type_name.split(".")[1:])
            for candidate in candidates:
                if candidate.endswith(suffix_without_root):
                    return candidate
        if len(candidates) == 1:
            return candidates[0]
        return None

    def resolve_function_name(self, function_name: str, current_module: str, current_scope: str | None = None) -> Optional[str]:
        """Resolve a top-level function through local scope or exact imports."""
        candidates = self.functions_by_name.get(function_name, [])
        for prefix in ([current_scope, current_module] if current_scope else [current_module]):
            local = f"{prefix}.{function_name}"
            if local in candidates:
                return local
        imported = self.import_aliases_by_module.get(current_module, {}).get(function_name)
        for _ in range(5):
            if imported and imported in self.functions_by_name.get(imported.rsplit(".", 1)[-1], []):
                return imported
            if not imported or "." not in imported:
                break
            module_name, member = imported.rsplit(".", 1)
            imported = self.import_aliases_by_module.get(module_name, {}).get(member)
        imported_modules = self.imports_by_module.get(current_module, set())
        imported_candidates = [item for item in candidates if item.rsplit(".", 1)[0] in imported_modules]
        return imported_candidates[0] if len(imported_candidates) == 1 else None

    def resolve_module_member(self, alias: str, member: str, current_module: str) -> Optional[str]:
        target_module = self.import_aliases_by_module.get(current_module, {}).get(alias)
        if not target_module:
            return None
        candidate = f"{target_module}.{member}"
        return candidate if candidate in self.methods or candidate in self.functions_by_name.get(member, []) else None

    def resolve_method_target(self, class_name: str, method_name: str) -> Optional[str]:
        direct = f"{class_name}.{method_name}"
        if direct in self.methods:
            return direct
        seen: set[str] = set()
        queue = list(self.bases_by_class.get(class_name, []))
        while queue:
            base = queue.pop(0)
            if base in seen:
                continue
            seen.add(base)
            candidate = f"{base}.{method_name}"
            if candidate in self.methods:
                return candidate
            queue.extend(self.bases_by_class.get(base, []))
        return None

    def resolve_class_name(self, class_name: str, current_module: str) -> Optional[str]:
        if "." in class_name:
            canonical = self.canonicalize_class_name(class_name)
            if canonical:
                return canonical

        imported_alias = self.import_aliases_by_module.get(current_module, {}).get(class_name)
        if imported_alias:
            canonical = self.canonicalize_class_name(imported_alias)
            if canonical:
                return canonical

        # 1. Check local declaration
        local_full = f"{current_module}.{class_name}"
        candidates = self.classes_by_name.get(class_name, [])
        if local_full in candidates:
            return local_full

        # 2. Check imports of current_module
        imported_modules = self.imports_by_module.get(current_module, set())
        for target_module in imported_modules:
            target_full = f"{target_module}.{class_name}"
            if target_full in candidates:
                return target_full

        return None


def build_symbol_index(graph: GraphDocument) -> SymbolIndex:
    modules = set()
    classes_by_name = {}
    methods = set()
    imports_by_module = {}
    import_aliases_by_module = {}
    functions_by_name = {}
    function_return_types = {}
    bases_by_class = {}

    for node in graph.nodes:
        if node.kind == "MODULE":
            mod_name = node.id
            if mod_name.startswith("module:"):
                mod_name = mod_name[7:]
            modules.add(mod_name)
            aliases = node.properties.get("import_aliases")
            if isinstance(aliases, dict):
                import_aliases_by_module[mod_name] = dict(aliases)
            
        elif node.kind == "CLASS":
            full_class = node.id
            if full_class.startswith("class:"):
                full_class = full_class[6:]
            simple_name = full_class.split(".")[-1]
            classes_by_name.setdefault(simple_name, []).append(full_class)
            bases = node.properties.get("bases", [])
            if isinstance(bases, list):
                bases_by_class[full_class] = [str(item) for item in bases]
            
        elif node.kind == "METHOD":
            full_method = node.id
            if full_method.startswith("method:"):
                full_method = full_method[7:]
            methods.add(full_method)
            if not node.properties.get("class"):
                functions_by_name.setdefault(full_method.rsplit(".", 1)[-1], []).append(full_method)
                if node.properties.get("return_type"):
                    function_return_types[full_method] = str(node.properties["return_type"])

    for edge in graph.edges:
        if edge.kind == "IMPORTS":
            from_mod = edge.from_node
            to_mod = edge.to_node
            if from_mod.startswith("module:"):
                from_mod = from_mod[7:]
            if to_mod.startswith("module:"):
                to_mod = to_mod[7:]
            imports_by_module.setdefault(from_mod, set()).add(to_mod)

    return SymbolIndex(
        modules=modules,
        classes_by_name=classes_by_name,
        methods=methods,
        imports_by_module=imports_by_module,
        import_aliases_by_module=import_aliases_by_module,
        functions_by_name=functions_by_name,
        function_return_types=function_return_types,
        bases_by_class=bases_by_class,
    )
