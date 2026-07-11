from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .bindings import BindingResolver
from .facts import FactSet
from .models import Evidence, Recipe, ResolvedEdge
from .path_templates import normalize_endpoint_value


class EndpointResolver:
    """Propagates endpoint paths/methods through sink and wrapper call chains."""

    def __init__(self, facts: FactSet, bindings: BindingResolver, recipes: Iterable[Recipe] = ()) -> None:
        self.facts = facts
        self.bindings = bindings
        self.recipes = list(recipes)
        self.diagnostics: List[str] = []

    def resolve(self) -> List[ResolvedEdge]:
        edges: Dict[str, ResolvedEdge] = {}
        sink_functions = self._sink_functions()
        wrapper_functions = self._wrapper_functions()
        if not sink_functions and not wrapper_functions:
            return []

        def add(edge: ResolvedEdge) -> None:
            existing = edges.get(edge.id or "")
            if existing is None or len(edge.evidence) > len(existing.evidence) or (len(edge.evidence) == len(existing.evidence) and edge.confidence > existing.confidence):
                edges[edge.id or ""] = edge

        for call in self.facts.calls:
            callee = self._resolve_callee(call.function)
            if callee in sink_functions:
                if not call.args:
                    self.diagnostics.append(f"endpoint sink {callee!r} has no path argument")
                    continue
                ev = Evidence("endpoint_sink", f"{callee} receives endpoint argument", call.file, call.line, call.id)
                sink_method, sink_confidence = self._method_for_sink_call(call, callee)
                for endpoint, source, method, evidence in self._resolve_endpoint_value(call.caller, call.args[0]):
                    resolved_method = method or sink_method
                    confidence = 0.9 if resolved_method else min(0.7, sink_confidence)
                    edge = ResolvedEdge(
                        source,
                        endpoint,
                        "HTTP_CALLS",
                        confidence,
                        method=resolved_method,
                        path=endpoint,
                        evidence=[ev] + evidence,
                    )
                    add(edge)

            if callee in wrapper_functions and call.args:
                endpoint = self._normalize_path(call.args[0])
                if endpoint:
                    ev = Evidence("endpoint_wrapper", f"{callee} wrapper receives endpoint", call.file, call.line, call.id)
                    method = self._method_for_wrapper(callee)
                    edge = ResolvedEdge(
                        call.caller or "<module>",
                        endpoint,
                        "HTTP_CALLS",
                        0.92 if method else 0.72,
                        method=method,
                        path=endpoint,
                        evidence=[ev],
                    )
                    add(edge)
        return [edges[key] for key in sorted(edges)]

    def _endpoint_recipes(self) -> List[Recipe]:
        return [r for r in self.recipes if r.type in {"endpoint_sink", "wrapper_function", "path_builder"}]

    def _sink_functions(self) -> set[str]:
        sinks: set[str] = set()
        for recipe in self._endpoint_recipes():
            sinks.update(str(item) for item in recipe.sink_functions)
            sinks.update(str(item) for item in recipe.options.get("sink_functions", []))
        return sinks

    def _wrapper_functions(self) -> set[str]:
        wrappers: set[str] = set()
        for recipe in self._endpoint_recipes():
            wrappers.update(str(item) for item in recipe.wrapper_functions)
            wrappers.update(str(item) for item in recipe.method_by_wrapper.keys())
            wrappers.update(str(item) for item in recipe.options.get("wrapper_functions", []))
            if recipe.type == "wrapper_function" and recipe.options.get("function"):
                wrappers.add(str(recipe.options["function"]))
        return wrappers

    def _path_builder_functions(self) -> set[str]:
        builders: set[str] = set()
        for recipe in self._endpoint_recipes():
            builders.update(str(item) for item in recipe.path_builder_functions)
            builders.update(str(item) for item in recipe.options.get("path_builder_functions", []))
            if recipe.type == "path_builder":
                builders.update(str(item) for item in recipe.options.get("functions", []))
                if recipe.options.get("function"):
                    builders.add(str(recipe.options["function"]))
        return builders

    def _function_params(self) -> Dict[str, List[str]]:
        params: Dict[str, List[str]] = {}
        for fn in self.facts.functions:
            params[fn.name] = list(fn.params)
            if fn.qualified_name:
                params[fn.qualified_name] = list(fn.params)
        return params

    def _incoming_calls(self, function_name: str) -> List[Any]:
        result = []
        for call in self.facts.calls:
            callee = self._resolve_callee(call.function)
            if callee == function_name or call.function == function_name:
                result.append(call)
        return result

    def _resolve_endpoint_value(
        self,
        context_function: Optional[str],
        value: Any,
        depth: int = 0,
    ) -> List[Tuple[str, str, Optional[str], List[Evidence]]]:
        normalized = self._normalize_path(value)
        if normalized:
            source = context_function or "<module>"
            return [(normalized, source, None, [])]
        if not context_function or not isinstance(value, str) or depth > 12:
            return []

        params = self._function_params().get(context_function, [])
        if value not in params:
            resolved = self.bindings.resolve_name(value)
            normalized = self._normalize_path(resolved)
            if normalized:
                return [(normalized, context_function, None, [])]
            return []

        index = params.index(value)
        results: List[Tuple[str, str, Optional[str], List[Evidence]]] = []
        for incoming in self._incoming_calls(context_function):
            if index >= len(incoming.args):
                continue
            incoming_value = incoming.args[index]
            ev = Evidence(
                "wrapper_to_sink",
                f"{incoming.function}.{value} receives argument {index} from {incoming.caller}",
                incoming.file,
                incoming.line,
                incoming.id,
            )
            nested = self._resolve_endpoint_value(incoming.caller, incoming_value, depth + 1)
            if nested:
                for endpoint, source, method, evidence in nested:
                    method_override = method or self._method_for_wrapper(self._resolve_callee(incoming.function))
                    results.append((endpoint, incoming.caller or source, method_override, evidence + [ev]))
            else:
                normalized = self._normalize_path(incoming_value)
                if normalized:
                    results.append((normalized, incoming.caller or "<module>", self._method_for_wrapper(self._resolve_callee(incoming.function)), [ev]))
        return results

    def _resolve_callee(self, function: Optional[str]) -> Optional[str]:
        if not function:
            return None
        resolved = self.bindings.resolve_name(function)
        return resolved or function

    def _method_for_wrapper(self, wrapper: Optional[str]) -> Optional[str]:
        if not wrapper:
            return None
        for recipe in self._endpoint_recipes():
            if wrapper in recipe.method_by_wrapper:
                return str(recipe.method_by_wrapper[wrapper]).upper()
            if wrapper in recipe.options.get("method_by_wrapper", {}):
                return str(recipe.options["method_by_wrapper"][wrapper]).upper()
            if recipe.type == "wrapper_function" and recipe.options.get("function") == wrapper and recipe.options.get("method"):
                return str(recipe.options["method"]).upper()
        return None

    def _method_for_sink_call(self, call: Any, callee: Optional[str]) -> Tuple[Optional[str], float]:
        explicit = self._method_from_value(call.kwargs.get("method"))
        if explicit:
            return explicit, 0.94
        if len(call.args) > 1:
            explicit = self._method_from_value(call.args[1])
            if explicit:
                return explicit, 0.94
        for recipe in self._endpoint_recipes():
            if callee and callee in recipe.method_by_sink:
                return str(recipe.method_by_sink[callee]).upper(), 0.9
            mapping = recipe.options.get("method_by_sink", {})
            if callee and callee in mapping:
                return str(mapping[callee]).upper(), 0.9
        return None, 0.72

    def _method_from_value(self, value: Any) -> Optional[str]:
        if isinstance(value, str) and value:
            upper = value.upper()
            return upper if upper in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} else None
        if isinstance(value, dict):
            method = value.get("method") or value.get("Method")
            if isinstance(method, str) and method:
                return method.upper()
        return None

    def _normalize_path(self, value: Any) -> Optional[str]:
        return normalize_endpoint_value(value, self._path_builder_functions())
