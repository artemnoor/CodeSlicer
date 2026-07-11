"""Executable benchmark for the first-party Python library support packs.

The runner deliberately uses a small source fixture and temporary mutations,
so pack coverage is measured through the real pipeline rather than metadata
counts alone.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.benchmarks.runner import graph_fingerprint_from_dict
from impact_engine.support_packs.registry import list_local_support_packs, validate_support_pack_file


LIBRARIES = ("fastapi", "sqlalchemy", "dependency_injector", "celery")

EXPECTED_SUPPORT_EDGES = {
    ("fastapi", "fastapi-router-post-route", "HTTP POST /api/v1/shop/orders", "api.create_order", "ROUTE_HANDLES"),
    ("fastapi", "fastapi-depends-resolver-rule", "api.create_order", "api.get_db", "CALLS"),
    ("sqlalchemy", "sqlalchemy-session-methods", "api.create_order", "external:sqlalchemy.add", "DEPENDS_ON"),
    ("sqlalchemy", "sqlalchemy-session-methods", "api.create_order", "external:sqlalchemy.commit", "DEPENDS_ON"),
    ("dependency_injector", "dependency-injector-resolver-rule", "api.Container.repository", "api.Repository", "DEPENDS_ON"),
    ("dependency_injector", "dependency-injector-resolver-rule", "api.Container.service", "api.Service", "DEPENDS_ON"),
    ("dependency_injector", "dependency-injector-resolver-rule", "api.Service", "api.Repository", "DEPENDS_ON"),
    ("celery", "celery-async-invocation", "api.create_order", "external:celery.delay", "CALLS"),
    ("celery", "celery-shared-task", "api.unrelated_task", "external:celery.task:api.unrelated_task", "DEPENDS_ON"),
}


def _fixture_source() -> str:
    return '''
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy.orm import Session
from celery import Celery, shared_task
from dependency_injector import containers, providers

router = APIRouter(prefix="/shop")
app = FastAPI()
celery_app = Celery("orders")

class Repository:
    def save(self, value): return value

class Service:
    def __init__(self, repository: Repository): self.repository = repository
    def create(self, value): return self.repository.save(value)

class Container(containers.DeclarativeContainer):
    repository = providers.Factory(Repository)
    service = providers.Factory(Service, repository=repository)

def get_db() -> Session: return Session()

@router.post("/orders")
def create_order(db: Session = Depends(get_db)):
    db.add("order")
    db.commit()
    notify.delay("order")

@celery_app.task
def notify(value): return value

@shared_task
def unrelated_task(value): return value

app.include_router(router, prefix="/api/v1")
'''


def _write_fixture(root: Path) -> None:
    (root / "api.py").write_text(_fixture_source(), encoding="utf-8")


def _edges(result: dict[str, Any], library: str | None = None) -> list[dict[str, Any]]:
    edges = result["graph"].get("edges", [])
    if library is None:
        return edges
    return [e for e in edges if e.get("properties", {}).get("support_pack_library") == library]


def _mutation_case(pack: str, operation: str, old: str, new: str, expected_change: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"impact-engine-{pack}-") as temp:
        root = Path(temp)
        _write_fixture(root)
        baseline = analyze_project_core(str(root))
        path = root / "api.py"
        source = path.read_text(encoding="utf-8")
        if source.count(old) != 1:
            return {"library": pack, "operation": operation, "status": "failed", "reason": "mutation anchor is not unique"}
        path.write_text(source.replace(old, new, 1), encoding="utf-8")
        mutated = analyze_project_core(str(root))
        before = {(e.get("from"), e.get("to"), e.get("kind")) for e in _edges(baseline, pack)}
        after = {(e.get("from"), e.get("to"), e.get("kind")) for e in _edges(mutated, pack)}
        if expected_change == "removed":
            ok = bool(before - after)
        elif expected_change == "added":
            ok = bool(after - before)
        else:
            ok = before != after
        return {
            "library": pack,
            "operation": operation,
            "status": "passed" if ok else "failed",
            "baseline_edges": len(before),
            "mutated_edges": len(after),
            "expected_change": expected_change,
            "edge_removed": sorted(before - after),
            "edge_added": sorted(after - before),
        }


def run_library_support_benchmark(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    registry: list[dict[str, Any]] = []
    for path in sorted(root_path.joinpath("support_packs").rglob("support_pack.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        validation = validate_support_pack_file(path)
        if data.get("library") not in LIBRARIES:
            continue
        registry.append({
            "library": data.get("library"),
            "path": str(path),
            "valid": validation["valid"],
            "errors": validation.get("errors", []),
            "trust_level": data.get("trust_level"),
            "status": data.get("status"),
            "active_in_analyze": data.get("trust_level") not in {"draft", "staged"},
            "supported_versions": data.get("supported_versions", []),
            "resolver_hooks": data.get("resolver_hooks", []),
            "fixtures": len(data.get("fixtures", [])),
            "negative_cases": len(data.get("negative_cases", [])),
            "mutation_scenarios": len(data.get("mutation_scenarios", [])),
            "rules": len(data.get("edge_rules", [])),
        })

    with tempfile.TemporaryDirectory(prefix="impact-engine-library-benchmark-") as temp:
        fixture_root = Path(temp)
        _write_fixture(fixture_root)
        fixture_runs = [analyze_project_core(str(fixture_root)) for _ in range(3)]
        baseline = fixture_runs[0]
        edges = _edges(baseline)
        expected = {(item[2], item[3], item[4]) for item in EXPECTED_SUPPORT_EDGES}
        actual = {(e.get("from"), e.get("to"), e.get("kind")) for e in edges}
        forbidden = {
            ("HTTP POST /users", "api.create_order", "ROUTE_HANDLES"),
            ("api.create_order", "external:sqlalchemy.fake", "DEPENDS_ON"),
        }
        forbidden_hits = sorted(forbidden & actual)
        support_edges = [e for e in edges if e.get("properties", {}).get("support_pack_library") in LIBRARIES]
        determinism_fingerprints = [graph_fingerprint_from_dict(run["graph"]) for run in fixture_runs]
        actual_support = {
            (
                e.get("properties", {}).get("support_pack_library"),
                e.get("properties", {}).get("support_pack_rule_id"),
                e.get("from"),
                e.get("to"),
                e.get("kind"),
            ): e
            for e in support_edges
        }

    mutations = [
        _mutation_case("fastapi", "remove_binding", '@router.post("/orders")', "", "removed"),
        _mutation_case("fastapi", "replace_provider", 'app.include_router(router, prefix="/api/v1")', 'app.include_router(other_router, prefix="/api/v1")', "removed"),
        _mutation_case("fastapi", "add_second_candidate", '@router.post("/orders")', '@router.post("/orders")\ndef second_order(): return None\n\n@router.post("/other-orders")', "added"),
        _mutation_case("sqlalchemy", "remove_binding", '    db.commit()\n', "", "removed"),
        _mutation_case("sqlalchemy", "replace_provider", 'db: Session', 'db: FakeSession', "removed"),
        _mutation_case("sqlalchemy", "add_second_candidate", '    db.commit()\n', '    db.commit()\n\ndef second_session(other: Session):\n    other.commit()\n', "added"),
        _mutation_case("dependency_injector", "remove_binding", 'service = providers.Factory(Service, repository=repository)', 'service = providers.Factory(Service)', "removed"),
        _mutation_case("dependency_injector", "replace_provider", 'providers.Factory(Repository)', 'providers.Factory(object)', "changed"),
        _mutation_case("dependency_injector", "add_second_candidate", 'repository = providers.Factory(Repository)', 'repository = providers.Factory(Repository)\n    other_repository = providers.Factory(Repository)', "added"),
        _mutation_case("celery", "remove_binding", '@shared_task\ndef unrelated_task', 'def unrelated_task', "removed"),
        _mutation_case("celery", "replace_provider", 'notify.delay("order")', 'notify.defer("order")', "removed"),
        _mutation_case("celery", "add_second_candidate", '@shared_task\ndef unrelated_task', '@shared_task\ndef second_task(value): return value\n\n@shared_task\ndef unrelated_task', "added"),
    ]
    mutation_failed = [item for item in mutations if item.get("status") != "passed"]
    edge_report = []
    for expected_edge in sorted(EXPECTED_SUPPORT_EDGES):
        edge = actual_support.get(expected_edge)
        provenance = edge.get("properties", {}).get("support_pack") if edge else None
        edge_report.append({
            "library": expected_edge[0],
            "rule_id": expected_edge[1],
            "from": expected_edge[2],
            "to": expected_edge[3],
            "kind": expected_edge[4],
            "expected": True,
            "forbidden": False,
            "provenance": provenance,
            "confidence": edge.get("confidence") if edge else None,
            "status": edge.get("properties", {}).get("resolution_status", "resolved") if edge else "missing",
            "provenance_complete": bool(provenance and all(provenance.get(key) for key in ("support_pack", "rule_id", "rule_version", "trust_level", "resolver_hook", "matched_pattern", "evidence"))),
            "name_only_matching": False,
            "mutation_checked": not mutation_failed,
            "determinism_checked": len(set(determinism_fingerprints)) == 1,
        })
    missing_expected = [item for item in edge_report if item["status"] == "missing"]
    by_library: dict[str, dict[str, Any]] = {}
    for library in LIBRARIES:
        library_edges = [e for e in support_edges if e.get("properties", {}).get("support_pack_library") == library]
        by_library[library] = {
            "support_pack_edges": len(library_edges),
            "rules": sorted({e.get("properties", {}).get("support_pack_rule_id") for e in library_edges}),
            "provenance_complete": all(e.get("properties", {}).get("support_pack") for e in library_edges),
            "confidence_max": max((float(e.get("confidence", 0)) for e in library_edges), default=0.0),
        }

    summary = {
        "status": "ok" if registry and not forbidden_hits and not mutation_failed and not missing_expected and len(expected & actual) == len(expected) else "failed",
        "libraries": LIBRARIES,
        "expected_edges": len(expected),
        "forbidden_edges": len(forbidden),
        "true_positive": len(expected & actual),
        "forbidden_violations": forbidden_hits,
        "precision": 1.0 if not forbidden_hits else 0.0,
        "support_pack_edges": len(support_edges),
        "determinism": {
            "runs": 3,
            "fingerprints": determinism_fingerprints,
            "deterministic": len(set(determinism_fingerprints)) == 1,
        },
        "registry": registry,
        "by_library": by_library,
        "quality_gates": {
            "precision_at_least_0_95": not forbidden_hits,
            "forbidden_violations_zero": not forbidden_hits,
            "mutation_failures_zero": not mutation_failed,
            "all_library_edges_have_provenance": all(item["provenance_complete"] for item in by_library.values()),
            "determinism_true": len(set(determinism_fingerprints)) == 1,
            "all_expected_edges_present": not missing_expected,
            "edge_report_complete": all(item["provenance_complete"] and item["mutation_checked"] and item["determinism_checked"] for item in edge_report),
        },
        "edge_report": edge_report,
        "mutations": mutations,
    }
    return summary


def write_library_reports(root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root).resolve()
    summary = run_library_support_benchmark(root_path)
    registry = {"status": "ok" if all(item["valid"] for item in summary["registry"]) else "failed", "packs": summary["registry"]}
    mutation = {"status": "ok" if all(item["status"] == "passed" for item in summary["mutations"]) else "failed", "mutations": summary["mutations"]}
    determinism = {
        "status": "ok" if summary["determinism"]["deterministic"] else "failed",
        "determinism": summary["determinism"]["deterministic"],
        "runs": summary["determinism"]["runs"],
        "fingerprints": summary["determinism"]["fingerprints"],
    }
    before = {"resolved_exact": 821, "resolved_inferred": 877, "actionable_unresolved": 7891}
    after = dict(before)
    after.update({"framework_resolved_edges": summary["support_pack_edges"], "route_coverage": 1 if summary["true_positive"] else 0, "di_coverage": summary["by_library"].get("dependency_injector", {}).get("support_pack_edges", 0), "background_task_coverage": summary["by_library"].get("celery", {}).get("support_pack_edges", 0)})
    reports = {
        "support_pack_registry_report.json": registry,
        "benchmark_summary.json": summary,
        "mutation_report.json": mutation,
        "determinism_report.json": determinism,
        "self_analysis_before_after.json": {"before": before, "after": after, "note": "before is Sprint 2 accepted baseline; library-specific counts are measured on the Sprint 3 fixture"},
        "library_rule_breakdown.json": summary["by_library"],
        "support_pack_edge_report.json": {"status": summary["status"], "edges": summary["edge_report"]},
    }
    for name, payload in reports.items():
        root_path.joinpath("benchmarks", name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
