"""Declarative HTTP wrapper resolution."""

from __future__ import annotations

from typing import Any

from .models import WrapperRecipe, WrapperResolution

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


def default_wrapper_recipes() -> list[WrapperRecipe]:
    """Built-in recipes for common HTTP call styles.

    Projects can add or override these through ``input_data["wrapper_recipes"]``.
    """

    return [
        WrapperRecipe("fetch", url_arg_index=0, options_arg_index=1, default_method="GET", confidence=0.82, description="native fetch"),
        WrapperRecipe("axios.get", method="GET", url_arg_index=0, confidence=0.88),
        WrapperRecipe("axios.post", method="POST", url_arg_index=0, confidence=0.89),
        WrapperRecipe("axios.put", method="PUT", url_arg_index=0, confidence=0.89),
        WrapperRecipe("axios.patch", method="PATCH", url_arg_index=0, confidence=0.89),
        WrapperRecipe("axios.delete", method="DELETE", url_arg_index=0, confidence=0.89),
        WrapperRecipe("httpClient.get", method="GET", url_arg_index=0, confidence=0.86),
        WrapperRecipe("httpClient.post", method="POST", url_arg_index=0, confidence=0.86),
        WrapperRecipe("httpClient.put", method="PUT", url_arg_index=0, confidence=0.86),
        WrapperRecipe("httpClient.patch", method="PATCH", url_arg_index=0, confidence=0.86),
        WrapperRecipe("httpClient.delete", method="DELETE", url_arg_index=0, confidence=0.86),
        WrapperRecipe("getJson", method="GET", url_arg_index=0, confidence=0.86),
        WrapperRecipe("postJson", method="POST", url_arg_index=0, confidence=0.88),
        WrapperRecipe("putJson", method="PUT", url_arg_index=0, confidence=0.86),
        WrapperRecipe("patchJson", method="PATCH", url_arg_index=0, confidence=0.86),
        WrapperRecipe("deleteJson", method="DELETE", url_arg_index=0, confidence=0.86),
        WrapperRecipe("request", method_arg_index=0, url_arg_index=1, confidence=0.84),
        WrapperRecipe("client.request", object_config_arg_index=0, confidence=0.84),
    ]


def build_recipes(custom: list[dict[str, Any]] | None = None) -> list[WrapperRecipe]:
    recipes = default_wrapper_recipes()
    for item in custom or []:
        recipes.append(WrapperRecipe.from_dict(item))
    return recipes


def _expr_literal_value(expr: Any) -> str | None:
    if isinstance(expr, str):
        return expr
    if isinstance(expr, dict):
        expr_type = expr.get("type") or expr.get("kind")
        if expr_type in {"literal", "string"}:
            value = expr.get("value")
            return None if value is None else str(value)
    return None


def _object_property(expr: Any, key: str) -> Any:
    if not isinstance(expr, dict):
        return None
    expr_type = expr.get("type") or expr.get("kind")
    if expr_type == "object":
        props = expr.get("properties", {}) or {}
        if isinstance(props, dict):
            return props.get(key)
        if isinstance(props, list):
            for prop in props:
                if prop.get("key") == key:
                    return prop.get("value")
    # Accept plain object literals as facts too.
    if key in expr and expr_type not in {"literal", "string", "ref", "call", "concat", "template"}:
        return expr.get(key)
    return None


def _method_from_expr(expr: Any) -> str | None:
    value = _expr_literal_value(expr)
    if not value:
        return None
    method = value.upper().strip()
    return method if method in HTTP_METHODS else None


def callee_matches(recipe_name: str, callee: str) -> bool:
    """Match exact wrapper names and member-call method suffixes safely."""

    if recipe_name == callee:
        return True
    # Allow a project-specific client instance such as api.post when a recipe is
    # expressed as httpClient.post or axios.post, but do not match arbitrary
    # function names by suffix alone.
    recipe_parts = recipe_name.split(".")
    callee_parts = callee.split(".")
    if len(recipe_parts) == 2 and len(callee_parts) == 2:
        recipe_obj, recipe_method = recipe_parts
        callee_obj, callee_method = callee_parts
        if recipe_method == callee_method and recipe_obj in {"httpClient", "client", "axios"} and callee_obj in {"httpClient", "client", "axios", "apiClient"}:
            return True
    return False


class WrapperResolver:
    """Resolve HTTP method and URL expression from wrapper call facts."""

    def __init__(self, recipes: list[WrapperRecipe] | None = None):
        self.recipes = recipes or default_wrapper_recipes()

    @classmethod
    def from_input(cls, input_data: dict[str, Any]) -> "WrapperResolver":
        return cls(build_recipes(input_data.get("wrapper_recipes", [])))

    def resolve_call(self, call_fact: dict[str, Any]) -> WrapperResolution | None:
        callee = str(call_fact.get("callee") or call_fact.get("name") or "")
        args = call_fact.get("args", []) or []
        candidates: list[WrapperResolution] = []
        for recipe in self.recipes:
            if not callee_matches(recipe.wrapper_name, callee):
                continue
            resolved = self._apply_recipe(recipe, callee, args)
            if resolved is not None:
                candidates.append(resolved)
        if not candidates:
            return None
        signatures = {(item.method, repr(item.url_expr)) for item in candidates}
        if len(signatures) > 1:
            # Conflicting recipes are an ambiguity, never a confirmed HTTP
            # call. Keep one candidate for diagnostics but force the quality
            # layer to quarantine the resulting endpoint edge.
            selected = candidates[0]
            return WrapperResolution(
                method=selected.method,
                url_expr=selected.url_expr,
                confidence=0.40,
                evidence=[*selected.evidence, "ambiguous wrapper recipes"],
                warnings=[*selected.warnings, "multiple wrapper recipes resolve this call"],
            )
        return candidates[0]

    def _apply_recipe(self, recipe: WrapperRecipe, callee: str, args: list[Any]) -> WrapperResolution | None:
        evidence = [f"wrapper:{callee}", f"recipe:{recipe.wrapper_name}"]
        warnings: list[str] = []

        method: str | None = recipe.method.upper() if recipe.method else None
        url_expr: Any = None

        if recipe.method_arg_index is not None:
            if recipe.method_arg_index >= len(args):
                return None
            method = _method_from_expr(args[recipe.method_arg_index])
            if method is None:
                warnings.append("method argument is not a static HTTP method")

        if recipe.url_arg_index is not None:
            if recipe.url_arg_index >= len(args):
                return None
            url_expr = args[recipe.url_arg_index]

        if recipe.object_config_arg_index is not None:
            if recipe.object_config_arg_index >= len(args):
                return None
            config = args[recipe.object_config_arg_index]
            url_expr = _object_property(config, recipe.url_object_key)
            method = method or _method_from_expr(_object_property(config, recipe.method_object_key))
            if url_expr is None:
                return None

        if recipe.options_arg_index is not None and recipe.options_arg_index < len(args):
            options = args[recipe.options_arg_index]
            method = _method_from_expr(_object_property(options, recipe.method_object_key)) or method

        method = method or (recipe.default_method.upper() if recipe.default_method else None)
        if method is None:
            warnings.append("HTTP method unresolved")
            return None
        if url_expr is None:
            return None

        confidence = recipe.confidence
        if warnings:
            confidence = min(confidence, 0.62)
        return WrapperResolution(method=method, url_expr=url_expr, confidence=confidence, evidence=evidence, warnings=warnings)
