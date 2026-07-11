from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List

from .extractor import extract_import_strings
from .models import ExtractedExample, FetchedPage, ResearchInputPack, ResearchRequest
from .support_pack_schema import empty_support_pack, rule_template


def build_research_input_pack(
    request: ResearchRequest,
    fetched_pages: Iterable[FetchedPage],
    examples: Iterable[ExtractedExample],
    diagnostics: List[str] | None = None,
) -> ResearchInputPack:
    pages = list(fetched_pages)
    examples_list = list(examples)
    fetched_source_excerpts = [
        {
            "url": p.source_url,
            "source_type": p.source_type,
            "title": p.title,
            "content_type": p.content_type,
            "excerpt": p.text_excerpt[:2000],
            "error": p.error,
            "bytes_read": p.bytes_read,
        }
        for p in pages
    ]
    return ResearchInputPack(
        library=request.library,
        ecosystem=request.ecosystem,
        version_range=request.version_range,
        detected_imports=extract_import_strings(examples_list),
        fetched_source_excerpts=fetched_source_excerpts,
        extracted_examples=[
            {
                "id": e.id,
                "source_url": e.source_url,
                "kind": e.kind,
                "language": e.language,
                "snippet": e.snippet,
                "signals": e.signals,
                "confidence": e.confidence,
                "context": e.context,
            }
            for e in examples_list
        ],
        diagnostics=diagnostics or [],
    )


class SupportPackGenerator:
    def generate_heuristic_draft(self, input_pack: ResearchInputPack) -> Dict[str, Any]:
        pack = empty_support_pack(input_pack.library, input_pack.ecosystem, input_pack.version_range)
        examples = input_pack.extracted_examples
        pack["imports"] = sorted(set(input_pack.detected_imports))
        pack["evidence_sources"] = _evidence_sources(input_pack)
        diagnostics = list(input_pack.diagnostics)
        rules: List[Dict[str, Any]] = []

        rules.extend(self._infer_fastapi_like_rules(input_pack, examples))
        rules.extend(self._infer_endpoint_sink_rules(input_pack, examples))
        rules.extend(self._infer_provider_factory_rules(input_pack, examples))
        rules.extend(self._infer_constructor_injection_rules(input_pack, examples))
        rules.extend(self._infer_component_rules(input_pack, examples))
        rules.extend(self._infer_test_rules(input_pack, examples))
        rules = _dedupe_rules(rules)
        if not rules:
            diagnostics.append("No support-pack rules inferred because extracted evidence was too weak. Use ai_prompt.md for manual/LLM-assisted generation.")
        if examples and len(rules) < 2:
            diagnostics.append("Only a small number of rules inferred; review evidence before installing this pack.")
        pack["rules"] = rules
        pack["confidence"] = _overall_confidence(rules, examples)
        pack["diagnostics"] = sorted(set(diagnostics))
        return _stable_json_roundtrip(pack)

    def build_ai_prompt(self, input_pack: ResearchInputPack) -> str:
        schema_hint = {
            "library": input_pack.library,
            "ecosystem": input_pack.ecosystem,
            "version_range": input_pack.version_range,
            "imports": ["..."],
            "rules": [
                {
                    "id": "stable_rule_id",
                    "type": "object_graph | endpoint_sink | provider_factory | ...",
                    "confidence": 0.0,
                    "evidence": [{"example_id": "ex_...", "source_url": "..."}],
                    "diagnostics": ["explain uncertainty when needed"],
                }
            ],
            "evidence_sources": [{"url": "...", "title": "...", "source_type": "..."}],
            "generated_by": {"tool": "external_ai", "mode": "ai_assisted"},
            "confidence": 0.0,
            "diagnostics": [],
        }
        return (
            "# AI Library Researcher handoff\n\n"
            "You are generating a conservative Impact Engine-style support_pack.json draft.\n"
            "Do not invent rules without evidence. Use low confidence when uncertain.\n\n"
            "## Required output schema shape\n\n"
            f"```json\n{json.dumps(schema_hint, indent=2, sort_keys=True)}\n```\n\n"
            "## Research input\n\n"
            f"```json\n{json.dumps(input_pack.__dict__, indent=2, sort_keys=True)}\n```\n"
        )

    def _infer_fastapi_like_rules(self, input_pack: ResearchInputPack, examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        text = _all_snippets(examples)
        library_slug = input_pack.library.lower().replace("_", "-")
        rules: List[Dict[str, Any]] = []
        api_router_examples = _examples_with(examples, ["APIRouter", "include_router", "@router."])
        if "APIRouter" in text or (library_slug == "fastapi" and "@router." in text):
            methods = sorted(set(re.findall(r"@(?:router|app)\.(get|post|put|delete|patch|head|options)\s*\(", text))) or ["get", "post", "put", "delete", "patch"]
            evidence = _evidence(api_router_examples[:4])
            confidence = 0.85 if "APIRouter" in text and "include_router" in text else 0.65
            rules.append(
                rule_template(
                    f"{_safe_id(input_pack.library)}_apirouter_object_graph",
                    "object_graph",
                    confidence,
                    evidence,
                    constructor="APIRouter",
                    prefix_kwarg="prefix",
                    include_method="include_router",
                    decorator_methods=methods,
                    diagnostics=[] if confidence >= 0.8 else ["APIRouter evidence found but router composition evidence is incomplete."],
                )
            )
        decorator_examples = _examples_with(examples, ["@router.", "@app.", "@GetMapping", "@PostMapping"])
        if decorator_examples:
            rules.append(
                rule_template(
                    f"{_safe_id(input_pack.library)}_decorator_entrypoints",
                    "decorator_entrypoint",
                    0.75,
                    _evidence(decorator_examples[:4]),
                    decorator_patterns=sorted(set(re.findall(r"@(\w+(?:\.\w+)?)", text)))[:20],
                    route_arg_index=0,
                    diagnostics=[],
                )
            )
        if "@GetMapping" in text or "@PostMapping" in text or "gin.Default" in text or "r.Get(" in text or "r.Post(" in text:
            route_examples = _examples_with(examples, ["@GetMapping", "@PostMapping", "gin.Default", "r.Get(", "r.Post("])
            rules.append(
                rule_template(
                    f"{_safe_id(input_pack.library)}_route_pattern",
                    "route_pattern",
                    0.7,
                    _evidence(route_examples[:4]),
                    route_decorators=sorted(set(re.findall(r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|RequestMapping)", text))),
                    function_patterns=["r.Get", "r.Post", "r.Put", "r.Delete"] if "r.Get(" in text or "r.Post(" in text else [],
                    diagnostics=["Generic route pattern inferred from framework examples; review exact method/path semantics."],
                )
            )
        return [r for r in rules if r.get("evidence")]

    def _infer_endpoint_sink_rules(self, input_pack: ResearchInputPack, examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        text = _all_snippets(examples)
        sink_functions = []
        if "fetch(" in text:
            sink_functions.append("fetch")
        if "axios." in text:
            sink_functions.append("axios")
        if not sink_functions:
            return []
        evidence = _evidence(_examples_with(examples, ["fetch(", "axios."])[:4])
        return [
            rule_template(
                f"{_safe_id(input_pack.library)}_endpoint_sink",
                "endpoint_sink",
                0.75 if len(sink_functions) > 1 else 0.65,
                evidence,
                sink_functions=sorted(set(sink_functions)),
                method_extraction="options.method or axios method name",
                url_arg_index=0,
                diagnostics=["Endpoint sink rule is generic and should be reviewed for wrappers/templates."],
            )
        ]

    def _infer_provider_factory_rules(self, input_pack: ResearchInputPack, examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        text = _all_snippets(examples)
        factories = sorted(set(re.findall(r"providers\.(Factory|Singleton|Callable|Resource)", text)))
        if not factories:
            return []
        evidence = _evidence(_examples_with(examples, ["providers.Factory", "providers.Singleton", "providers.Callable", "providers.Resource"])[:4])
        return [
            rule_template(
                f"{_safe_id(input_pack.library)}_provider_factory",
                "provider_factory",
                0.8 if "providers.Factory" in text or "providers.Singleton" in text else 0.6,
                evidence,
                factory_functions=[f"providers.{name}" for name in factories],
                provided_symbol_arg_index=0,
                dependency_kwargs=True,
                diagnostics=[],
            )
        ]

    def _infer_constructor_injection_rules(self, input_pack: ResearchInputPack, examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ci_examples = [e for e in examples if "constructor_injection" in e.get("signals", [])]
        if not ci_examples:
            return []
        return [
            rule_template(
                f"{_safe_id(input_pack.library)}_constructor_injection",
                "constructor_injection",
                0.65,
                _evidence(ci_examples[:4]),
                constructor_names=["__init__", "constructor"],
                assignment_pattern="self.<attr> = <param> / this.<attr> = <param>",
                diagnostics=["Constructor injection inferred from examples; type propagation must be confirmed by downstream analyzer."],
            )
        ]

    def _infer_component_rules(self, input_pack: ResearchInputPack, examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        component_examples = [e for e in examples if "component_usage" in e.get("signals", [])]
        if not component_examples:
            return []
        return [
            rule_template(
                f"{_safe_id(input_pack.library)}_component_usage",
                "component_usage",
                0.6,
                _evidence(component_examples[:4]),
                component_patterns=["<Component ...>", "use* hook calls"],
                diagnostics=["Component usage rule is intentionally generic."],
            )
        ]

    def _infer_test_rules(self, input_pack: ResearchInputPack, examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        test_examples = [e for e in examples if "test_target_pattern" in e.get("signals", [])]
        if not test_examples:
            return []
        text = _all_snippets(test_examples)
        methods = sorted(set(re.findall(r"client\.(get|post|put|delete|patch)\s*\(", text)))
        return [
            rule_template(
                f"{_safe_id(input_pack.library)}_test_target_pattern",
                "test_target_pattern",
                0.7,
                _evidence(test_examples[:4]),
                client_methods=methods,
                target_arg_index=0,
                diagnostics=[],
            )
        ]


def _evidence_sources(input_pack: ResearchInputPack) -> List[Dict[str, Any]]:
    by_url: Dict[str, Dict[str, Any]] = {}
    for page in input_pack.fetched_source_excerpts:
        by_url[page["url"]] = {
            "url": page["url"],
            "title": page.get("title", ""),
            "source_type": page.get("source_type", ""),
            "bytes_read": page.get("bytes_read", 0),
            "error": page.get("error"),
        }
    return [by_url[url] for url in sorted(by_url)]


def _all_snippets(examples: Iterable[Dict[str, Any]]) -> str:
    return "\n".join(str(e.get("snippet", "")) for e in examples)


def _examples_with(examples: List[Dict[str, Any]], needles: List[str]) -> List[Dict[str, Any]]:
    return [e for e in examples if any(n in str(e.get("snippet", "")) for n in needles)]


def _evidence(examples: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    return [{"example_id": str(e.get("id", "")), "source_url": str(e.get("source_url", ""))} for e in examples if e.get("id") and e.get("source_url")]


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "library"


def _dedupe_rules(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = {}
    for rule in rules:
        result[rule["id"]] = rule
    return [result[key] for key in sorted(result)]


def _overall_confidence(rules: List[Dict[str, Any]], examples: List[Dict[str, Any]]) -> float:
    if not rules:
        return 0.0
    avg = sum(float(r.get("confidence", 0.0)) for r in rules) / len(rules)
    if len(examples) < 3:
        avg = min(avg, 0.55)
    return round(avg, 2)


def _stable_json_roundtrip(data: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(data, sort_keys=True, ensure_ascii=False))
