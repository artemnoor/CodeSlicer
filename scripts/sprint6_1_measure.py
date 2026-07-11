"""Measure Sprint 6.1 subprocess memory and incremental reuse honestly."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil


ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "benchmarks" / "sprint6_real_projects"
OUT = ROOT / "benchmarks" / "sprint6_1"
VOLATILE_METADATA = {
    "project_path", "fact_document_path", "unknown_region_tasks_path",
    "stage_timings_seconds", "incremental_cache", "graph_fingerprint",
}


def normalized_graph(graph: dict) -> dict:
    metadata = {
        key: value for key, value in (graph.get("metadata") or {}).items()
        if key not in VOLATILE_METADATA
    }
    return {"nodes": graph.get("nodes", []), "edges": graph.get("edges", []), "metadata": metadata}


def fingerprint(graph: dict) -> str:
    payload = json.dumps(normalized_graph(graph), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_command(args: list[str], cwd: Path) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    started = time.perf_counter()
    process = subprocess.Popen(
        [sys.executable, "-m", "impact_engine.cli", "--json", *args],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    ps = psutil.Process(process.pid)
    peak_rss = 0
    timeout_seconds = 180
    timed_out = False
    while process.poll() is None:
        if time.perf_counter() - started > timeout_seconds:
            timed_out = True
            process.kill()
            break
        try:
            peak_rss = max(peak_rss, ps.memory_info().rss)
        except psutil.Error:
            pass
        time.sleep(0.02)
    stdout, stderr = process.communicate()
    wall = time.perf_counter() - started
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except Exception:
        payload = {"status": "invalid_json", "stdout": stdout.decode("utf-8", "replace")[-4000:]}
    payload["_measurement"] = {
        "exit_code": process.returncode,
        "wall_time_seconds": round(wall, 4),
        "peak_rss_bytes": peak_rss or None,
        "output_bytes": len(stdout),
        "stderr": stderr.decode("utf-8", "replace")[-2000:],
        "timed_out": timed_out,
    }
    return payload


def project_run(name: str, source: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"impact-{name}-") as td:
        project = Path(td) / name
        shutil.copytree(source, project, ignore=shutil.ignore_patterns(".git", ".impact_engine", "node_modules"))
        out = Path(td) / "graph.json"
        snapshot = Path(td) / "snapshot.json"
        cold = run_command(["analyze", str(project), "--out", str(out), "--no-research-requests"], ROOT)
        initial = run_command(["analyze-incremental", str(project), "--out", str(out), "--snapshot", str(snapshot)], ROOT)
        warm = run_command(["analyze-incremental", str(project), "--out", str(out), "--snapshot", str(snapshot)], ROOT)
        candidates = sorted(
            p for p in project.rglob("*")
            if p.is_file() and p.suffix.lower() in {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java"}
        )
        if candidates:
            leaf = candidates[-1]
            leaf.write_text(leaf.read_text(encoding="utf-8", errors="ignore") + "\n", encoding="utf-8")
            leaf_result = run_command(["analyze-incremental", str(project), "--out", str(out), "--snapshot", str(snapshot)], ROOT)
        else:
            leaf_result = {"status": "skipped"}
        if len(candidates) > 1:
            central = max(candidates, key=lambda p: p.stat().st_size)
            central.write_text(central.read_text(encoding="utf-8", errors="ignore") + "\n", encoding="utf-8")
            central_result = run_command(["analyze-incremental", str(project), "--out", str(out), "--snapshot", str(snapshot)], ROOT)
        else:
            central_result = {"status": "skipped"}
        clean = run_command(["analyze", str(project), "--out", str(Path(td) / "clean.json"), "--no-research-requests"], ROOT)
        inc_graph = (central_result.get("graph") or leaf_result.get("graph") or {})
        clean_graph = clean.get("graph") or {}
        return {
            "project": name,
            "cold": cold.get("_measurement", {}),
            "initial_incremental": initial.get("incremental", {}),
            "warm": {"measurement": warm.get("_measurement", {}), "incremental": warm.get("incremental", {})},
            "leaf": {"measurement": leaf_result.get("_measurement", {}), "incremental": leaf_result.get("incremental", {})},
            "central": {"measurement": central_result.get("_measurement", {}), "incremental": central_result.get("incremental", {})},
            "equivalence": {
                "incremental_graph_fingerprint": fingerprint(inc_graph) if inc_graph else None,
                "clean_graph_fingerprint": fingerprint(clean_graph) if clean_graph else None,
                "equal": bool(inc_graph and clean_graph and fingerprint(inc_graph) == fingerprint(clean_graph)),
            },
        }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for project in sorted(PROJECTS.iterdir()):
        if not project.is_dir():
            continue
        try:
            rows.append(project_run(project.name, project))
        except Exception as exc:
            rows.append({"project": project.name, "status": "error", "error": str(exc)})
        (OUT / "memory_performance_partial.json").write_text(json.dumps({"projects": rows}, indent=2), encoding="utf-8")
    report = {"status": "completed", "measurement": "subprocess_psutil", "projects": rows}
    (OUT / "memory_performance_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "incremental_analysis_report.json").write_text(json.dumps({"projects": [{"project": r["project"], "warm": r["warm"], "leaf": r["leaf"], "central": r["central"]} for r in rows]}, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "projects": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
