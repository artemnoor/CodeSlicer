from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .facts import FactSet
from .integration import semantic_result_to_graph_edges
from .models import ResolutionResult
from .recipes import load_recipes, validate_recipes
from .resolver import SemanticResolver
from .serialization import dump_json, dump_result, load_facts, load_json


def _emit(payload: Dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if payload.get("ok"):
            print(payload.get("message", "ok"))
        else:
            print(payload.get("message", "error"), file=sys.stderr)
            for error in payload.get("errors", []):
                print(f"- {error}", file=sys.stderr)


def cmd_resolve(args: argparse.Namespace) -> int:
    facts = load_facts(args.facts)
    recipes = load_recipes(args.recipes) if args.recipes else []
    fact_errors = facts.validate()
    recipe_errors = validate_recipes(recipes)
    if fact_errors or recipe_errors:
        _emit({"ok": False, "message": "validation failed", "errors": fact_errors + recipe_errors}, args.json)
        return 2
    result = SemanticResolver(facts, recipes).resolve()
    if args.out:
        dump_result(result, args.out)
    payload = {"ok": True, "message": "resolved", "summary": {
        "bindings": len(result.bindings),
        "dataflow": len(result.dataflow),
        "resolved_edges": len(result.resolved_edges),
        "diagnostics": len(result.diagnostics),
    }}
    if not args.out:
        payload["result"] = result.to_dict()
    _emit(payload, args.json)
    return 0



def cmd_resolve_fixture(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parent.parent / "fixtures"
    facts_path = root / f"{args.name}.facts.json"
    recipes_path = root / f"{args.name}.recipes.json"
    if not facts_path.exists() or not recipes_path.exists():
        _emit({"ok": False, "message": "fixture not found", "errors": [str(facts_path), str(recipes_path)]}, args.json)
        return 2
    resolve_args = argparse.Namespace(facts=str(facts_path), recipes=str(recipes_path), out=args.out, json=args.json)
    return cmd_resolve(resolve_args)

def cmd_validate_facts(args: argparse.Namespace) -> int:
    facts = load_facts(args.facts)
    errors = facts.validate()
    _emit({"ok": not errors, "message": "facts valid" if not errors else "facts invalid", "errors": errors}, args.json)
    return 0 if not errors else 2


def cmd_validate_recipes(args: argparse.Namespace) -> int:
    recipes = load_recipes(args.recipes)
    errors = validate_recipes(recipes)
    _emit({"ok": not errors, "message": "recipes valid" if not errors else "recipes invalid", "errors": errors}, args.json)
    return 0 if not errors else 2


def cmd_convert_to_graph(args: argparse.Namespace) -> int:
    result = ResolutionResult.from_dict(load_json(args.result))
    graph_edges = semantic_result_to_graph_edges(result)
    errors: List[str] = []
    for index, edge in enumerate(graph_edges):
        if not edge.get("evidence"):
            errors.append(f"graph_edges[{index}] evidence is required")
        if not edge.get("from_node") or not edge.get("to_node"):
            errors.append(f"graph_edges[{index}] from_node and to_node are required")
    if errors:
        _emit({"ok": False, "message": "graph conversion failed", "errors": errors}, args.json)
        return 2
    if args.out:
        dump_json(graph_edges, args.out)
    payload: Dict[str, Any] = {"ok": True, "message": "converted", "summary": {"edges": len(graph_edges)}}
    if not args.out:
        payload["edges"] = graph_edges
    _emit(payload, args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="semantic-binding")
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser("resolve", help="resolve normalized facts")
    resolve.add_argument("facts")
    resolve.add_argument("--recipes")
    resolve.add_argument("--out")
    resolve.add_argument("--json", action="store_true")
    resolve.set_defaults(func=cmd_resolve)


    fixture = sub.add_parser("resolve-fixture", help="resolve a bundled fixture by name")
    fixture.add_argument("name")
    fixture.add_argument("--out")
    fixture.add_argument("--json", action="store_true")
    fixture.set_defaults(func=cmd_resolve_fixture)

    validate_facts = sub.add_parser("validate-facts", help="validate facts JSON")
    validate_facts.add_argument("facts")
    validate_facts.add_argument("--json", action="store_true")
    validate_facts.set_defaults(func=cmd_validate_facts)

    validate_recipes = sub.add_parser("validate-recipes", help="validate recipes JSON")
    validate_recipes.add_argument("recipes")
    validate_recipes.add_argument("--json", action="store_true")
    validate_recipes.set_defaults(func=cmd_validate_recipes)

    convert = sub.add_parser("convert-to-graph", help="convert resolution result to Impact-compatible graph edges")
    convert.add_argument("result")
    convert.add_argument("--out")
    convert.add_argument("--json", action="store_true")
    convert.set_defaults(func=cmd_convert_to_graph)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
