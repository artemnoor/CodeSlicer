from __future__ import annotations
import json, shutil, tempfile
from pathlib import Path
from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.incremental import incremental_update, project_snapshot

ROOT=Path(__file__).resolve().parents[1]
EXT={'.py','.js','.jsx','.ts','.tsx','.go','.java'}
IGNORE={'project_path','fact_document_path','unknown_region_tasks_path','stage_timings_seconds','incremental_cache','graph_fingerprint'}

def keyed(items,key): return {key(x):x for x in items}
def diff_graph(inc,clean,project,scenario,changed):
    ni=keyed(inc.get('nodes',[]),lambda x:x.get('id')); nc=keyed(clean.get('nodes',[]),lambda x:x.get('id'))
    ei=keyed(inc.get('edges',[]),lambda x:(x.get('from'),x.get('to'),x.get('kind'),x.get('source'),x.get('id'))); ec=keyed(clean.get('edges',[]),lambda x:(x.get('from'),x.get('to'),x.get('kind'),x.get('source'),x.get('id')))
    rows=[]
    for k in sorted(set(ni)-set(nc)): rows.append({'project':project,'scenario':scenario,'changed_file':changed,'entity_id':k,'difference_type':'node_only_in_incremental','incremental_value':ni[k],'clean_value':None,'probable_cause':'stale fact/cache merge','responsible_stage':'file invalidation'})
    for k in sorted(set(nc)-set(ni)): rows.append({'project':project,'scenario':scenario,'changed_file':changed,'entity_id':k,'difference_type':'node_only_in_clean','incremental_value':None,'clean_value':nc[k],'probable_cause':'missing rebuilt fact','responsible_stage':'fact extraction'})
    for k in sorted(set(ei)-set(ec)): rows.append({'project':project,'scenario':scenario,'changed_file':changed,'entity_id':str(k),'difference_type':'edge_only_in_incremental','incremental_value':ei[k],'clean_value':None,'probable_cause':'stale edge or merge retention','responsible_stage':'graph merge'})
    for k in sorted(set(ec)-set(ei)): rows.append({'project':project,'scenario':scenario,'changed_file':changed,'entity_id':str(k),'difference_type':'edge_only_in_clean','incremental_value':None,'clean_value':ec[k],'probable_cause':'dependent edge not rebuilt','responsible_stage':'semantic resolver'})
    for k in sorted(set(ni)&set(nc)):
        a={x:v for x,v in ni[k].get('properties',{}).items() if x not in {'stable_id','canonical_identity'}}; b={x:v for x,v in nc[k].get('properties',{}).items() if x not in {'stable_id','canonical_identity'}}
        if a!=b: rows.append({'project':project,'scenario':scenario,'changed_file':changed,'entity_id':k,'difference_type':'node_property_differences','incremental_value':a,'clean_value':b,'probable_cause':'derived annotation order','responsible_stage':'canonicalization'})
    for k in sorted(set(ei)&set(ec)):
        a=ei[k].get('properties',{}); b=ec[k].get('properties',{})
        if a!=b: rows.append({'project':project,'scenario':scenario,'changed_file':changed,'entity_id':str(k),'difference_type':'edge_property_differences','incremental_value':a,'clean_value':b,'probable_cause':'derived quality/provenance mismatch','responsible_stage':'quality guard'})
    im=inc.get('metadata',{}); cm=clean.get('metadata',{})
    for key in ('unknown_regions','frontend_backend_endpoint_bridge','support_pack_context'):
        if im.get(key)!=cm.get(key): rows.append({'project':project,'scenario':scenario,'changed_file':changed,'entity_id':key,'difference_type':'metadata_semantic_difference','incremental_value':im.get(key),'clean_value':cm.get(key),'probable_cause':'derived stage not rerun consistently','responsible_stage':'unknown-region lifecycle' if key=='unknown_regions' else 'support-pack application'})
    return rows

def main():
    reports=[]; root=ROOT/'benchmarks'/'sprint6_real_projects'
    for source in sorted(root.iterdir()):
        if not source.is_dir(): continue
        with tempfile.TemporaryDirectory(prefix='s61-diff-') as td:
            p=Path(td)/source.name; shutil.copytree(source,p,ignore=shutil.ignore_patterns('.git','.impact_engine','node_modules')); out=Path(td)/'graph.json'; cache=Path(td)/'raw.json'; analyze_project_core(str(p),out_path=str(out),create_research_requests=False,raw_graph_cache_path=str(cache)); snap=project_snapshot(p); files=sorted(x for x in p.rglob('*') if x.is_file() and x.suffix.lower() in EXT)
            for scenario,f in [('leaf',files[0]),('central',max(files,key=lambda x:x.stat().st_size))]:
                f.write_text(f.read_text(encoding='utf-8',errors='ignore')+'\n',encoding='utf-8'); result=incremental_update(str(p),lambda ch: analyze_project_core(str(p),create_research_requests=False,changed_files=ch,raw_graph_cache_path=str(cache)),snap,str(out),str(out)); clean=analyze_project_core(str(p),create_research_requests=False); reports.extend(diff_graph(result['graph'],clean['graph'],source.name,scenario,f.relative_to(p).as_posix())); snap=result['incremental']['snapshot']
    payload={'status':'completed','difference_count':len(reports),'differences':reports,'summary':{}}
    for row in reports: payload['summary'][row['difference_type']]=payload['summary'].get(row['difference_type'],0)+1
    out=ROOT/'benchmarks'/'sprint6_1'/'incremental_equivalence_diff_report.json'; out.write_text(json.dumps(payload,indent=2),encoding='utf-8'); print(json.dumps({'difference_count':len(reports),'summary':payload['summary']}))
if __name__=='__main__': main()
