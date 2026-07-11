"""Path expression evaluator working on extracted facts.

The evaluator consumes JSON-like expression facts. It intentionally does not
parse JavaScript/TypeScript source code. A larger analyzer should provide facts
such as constants, return expressions, imports and wrapper calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import EvalResult


@dataclass
class ModuleIndex:
    constants_by_fqn: dict[str, dict[str, Any]] = field(default_factory=dict)
    functions_by_fqn: dict[str, dict[str, Any]] = field(default_factory=dict)
    constants_by_module_name: dict[tuple[str, str], str] = field(default_factory=dict)
    functions_by_module_name: dict[tuple[str, str], str] = field(default_factory=dict)
    imports_by_module: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_input(cls, input_data: dict[str, Any]) -> "ModuleIndex":
        index = cls()
        modules = input_data.get("modules", []) or []

        def add_constant(module_id: str, constant: dict[str, Any]) -> None:
            name = constant.get("name") or constant.get("id")
            if not name:
                return
            fqn = constant.get("id") or f"{module_id}.{name}"
            fact = {**constant, "id": fqn, "name": name, "module": constant.get("module", module_id)}
            index.constants_by_fqn[fqn] = fact
            index.constants_by_module_name[(fact["module"], name)] = fqn

        def add_function(module_id: str, function: dict[str, Any]) -> None:
            name = function.get("name") or function.get("id")
            if not name:
                return
            fqn = function.get("id") or f"{module_id}.{name}"
            fact = {**function, "id": fqn, "name": name, "module": function.get("module", module_id)}
            index.functions_by_fqn[fqn] = fact
            index.functions_by_module_name[(fact["module"], name)] = fqn

        for module in modules:
            module_id = module.get("id") or module.get("name") or module.get("path")
            if not module_id:
                continue
            import_map: dict[str, str] = {}
            for imp in module.get("imports", []) or []:
                local = imp.get("local") or imp.get("alias") or imp.get("name") or imp.get("imported")
                target = imp.get("target")
                if not target:
                    imported = imp.get("imported") or imp.get("name") or local
                    from_module = imp.get("from_module") or imp.get("from")
                    if from_module and imported:
                        target = f"{from_module}.{imported}"
                if local and target:
                    import_map[str(local)] = str(target)
            index.imports_by_module[str(module_id)] = import_map

            for const in module.get("constants", []) or []:
                add_constant(str(module_id), const)
            for func in module.get("functions", []) or []:
                add_function(str(module_id), func)

        for const in input_data.get("constants", []) or []:
            module_id = const.get("module", "")
            add_constant(str(module_id), const)
        for func in input_data.get("functions", []) or []:
            module_id = func.get("module", "")
            add_function(str(module_id), func)
        for func in input_data.get("frontend_functions", []) or []:
            module_id = func.get("module", "")
            add_function(str(module_id), func)

        # Expand export-star/barrel chains after every module import map is
        # known. This keeps resolution deterministic and avoids name-only
        # fallback when a symbol crosses multiple index modules.
        for module_id, imports in list(index.imports_by_module.items()):
            star_modules = [target for local, target in imports.items() if local == "*" and target]
            for star_module in star_modules:
                imports.pop("*", None)
                for exported_local, exported_target in index.imports_by_module.get(star_module, {}).items():
                    imports.setdefault(exported_local, exported_target)
                for (decl_module, declared_name), declared_fqn in index.functions_by_module_name.items():
                    if decl_module == star_module:
                        imports.setdefault(declared_name, declared_fqn)
                for (decl_module, declared_name), declared_fqn in index.constants_by_module_name.items():
                    if decl_module == star_module:
                        imports.setdefault(declared_name, declared_fqn)

        # Hook exposed functions may point to normal frontend functions, so no
        # special handling is needed here.
        return index

    def resolve_constant_fqn(self, module: str | None, name: str) -> str | None:
        if name in self.constants_by_fqn:
            return name
        if module and (module, name) in self.constants_by_module_name:
            return self.constants_by_module_name[(module, name)]
        if module:
            if "." in name:
                namespace, member = name.split(".", 1)
                namespace_target = self.imports_by_module.get(module, {}).get(namespace)
                if namespace_target:
                    return self.resolve_constant_fqn(namespace_target, member)
            target = self.imports_by_module.get(module, {}).get(name)
            if target:
                if target in self.constants_by_fqn:
                    return target
                # Imported target may be a module/name pair not fully indexed yet.
                target_module, _, target_name = target.rpartition(".")
                resolved = self.constants_by_module_name.get((target_module, target_name))
                if resolved:
                    return resolved
                return self._resolve_reexported_constant(target_module, target_name)
        candidates = [fqn for (mod, const_name), fqn in self.constants_by_module_name.items() if const_name == name]
        return candidates[0] if len(candidates) == 1 else None

    def resolve_function_fqn(self, module: str | None, name: str) -> str | None:
        if name in self.functions_by_fqn:
            return name
        if module and (module, name) in self.functions_by_module_name:
            return self.functions_by_module_name[(module, name)]
        if module:
            if "." in name:
                namespace, member = name.split(".", 1)
                namespace_target = self.imports_by_module.get(module, {}).get(namespace)
                if namespace_target:
                    return self.resolve_function_fqn(namespace_target, member)
            target = self.imports_by_module.get(module, {}).get(name)
            if target:
                if target in self.functions_by_fqn:
                    return target
                target_module, _, target_name = target.rpartition(".")
                resolved = self.functions_by_module_name.get((target_module, target_name))
                if resolved:
                    return resolved
                return self._resolve_reexported_function(target_module, target_name)
        candidates = [fqn for (mod, func_name), fqn in self.functions_by_module_name.items() if func_name == name]
        return candidates[0] if len(candidates) == 1 else None

    def _resolve_reexported_constant(self, module: str, name: str) -> str | None:
        target = self.imports_by_module.get(module, {}).get(name)
        if not target:
            target = self.imports_by_module.get(f"{module}.index", {}).get(name)
        if not target:
            return None
        if target in self.constants_by_fqn:
            return target
        target_module, _, target_name = target.rpartition(".")
        return self.constants_by_module_name.get((target_module, target_name))

    def _resolve_reexported_function(self, module: str, name: str) -> str | None:
        target = self.imports_by_module.get(module, {}).get(name)
        if not target:
            target = self.imports_by_module.get(f"{module}.index", {}).get(name)
        if not target:
            return None
        if target in self.functions_by_fqn:
            return target
        target_module, _, target_name = target.rpartition(".")
        return self.functions_by_module_name.get((target_module, target_name))


class PathEvaluator:
    """Evaluate path expressions from extracted frontend facts."""

    def __init__(self, input_data: dict[str, Any] | ModuleIndex):
        self.index = input_data if isinstance(input_data, ModuleIndex) else ModuleIndex.from_input(input_data)

    def evaluate(self, expr: Any, *, module: str | None = None, scope: dict[str, EvalResult] | None = None) -> EvalResult:
        return self._evaluate(expr, module=module, scope=scope or {}, visited=set())

    def evaluate_function(
        self,
        name_or_fqn: str,
        args: list[Any] | None = None,
        *,
        module: str | None = None,
    ) -> EvalResult:
        return self._evaluate_call(name_or_fqn, args or [], module=module, scope={}, visited=set())

    def _evaluate(
        self,
        expr: Any,
        *,
        module: str | None,
        scope: dict[str, EvalResult],
        visited: set[str],
    ) -> EvalResult:
        if expr is None:
            return EvalResult(None, confidence=0.0, warnings=["empty expression"], unresolved=["<none>"])

        if isinstance(expr, str):
            return EvalResult(expr, confidence=0.95, evidence=[f"literal:{expr}"])

        if isinstance(expr, (int, float, bool)):
            return EvalResult(str(expr), confidence=0.7, evidence=[f"scalar:{expr}"])

        if isinstance(expr, list):
            return self._concat(expr, module=module, scope=scope, visited=visited, evidence_prefix="list-concat")

        if not isinstance(expr, dict):
            return EvalResult(None, confidence=0.0, warnings=[f"unsupported expression type {type(expr).__name__}"], unresolved=[repr(expr)])

        expr_type = expr.get("type") or expr.get("kind")
        if expr_type in ("literal", "string"):
            return EvalResult(str(expr.get("value", "")), confidence=0.95, evidence=["string literal"])

        if expr_type == "param":
            name = str(expr.get("name", "param"))
            return EvalResult("{param}", confidence=0.90, evidence=[f"dynamic param:{name}"])

        if expr_type == "unknown":
            name = str(expr.get("name", "unknown"))
            return EvalResult(None, confidence=0.0, warnings=[f"unknown expression:{name}"], unresolved=[name])

        if expr_type in {"conditional", "ternary"}:
            condition = self._evaluate(expr.get("condition"), module=module, scope=scope, visited=visited)
            # A missing optional argument is represented as None and follows the
            # false branch. A supplied dynamic parameter follows the true branch;
            # this preserves paths such as orderPath() vs orderPath(orderId).
            condition_value = condition.value
            if condition_value is None or str(condition_value).lower() in {"", "false", "undefined", "null"}:
                branch_key = "when_false"
            elif str(condition_value).lower() == "true" or condition_value == "{param}":
                branch_key = "when_true"
            else:
                return EvalResult(
                    None,
                    confidence=0.0,
                    evidence=[*condition.evidence, "conditional branch unresolved"],
                    warnings=[*condition.warnings, "conditional expression depends on unresolved value"],
                    unresolved=[*condition.unresolved, "conditional"],
                )
            branch = self._evaluate(expr.get(branch_key), module=module, scope=scope, visited=visited)
            return EvalResult(
                branch.value,
                confidence=min(condition.confidence, branch.confidence, 0.92),
                evidence=[*condition.evidence, f"conditional:{branch_key}", *branch.evidence],
                warnings=[*condition.warnings, *branch.warnings],
                unresolved=[*condition.unresolved, *branch.unresolved],
            )

        if expr_type == "ref":
            name = str(expr.get("name"))
            return self._evaluate_ref(name, module=module, scope=scope, visited=visited)

        if expr_type in ("concat", "template"):
            parts = expr.get("parts")
            if parts is None and expr_type == "template":
                parts = expr.get("quasis", [])
            return self._concat(parts or [], module=module, scope=scope, visited=visited, evidence_prefix=expr_type)

        if expr_type == "binary" and expr.get("op") == "+":
            return self._concat([expr.get("left"), expr.get("right")], module=module, scope=scope, visited=visited, evidence_prefix="binary-plus")

        if expr_type == "call":
            name = str(expr.get("name") or expr.get("callee"))
            return self._evaluate_call(name, expr.get("args", []) or [], module=module, scope=scope, visited=visited)

        if expr_type == "object":
            return EvalResult(None, confidence=0.0, warnings=["object expression is not a path"], unresolved=["object"])

        return EvalResult(None, confidence=0.0, warnings=[f"unsupported expression kind:{expr_type}"], unresolved=[str(expr_type)])

    def _evaluate_ref(
        self,
        name: str,
        *,
        module: str | None,
        scope: dict[str, EvalResult],
        visited: set[str],
    ) -> EvalResult:
        if name in scope:
            result = scope[name]
            return EvalResult(
                result.value,
                confidence=min(result.confidence, 0.90 if result.value == "{param}" else result.confidence),
                evidence=[*result.evidence, f"scope ref:{name}"],
                warnings=list(result.warnings),
                unresolved=list(result.unresolved),
            )

        fqn = self.index.resolve_constant_fqn(module, name)
        if not fqn:
            return EvalResult(None, confidence=0.0, warnings=[f"unresolved reference:{name}"], unresolved=[name])
        if fqn in visited:
            return EvalResult(None, confidence=0.0, warnings=[f"cyclic constant reference:{fqn}"], unresolved=[fqn])
        fact = self.index.constants_by_fqn[fqn]
        expr = fact.get("expression", fact.get("value"))
        nested = self._evaluate(expr, module=fact.get("module", module), scope=scope, visited={*visited, fqn})
        nested.evidence.append(f"const:{fqn}")
        return nested.with_confidence(0.94)

    def _evaluate_call(
        self,
        name: str,
        args: list[Any],
        *,
        module: str | None,
        scope: dict[str, EvalResult],
        visited: set[str],
    ) -> EvalResult:
        fqn = self.index.resolve_function_fqn(module, name)
        if not fqn:
            return EvalResult(None, confidence=0.0, warnings=[f"unresolved function:{name}"], unresolved=[name])
        if fqn in visited:
            return EvalResult(None, confidence=0.0, warnings=[f"cyclic function helper:{fqn}"], unresolved=[fqn])

        fact = self.index.functions_by_fqn[fqn]
        params = [str(p) for p in fact.get("params", [])]
        call_scope = dict(scope)
        for index, param in enumerate(params):
            if index < len(args):
                call_scope[param] = self._evaluate(args[index], module=module, scope=scope, visited=visited)
            else:
                # Omitted optional arguments are statically known to be absent;
                # they are not unresolved dynamic values.
                call_scope[param] = EvalResult(None, confidence=0.95, evidence=[f"omitted arg:{param}"])

        return_expr = fact.get("returns", fact.get("return", fact.get("expression")))
        result = self._evaluate(
            return_expr,
            module=fact.get("module", module),
            scope=call_scope,
            visited={*visited, fqn},
        )
        result.evidence.append(f"function:{fqn}")
        imported_penalty = 0.85 if module and fact.get("module") != module else 0.90
        return result.with_confidence(imported_penalty)

    def _concat(
        self,
        parts: list[Any],
        *,
        module: str | None,
        scope: dict[str, EvalResult],
        visited: set[str],
        evidence_prefix: str,
    ) -> EvalResult:
        values: list[str] = []
        confidence = 0.93
        evidence = [evidence_prefix]
        warnings: list[str] = []
        unresolved: list[str] = []
        for part in parts:
            result = self._evaluate(part, module=module, scope=scope, visited=visited)
            evidence.extend(result.evidence)
            warnings.extend(result.warnings)
            unresolved.extend(result.unresolved)
            confidence = min(confidence, result.confidence)
            if not result.ok:
                return EvalResult(None, confidence=0.0, evidence=evidence, warnings=warnings, unresolved=unresolved)
            values.append(result.value or "")
        return EvalResult("".join(values), confidence=confidence, evidence=evidence, warnings=warnings, unresolved=unresolved)
