from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from .models import Recipe


KNOWN_RECIPE_TYPES = {
    "object_graph",
    "endpoint_sink",
    "alias_import",
    "re_export",
    "wrapper_function",
    "path_builder",
    "returned_object",
    "provider_factory",
    "constructor_provider",
    "decorator_entrypoint",
    "call_chain_binding",
}


def load_recipes(path: str | Path) -> List[Recipe]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        items = data.get("recipes", [])
    elif isinstance(data, list):
        items = data
    else:
        raise TypeError("recipes JSON must be an array or an object with a recipes array")
    return [Recipe.from_dict(item) for item in items]


def validate_recipes(recipes: Iterable[Recipe]) -> List[str]:
    errors: List[str] = []
    for index, recipe in enumerate(recipes):
        if not recipe.id:
            errors.append(f"recipes[{index}].id is required")
        if not recipe.type:
            errors.append(f"recipes[{index}].type is required")
            continue
        if recipe.type not in KNOWN_RECIPE_TYPES:
            errors.append(f"recipes[{index}].type {recipe.type!r} is unknown")
            continue
        if recipe.type in {"object_graph", "decorator_entrypoint"}:
            if recipe.type == "object_graph" and not recipe.constructor and not recipe.options.get("constructor"):
                errors.append(f"recipes[{index}].constructor is required for object_graph")
            if not recipe.include_method and not recipe.options.get("include_method"):
                errors.append(f"recipes[{index}].include_method is required for {recipe.type}")
            if not recipe.decorator_methods and not recipe.options.get("decorator_methods"):
                errors.append(f"recipes[{index}].decorator_methods is required for {recipe.type}")
        if recipe.type == "endpoint_sink":
            if not recipe.sink_functions and not recipe.options.get("sink_functions"):
                errors.append(f"recipes[{index}].sink_functions is required for endpoint_sink")
        if recipe.type == "wrapper_function":
            has_mapping = bool(recipe.method_by_wrapper or recipe.options.get("method_by_wrapper"))
            has_pair = bool(recipe.options.get("function") and recipe.options.get("method"))
            if not (has_mapping or has_pair):
                errors.append(f"recipes[{index}] wrapper_function requires method_by_wrapper or options.function/options.method")
        if recipe.type == "path_builder":
            if not (recipe.path_builder_functions or recipe.options.get("functions") or recipe.options.get("function")):
                errors.append(f"recipes[{index}] path_builder requires functions or function")
        if recipe.type == "constructor_provider":
            if not recipe.providers:
                errors.append(f"recipes[{index}].providers is required for constructor_provider")
        if recipe.type == "provider_factory":
            if not recipe.constructor and not recipe.options.get("factory_functions"):
                errors.append(f"recipes[{index}] provider_factory requires constructor or options.factory_functions")
    return errors
