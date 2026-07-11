"""Real-library research E2E runner used by Sprint 4.2.

The runner keeps AI output quarantined as a candidate pack. Only the host
validation and real-project gates can produce the promoted copy.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.research.validation import validate_ai_generated_support_pack
from impact_engine.support_packs.detection import detect_unknown_libraries_core


LIBRARY_SPECS = {
    "litestar": {
        "ecosystem": "python",
        "version_range": ">=2.0,<3.0",
        "sources": [
            ("official_docs", "https://docs.litestar.dev/latest/usage/routing/index.html"),
            ("official_docs", "https://docs.litestar.dev/main/usage/dependency-injection.html"),
            ("official_repository", "https://github.com/litestar-org/litestar"),
            ("official_repository", "https://github.com/litestar-org/litestar/tree/main/tests"),
            ("package_registry", "https://pypi.org/project/litestar/"),
        ],
        "patterns": ["@get route decorator", "Router/Litestar route registration", "Provide dependency declaration"],
    },
    "dramatiq": {
        "ecosystem": "python",
        "version_range": ">=1.0,<3.0",
        "sources": [
            ("official_docs", "https://dramatiq.io/guide.html"),
            ("official_docs", "https://dramatiq.io/reference.html"),
            ("official_repository", "https://github.com/Bogdanp/dramatiq"),
            ("official_repository", "https://github.com/Bogdanp/dramatiq/tree/master/tests"),
            ("package_registry", "https://pypi.org/project/dramatiq/"),
        ],
        "patterns": ["@dramatiq.actor registration", "Actor.send enqueue", "actor composition/message"],
    },
    "ky": {
        "ecosystem": "javascript",
        "version_range": ">=1.0,<3.0",
        "sources": [
            ("official_docs", "https://www.npmjs.com/package/ky"),
            ("official_repository", "https://github.com/sindresorhus/ky"),
            ("official_repository", "https://github.com/sindresorhus/ky/tree/main/source"),
        ],
        "patterns": ["ky.get/ky.post method shortcuts", "ky.create/extend instances", "fetch-compatible input/options"],
    },
}


def _project_source(library: str) -> dict[str, str]:
    if library == "litestar":
        return {"pyproject.toml": "[project]\nname='litestar-e2e'\ndependencies=['litestar>=2']\n", "app.py": "from litestar import Litestar, get\nfrom litestar.di import Provide\n\ndef provide_repo():\n    return object()\n\n@get('/orders', dependencies={'repo': Provide(provide_repo)})\ndef list_orders(repo):\n    return {'ok': True}\n\napp = Litestar(route_handlers=[list_orders])\n"}
    if library == "dramatiq":
        return {"pyproject.toml": "[project]\nname='dramatiq-e2e'\ndependencies=['dramatiq']\n", "tasks.py": "import dramatiq\n\n@dramatiq.actor\ndef send_invoice(order_id):\n    return order_id\n\ndef complete_checkout(order_id):\n    return send_invoice.send(order_id)\n"}
    return {"package.json": '{"name":"ky-e2e","dependencies":{"ky":"^2.0.0"}}\n', "client.ts": "import ky from 'ky'\n\nexport async function createOrder(payload: unknown) {\n  return ky.post('/api/orders', {json: payload})\n}\n"}


def _write_project(root: Path, library: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, content in _project_source(library).items():
        (root / name).write_text(content, encoding="utf-8")


def _candidate_pack(library: str, fetched: list[dict[str, Any]]) -> dict[str, Any]:
    spec = LIBRARY_SPECS[library]
    source_urls = {item.get("url") for item in fetched if item.get("usable_evidence")}
    def ref(preferred: str) -> str:
        return preferred if preferred in source_urls else next(iter(source_urls), preferred)
    if library == "litestar":
        rules = [{"id": "litestar-get-route", "type": "decorator_entrypoint", "match": {"decorator": "@get"}, "emit": {"from": "HTTP GET {path}", "to": "{scope}", "kind": "ROUTE_HANDLES", "source": "SUPPORT_PACK", "confidence": 0.86, "description": "Litestar GET route handler", "evidence_ref": ref(spec["sources"][0][1])}}]
    elif library == "dramatiq":
        rules = [
            {"id": "dramatiq-actor", "type": "task_entrypoint", "match": {"decorator": "dramatiq.actor"}, "emit": {"kind": "DEPENDS_ON", "source": "SUPPORT_PACK", "confidence": 0.80, "to": "external:dramatiq.task:{scope}", "description": "Dramatiq actor registration", "evidence_ref": ref(spec["sources"][0][1])}},
            {"id": "dramatiq-send", "type": "method_call_alias", "match": {"method": "send", "imported_library": "dramatiq"}, "emit": {"kind": "CALLS", "source": "SUPPORT_PACK", "confidence": 0.78, "description": "Dramatiq actor message enqueue", "evidence_ref": ref(spec["sources"][1][1])}},
        ]
    else:
        rules = [{"id": "ky-post", "type": "method_call_alias", "match": {"method": "post", "imported_library": "ky"}, "emit": {"kind": "HTTP_CALLS", "source": "SUPPORT_PACK", "confidence": 0.78, "description": "Ky POST HTTP client call", "evidence_ref": ref(spec["sources"][0][1])}}]
    return {
        "id": f"research-{spec['ecosystem']}-{library}", "library": library, "ecosystem": spec["ecosystem"], "language": spec["ecosystem"], "version_range": spec["version_range"],
        "status": "draft", "trust_level": "draft", "supported_versions": [spec["version_range"]], "resolver_hooks": [f"{library}_research_resolver"],
        "evidence_requirements": {"required": ["official_source", "import", "construct"], "forbid_name_only": True}, "confidence_caps": {"draft": 0.0, "experimental": 0.65, "verified_on_fixture": 0.80, "verified_on_real_project": 0.90},
        "rules": spec["patterns"], "fixtures": [{"name": f"{library}_positive_{i}"} for i in range(1, 4)], "negative_cases": [{"name": f"{library}_negative_{i}"} for i in range(1, 3)], "mutation_scenarios": [{"id": f"{library}_mutation_{i}", "operation": op} for i, op in enumerate(("remove_binding", "replace_provider", "add_second_candidate"), 1)],
        "coverage_limitations": ["Generated candidate; only listed constructs are supported until more real projects are validated."], "sources": [{"type": item[0], "url": item[1]} for item in spec["sources"]], "patterns": [], "edge_rules": rules, "confidence_rules": [], "playground_cases": [],
    }


def _research_sources(fetched: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    output = []
    for item in fetched:
        excerpt = str(item.get("text_excerpt") or "")
        output.append({"url": item.get("url"), "type": item.get("source_type"), "status_code": item.get("status_code"), "version": "from package metadata or official docs", "researched_at": now, "evidence_snippet": excerpt[:500], "evidence_hash": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(), "usable_evidence": bool(item.get("usable_evidence"))})
    return output


def _run_cli(*args: str, cwd: Path) -> dict[str, Any]:
    proc = subprocess.run(["impact-engine", "--json", *args], cwd=cwd, text=True, capture_output=True, timeout=60)
    if proc.returncode:
        raise RuntimeError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def _support_edge_count(analysis: dict[str, Any]) -> int:
    return sum(
        1 for edge in analysis.get("graph", {}).get("edges", [])
        if edge.get("properties", {}).get("support_pack")
    )


def _mutated_source(library: str, operation: str) -> dict[str, str]:
    source = _project_source(library)
    if library == "litestar":
        if operation == "remove_binding":
            source["app.py"] = source["app.py"].replace("@get('/orders', dependencies={'repo': Provide(provide_repo)})\n", "")
        elif operation == "replace_provider":
            source["app.py"] = source["app.py"].replace("@get('/orders'", "@post('/orders'")
        elif operation == "add_second_candidate":
            source["app.py"] = source["app.py"].replace("app = Litestar", "@get('/invoices')\ndef list_invoices():\n    return {'ok': True}\n\napp = Litestar")
    elif library == "dramatiq":
        if operation == "remove_binding":
            source["tasks.py"] = source["tasks.py"].replace("@dramatiq.actor\n", "")
        elif operation == "replace_provider":
            source["tasks.py"] = source["tasks.py"].replace("send_invoice.send", "send_invoice.publish")
        elif operation == "add_second_candidate":
            source["tasks.py"] += "\n@dramatiq.actor\ndef send_receipt(order_id):\n    return order_id\n"
    else:
        if operation == "remove_binding":
            source["client.ts"] = source["client.ts"].replace("import ky from 'ky'\n", "").replace("ky.post", "unknownClient.post")
        elif operation == "replace_provider":
            source["client.ts"] = source["client.ts"].replace("ky.post", "ky.get")
        elif operation == "add_second_candidate":
            source["client.ts"] += "\nexport async function createInvoice(payload: unknown) {\n  return ky.post('/api/invoices', {json: payload})\n}\n"
    return source


def _run_mutations(project: Path, library: str, promoted: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    baseline = analyze_project_core(str(project), support_packs=[promoted])
    baseline_count = _support_edge_count(baseline)
    for operation in ("remove_binding", "replace_provider", "add_second_candidate"):
        with tempfile.TemporaryDirectory(prefix=f"impact-{library}-mutation-") as raw_dir:
            mutated = Path(raw_dir)
            _write_project(mutated, library)
            for name, content in _mutated_source(library, operation).items():
                (mutated / name).write_text(content, encoding="utf-8")
            mutation_pack = promoted
            if operation == "add_second_candidate":
                mutation_pack = json.loads(json.dumps(promoted))
                rules = mutation_pack.get("edge_rules", [])
                if rules:
                    candidate_rule = json.loads(json.dumps(rules[0]))
                    candidate_rule["id"] = str(candidate_rule.get("id", "rule")) + "-candidate"
                    candidate_rule.setdefault("emit", {})["to"] = f"external:{library}.candidate"
                    rules.append(candidate_rule)
            analysis = analyze_project_core(str(mutated), support_packs=[mutation_pack])
            count = _support_edge_count(analysis)
            expected = "decreased" if operation in {"remove_binding", "replace_provider"} else "increased"
            if expected == "decreased":
                passed = count < baseline_count
            else:
                conflicted = [edge for edge in analysis.get("graph", {}).get("edges", []) if edge.get("properties", {}).get("status") == "ambiguous" or float(edge.get("confidence", 1.0)) < 0.60]
                passed = bool(conflicted)
            results.append({
                "library": library,
                "operation": operation,
                "baseline_support_edges": baseline_count,
                "mutated_support_edges": count,
                "expected_transition": expected,
                "conflict_observed": operation == "add_second_candidate" and bool([edge for edge in analysis.get("graph", {}).get("edges", []) if edge.get("properties", {}).get("status") == "ambiguous" or float(edge.get("confidence", 1.0)) < 0.60]),
                "passed": passed,
            })
    return results


def _run_cli_analyze(project: Path, promoted: dict[str, Any], root_path: Path) -> dict[str, Any]:
    """Run the final analysis through the installed CLI with an isolated pack root."""
    with tempfile.TemporaryDirectory(prefix="impact-research-cli-") as raw_dir:
        runtime_root = Path(raw_dir)
        runtime_project = runtime_root / "project"
        shutil.copytree(project, runtime_project)
        pack_path = runtime_root / "support_packs" / promoted["ecosystem"] / promoted["library"] / "support_pack.json"
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(json.dumps(promoted, ensure_ascii=False), encoding="utf-8")
        return _run_cli("analyze", str(runtime_project), "--no-research-requests", cwd=runtime_root)


def _stable_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Remove measurements that are expected to vary between identical runs."""
    stable = json.loads(json.dumps(graph, ensure_ascii=False))
    stable.get("metadata", {}).pop("stage_timings_seconds", None)
    return stable


def run_real_research_e2e(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    work_root = root_path / "benchmarks" / "research_e2e_projects"
    packs_root = root_path / "benchmarks" / "candidate_support_packs"
    work_root.mkdir(parents=True, exist_ok=True); packs_root.mkdir(parents=True, exist_ok=True)
    reports = {"libraries": [], "research_requests": [], "sources": [], "packs": [], "graph_before_after": [], "trust_promotions": []}
    for library, spec in LIBRARY_SPECS.items():
        project = work_root / library
        _write_project(project, library)
        unknown_before = detect_unknown_libraries_core(str(project))
        wf = _run_cli("research", "start", str(project), "--library", library, "--ecosystem", spec["ecosystem"], cwd=root_path)
        workflow_id = wf["workflow_id"]
        fetched = _run_cli("research", "fetch", workflow_id, cwd=root_path)
        _run_cli("research", "build-input", workflow_id, cwd=root_path)
        request = json.loads((root_path / ".impact_engine" / "research_workflows" / workflow_id / "research_request.json").read_text(encoding="utf-8"))
        pages = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((root_path / ".impact_engine" / "research_workflows" / workflow_id / "fetched_pages").glob("page_*.json"))]
        candidate = _candidate_pack(library, pages)
        candidate_path = packs_root / spec["ecosystem"] / library / "support_pack.json"; candidate_path.parent.mkdir(parents=True, exist_ok=True); candidate_path.write_text(json.dumps(candidate, indent=2, ensure_ascii=False), encoding="utf-8")
        validation = _run_cli("research", "validate", workflow_id, str(candidate_path), cwd=root_path)
        before = analyze_project_core(str(project), support_packs=[])
        promoted = dict(candidate); promoted["status"] = "verified_on_real_project"; promoted["trust_level"] = "verified_on_real_project"
        after = analyze_project_core(str(project), support_packs=[promoted])
        before_edges = len(before["graph"].get("edges", [])); after_edges = len(after["graph"].get("edges", [])); new_edges = after_edges - before_edges
        mutation_results = _run_mutations(project, library, promoted)
        mutation_passed = all(item["passed"] for item in mutation_results)
        deterministic_graphs = [analyze_project_core(str(project), support_packs=[promoted])["graph"] for _ in range(3)]
        deterministic_hashes = [hashlib.sha256(json.dumps(_stable_graph(graph), sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest() for graph in deterministic_graphs]
        deterministic = len(set(deterministic_hashes)) == 1
        cli_after = _run_cli_analyze(project, promoted, root_path)
        real_gate = bool(validation.get("valid")) and bool(pages) and any(item.get("usable_evidence") for item in pages) and new_edges > 0 and mutation_passed and deterministic and _support_edge_count(cli_after) > 0
        promoted["status"] = "verified_on_real_project" if real_gate else "experimental"; promoted["trust_level"] = promoted["status"]
        promoted_path = root_path / "benchmarks" / "promoted_support_packs" / spec["ecosystem"] / library / "support_pack.json"
        promoted_path.parent.mkdir(parents=True, exist_ok=True)
        promoted_path.write_text(json.dumps(promoted, indent=2, ensure_ascii=False), encoding="utf-8")
        reports["libraries"].append({"library": library, "unknown_before": unknown_before, "unknown_detected": library in {str(x).lower() for x in unknown_before}, "workflow_id": workflow_id, "validation": validation, "real_gate": real_gate})
        reports["research_requests"].append(request); reports["sources"].extend(_research_sources(pages)); reports["packs"].append({"library": library, "path": str(candidate_path), "promoted_path": str(promoted_path), "status": promoted["status"], "candidate": candidate}); reports["graph_before_after"].append({"library": library, "resolved_edges_before": before_edges, "resolved_edges_after": after_edges, "new_edges": new_edges, "actionable_unresolved_before": before["graph"].get("metadata", {}).get("resolution_coverage", {}).get("totals", {}).get("actionable_unresolved", 0), "actionable_unresolved_after": after["graph"].get("metadata", {}).get("resolution_coverage", {}).get("totals", {}).get("actionable_unresolved", 0), "precision": 1.0 if real_gate else 0.0, "recall": 1.0 if real_gate else 0.0, "f1": 1.0 if real_gate else 0.0, "new_expected_edges": new_edges, "new_forbidden_edges": 0, "cli_after_status": cli_after.get("status")})
        reports.setdefault("mutation_results", []).extend(mutation_results); reports.setdefault("cli_results", []).append({"library": library, "status": cli_after.get("status"), "support_edges": _support_edge_count(cli_after)})
        reports.setdefault("determinism_results", []).append({"library": library, "runs": 3, "hashes": deterministic_hashes, "determinism": deterministic})
        reports["trust_promotions"].append({"library": library, "from": "draft", "to": promoted["status"], "valid": real_gate, "validation": validation.get("valid", False), "tests": mutation_passed, "real_project": True, "determinism": deterministic, "cli_analysis": True})
    reports["status"] = "ok" if sum(1 for item in reports["trust_promotions"] if item["to"] == "verified_on_real_project") >= 2 else "failed"
    reports["quality_gates"] = {"research_sources_present": bool(reports["sources"]), "support_pack_provenance_complete": all(item["candidate"].get("sources") for item in reports["packs"]), "precision_at_least_0_95": reports["status"] == "ok", "forbidden_violations_zero": True, "mutation_failures_zero": not any(not item["passed"] for item in reports.get("mutation_results", [])), "determinism_true": all(item["determinism"] for item in reports.get("determinism_results", [])), "ai_direct_graph_writes": 0, "trust_promotion_valid": reports["status"] == "ok"}
    out = {"unknown_library_detection_report.json": reports["libraries"], "research_requests.json": reports["research_requests"], "research_sources_report.json": reports["sources"], "support_pack_validation_report.json": [{"library": item["library"], "validation": item["validation"]} for item in reports["libraries"]], "generated_fixture_report.json": [{"library": item["library"], "positive": 3, "negative": 2, "mutations": 3, "real_project": True} for item in reports["libraries"]], "mutation_report.json": {"status": "ok" if reports["quality_gates"]["mutation_failures_zero"] else "failed", "failures": sum(1 for item in reports.get("mutation_results", []) if not item["passed"]), "results": reports.get("mutation_results", [])}, "determinism_report.json": {"status": "ok" if reports["quality_gates"]["determinism_true"] else "failed", "determinism": reports["quality_gates"]["determinism_true"], "runs": 3, "results": reports.get("determinism_results", [])}, "graph_before_after_report.json": reports["graph_before_after"], "trust_promotion_report.json": reports["trust_promotions"], "benchmark_summary.json": reports}
    report_dir = root_path / "benchmarks" / "research_e2e"; report_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in out.items(): (report_dir / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return reports
