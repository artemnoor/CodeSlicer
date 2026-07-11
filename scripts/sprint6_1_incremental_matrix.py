from __future__ import annotations
import hashlib, json, shutil, tempfile, time
from pathlib import Path
from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.incremental import incremental_update, project_snapshot

ROOT=Path(__file__).resolve().parents[1]
VOLATILE={"project_path","fact_document_path","unknown_region_tasks_path","stage_timings_seconds","incremental_cache","graph_fingerprint"}
EXT={".py",".js",".jsx",".ts",".tsx",".go",".java"}

def fingerprint(graph):
    # Quality annotations (warnings/status/quality_guard) are derived review
    # metadata. The normalized equivalence key compares semantic graph facts.
    nodes=[{"id":n.get("id"),"kind":n.get("kind"),"name":n.get("name")} for n in graph.get("nodes",[])]
    edges=[]
    for edge in graph.get("edges",[]):
        edges.append({"id":edge.get("id"),"kind":edge.get("kind"),"from":edge.get("from"),"to":edge.get("to"),"source":edge.get("source"),"confidence":edge.get("confidence"),"evidence":edge.get("evidence",[])})
    value={"nodes":nodes,"edges":edges}
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def change_run(project, snapshot, out, cache, file_path):
    file_path.write_text(file_path.read_text(encoding="utf-8",errors="ignore")+"\n",encoding="utf-8")
    started=time.perf_counter()
    result=incremental_update(str(project),lambda changed: analyze_project_core(str(project),create_research_requests=False,changed_files=changed,raw_graph_cache_path=str(cache)),snapshot,str(out),str(out))
    result["elapsed_seconds"]=round(time.perf_counter()-started,4)
    return result

def main():
    source_root=ROOT/"benchmarks"/"sprint6_real_projects"; output=ROOT/"benchmarks"/"sprint6_1"; output.mkdir(exist_ok=True); rows=[]
    for source in sorted(source_root.iterdir()):
        if not source.is_dir(): continue
        with tempfile.TemporaryDirectory(prefix="s61-matrix-") as td:
            project=Path(td)/source.name; shutil.copytree(source,project,ignore=shutil.ignore_patterns(".git",".impact_engine","node_modules")); out=Path(td)/"graph.json"; cache=Path(td)/"raw.json"
            started=time.perf_counter(); analyze_project_core(str(project),out_path=str(out),create_research_requests=False,raw_graph_cache_path=str(cache)); cold=time.perf_counter()-started; snap=project_snapshot(project)
            files=sorted(p for p in project.rglob("*") if p.is_file() and p.suffix.lower() in EXT)
            leaf=files[0]; leaf_result=change_run(project,snap,out,cache,leaf); leaf_clean=analyze_project_core(str(project),create_research_requests=False); snap2=leaf_result["incremental"]["snapshot"]
            central=max(files,key=lambda p:p.stat().st_size); central_result=change_run(project,snap2,out,cache,central); central_clean=analyze_project_core(str(project),create_research_requests=False)
            rows.append({"project":source.name,"cold_time":round(cold,4),"leaf":{"file":leaf.relative_to(project).as_posix(),"time":leaf_result["elapsed_seconds"],"incremental":leaf_result["incremental"],"equivalent":fingerprint(leaf_result["graph"])==fingerprint(leaf_clean["graph"])},"central":{"file":central.relative_to(project).as_posix(),"time":central_result["elapsed_seconds"],"incremental":central_result["incremental"],"equivalent":fingerprint(central_result["graph"])==fingerprint(central_clean["graph"])}})
            print(source.name,flush=True)
    report={"status":"ok","projects":rows,"quality_gates":{"all_cache_hit_rate_positive":all(r["leaf"]["incremental"].get("cache_hit_rate",0)>0 and r["central"]["incremental"].get("cache_hit_rate",0)>0 for r in rows),"all_equivalent":all(r["leaf"]["equivalent"] and r["central"]["equivalent"] for r in rows)}}
    (output/"real_project_incremental_cache_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    (output/"full_vs_incremental_equivalence_report.json").write_text(json.dumps({"projects":[{"project":r["project"],"leaf":r["leaf"]["equivalent"],"central":r["central"]["equivalent"]} for r in rows],"all_equivalent":report["quality_gates"]["all_equivalent"]},indent=2),encoding="utf-8")

if __name__=="__main__": main()
