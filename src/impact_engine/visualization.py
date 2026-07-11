"""Dependency-light local node-link graph viewer."""
from __future__ import annotations

import html
import json
from pathlib import Path


def render_graph_html(graph_path: str | Path, output_path: str | Path | None = None) -> Path:
    source = Path(graph_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    graph = payload.get("graph", payload)
    if not isinstance(graph, dict):
        raise ValueError("Graph JSON must be an object or contain a graph object")
    graph = _normalize_external_graph(graph)
    destination = Path(output_path) if output_path else source.with_suffix(".html")
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(graph, ensure_ascii=False).replace("</", "<\\/")
    document = _template().replace("__TITLE__", html.escape(source.name)).replace("__GRAPH_DATA__", data).replace("__VIEW_TOGGLE__", "")
    destination.write_text(document, encoding="utf-8")
    return destination


def render_graph_comparison_html(impact_graph_path: str | Path, graphify_graph_path: str | Path, output_path: str | Path) -> Path:
    """Create one viewer with switchable Impact Engine and Graphify views."""
    payload = json.dumps({
        "impact": _load_graph(Path(impact_graph_path)),
        "graphify": _load_graph(Path(graphify_graph_path)),
    }, ensure_ascii=False).replace("</", "<\\/")
    toggle = '<div class="tabs"><a href="?view=impact">Impact Engine</a><a href="?view=graphify">Graphify</a></div>'
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    document = _template().replace("__TITLE__", "Impact Engine vs Graphify").replace("__GRAPH_DATA__", payload).replace("__VIEW_TOGGLE__", toggle)
    destination.write_text(document, encoding="utf-8")
    return destination


def _load_graph(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    graph = payload.get("graph", payload)
    if not isinstance(graph, dict):
        raise ValueError(f"Graph JSON must be an object: {path}")
    return _normalize_external_graph(graph)


def _normalize_external_graph(graph: dict) -> dict:
    """Accept Graphify's links/label format for visualization only."""
    if "edges" in graph:
        return graph
    links = graph.get("links")
    if not isinstance(links, list):
        return graph
    nodes = []
    for node in graph.get("nodes", []):
        item = dict(node)
        item["name"] = item.get("name") or item.get("label") or item.get("id")
        item["kind"] = item.get("kind") or ("FILE" if item.get("file_type") == "code" else "CONCEPT")
        nodes.append(item)
    edges = []
    for link in links:
        item = dict(link)
        item["from_node"] = item.get("from_node") or item.get("source")
        item["to_node"] = item.get("to_node") or item.get("target")
        item["kind"] = item.get("kind") or item.get("relation") or "RELATED"
        confidence = item.get("confidence")
        item["confidence"] = 1.0 if confidence == "EXTRACTED" else (0.75 if confidence == "INFERRED" else confidence or 0.5)
        item["source"] = item.get("source") or ("EXTRACTED" if confidence == "EXTRACTED" else "EXTERNAL_TOOL")
        edges.append(item)
    return {"nodes": nodes, "edges": edges, "metadata": {"input_adapter": "graphify_visualization_only"}}


def _template() -> str:
    return r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Impact Engine Graph - __TITLE__</title>
<style>
:root{--bg:#09111b;--panel:#101b29;--line:#253447;--muted:#8ea0b5;--text:#eef4fb}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px Inter,ui-sans-serif,system-ui,sans-serif;display:grid;grid-template-columns:310px 1fr;height:100vh;overflow:hidden}
aside{padding:18px;border-right:1px solid var(--line);background:linear-gradient(180deg,#122033,#0d1724);overflow:auto;z-index:2}h1{font-size:19px;margin:0 0 5px;letter-spacing:.2px}.sub{color:var(--muted);font-size:12px;margin-bottom:18px}
label{display:block;color:#b8c5d4;margin:14px 0 6px;font-size:12px}input,select{width:100%;padding:9px 10px;background:#0a131f;color:var(--text);border:1px solid #304156;border-radius:6px;outline:none}input:focus,select:focus{border-color:#6ca9ff}
.stat{margin:16px 0;padding:12px;background:#172638;border:1px solid #2d4057;border-radius:7px;line-height:1.7}.hint{color:var(--muted);font-size:12px;line-height:1.5}.legend{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:14px}.legend span{font-size:11px;color:#c5d1df}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}.tabs{display:flex;gap:6px;margin:12px 0 4px}.tabs a{color:#d8e8fb;text-decoration:none;border:1px solid #3a506b;border-radius:5px;padding:6px 8px;background:#172638;font-size:12px}.tabs a:hover{border-color:#78b4ff}
main{position:relative;overflow:hidden;background:radial-gradient(circle at 50% 45%,#13253a 0,#0a121d 60%)}svg{width:100%;height:100%;cursor:grab}svg:active{cursor:grabbing}.link{stroke:#70849d;stroke-opacity:.46;stroke-width:1.2}.link.active{stroke:#fff;stroke-opacity:.95;stroke-width:2.5}.link-label{fill:#8fa2b8;font-size:10px;pointer-events:none}.node{cursor:pointer}.node circle{stroke:#07101a;stroke-width:2}.node text{fill:#f4f8fd;text-anchor:middle;font-size:11px;pointer-events:none}.node .kind{fill:#a9b8c9;font-size:9px}.node.dim{opacity:.14}.node.active circle{stroke:#fff;stroke-width:3}.node.active text{font-weight:700}.edge-hit{stroke:transparent;stroke-width:14;cursor:pointer}
#details{position:absolute;right:16px;top:16px;width:330px;max-height:55vh;overflow:auto;padding:14px;background:rgba(16,27,41,.96);border:1px solid #3a506b;border-radius:8px;display:none;white-space:pre-wrap;box-shadow:0 12px 35px #0008}.close{float:right;color:#9fb1c5;cursor:pointer}
</style></head><body><aside><h1>Impact Graph</h1><div class="sub">Source: __TITLE__</div>
<label for="search">Search symbols</label><input id="search" placeholder="OrderService, route...">
<label for="kind">Node kind</label><select id="kind"><option value="">All kinds</option></select>
<label for="min">Minimum confidence: <span id="minValue">0.00</span></label><input id="min" type="range" min="0" max="1" step="0.05" value="0">
__VIEW_TOGGLE__<div class="stat" id="stats"></div><div class="hint">Click a node to highlight its chain. Click a line to inspect the edge. Drag to pan and use the wheel to zoom.</div>
<div class="legend" id="legend"></div></aside><main><svg id="canvas"><defs><marker id="arrow" viewBox="0 -5 10 10" refX="20" refY="0" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,-5L10,0L0,5" fill="#91a5bd"></path></marker></defs><g id="viewport"><g id="links"></g><g id="nodes"></g></g></svg><div id="details"><span class="close" onclick="details.style.display='none'">Close</span><div id="detailText"></div></div></main>
<script id="graph-data" type="application/json">__GRAPH_DATA__</script>
<script src="https://cdn.jsdelivr.net/npm/d3@7"></script><script>
const graphSet=JSON.parse(document.getElementById('graph-data').textContent), viewName=new URLSearchParams(location.search).get('view')||'default', graph=graphSet[viewName]||graphSet.default||graphSet, rawNodes=graph.nodes||[], rawEdges=graph.edges||[];
const nodeById=new Map(rawNodes.map(n=>[n.id,n])), edgeData=rawEdges.map(e=>({...e,source:e.from_node||e.from,target:e.to_node||e.to})).filter(e=>nodeById.has(e.source)&&nodeById.has(e.target));
const svg=document.getElementById('canvas'), viewport=document.getElementById('viewport'), linksLayer=document.getElementById('links'), nodesLayer=document.getElementById('nodes'), details=document.getElementById('details'), detailText=document.getElementById('detailText');
const kinds=[...new Set(rawNodes.map(n=>n.kind||'UNKNOWN'))].sort(), kind=document.getElementById('kind'), colors={FILE:'#3b82f6',CLASS:'#a855f7',METHOD:'#22c55e',FUNCTION:'#14b8a6',ROUTE:'#f59e0b',TEST:'#ef8b4a',CALL_EXPR:'#64748b'};
kinds.forEach(k=>{const o=document.createElement('option');o.value=k;o.textContent=k;kind.appendChild(o)});Object.keys(colors).filter(k=>kinds.includes(k)).forEach(k=>{document.getElementById('legend').innerHTML+=`<span><i class="dot" style="background:${colors[k]}"></i>${k}</span>`});
const degree=new Map(rawNodes.map(n=>[n.id,0]));edgeData.forEach(e=>{degree.set(e.source,(degree.get(e.source)||0)+1);degree.set(e.target,(degree.get(e.target)||0)+1)});
const communityColors=['#38bdf8','#c084fc','#4ade80','#fb7185','#facc15','#fb923c','#2dd4bf','#a3e635'];
function label(n){return String(n.name||n.id).split('/').pop().slice(0,24)} function color(n){if(n.properties&&n.properties.community_id){const index=Number(String(n.properties.community_id).split('-').pop()||1)-1;return communityColors[index%communityColors.length]}return colors[n.kind]||'#516174'} function conf(e){return Number(e.confidence??1)}
function nodeId(value){return typeof value==='object'?value.id:value}
function visible(n){const q=document.getElementById('search').value.toLowerCase(),k=kind.value;return(!q||String(n.id).toLowerCase().includes(q)||String(n.name||'').toLowerCase().includes(q))&&(!k||n.kind===k)}
function showDetails(value){details.style.display='block';detailText.textContent=JSON.stringify(value,null,2)}
function renderFallback(){const w=svg.clientWidth||1200,h=svg.clientHeight||800;rawNodes.forEach((n,i)=>{n.x=90+(i%8)*150;n.y=90+Math.floor(i/8)*90});draw()}
function draw(){const min=Number(document.getElementById('min').value), visibleSet=new Set(rawNodes.filter(visible).map(n=>n.id));linksLayer.innerHTML='';nodesLayer.innerHTML='';let shown=0;
edgeData.forEach(e=>{const sourceId=nodeId(e.source),targetId=nodeId(e.target);if(conf(e)<min||!visibleSet.has(sourceId)||!visibleSet.has(targetId))return;shown++;const line=document.createElementNS('http://www.w3.org/2000/svg','line');line.classList.add('link');line.setAttribute('x1',e.source.x);line.setAttribute('y1',e.source.y);line.setAttribute('x2',e.target.x);line.setAttribute('y2',e.target.y);line.setAttribute('marker-end','url(#arrow)');line.onclick=()=>showDetails({from:sourceId,to:targetId,kind:e.kind,confidence:e.confidence,source:e.source,evidence:e.evidence,properties:e.properties});linksLayer.appendChild(line)});
rawNodes.forEach(n=>{const g=document.createElementNS('http://www.w3.org/2000/svg','g');g.classList.add('node');if(!visible(n))g.classList.add('dim');g.setAttribute('transform',`translate(${n.x},${n.y})`);const c=document.createElementNS('http://www.w3.org/2000/svg','circle');c.setAttribute('r',Math.min(30,12+(degree.get(n.id)||0)*2));c.setAttribute('fill',color(n));const t=document.createElementNS('http://www.w3.org/2000/svg','text');t.setAttribute('dy','4');t.textContent=label(n);const s=document.createElementNS('http://www.w3.org/2000/svg','text');s.classList.add('kind');s.setAttribute('dy','17');s.textContent=n.kind||'';g.append(c,t,s);g.onclick=()=>selectNode(n.id);nodesLayer.appendChild(g)});document.getElementById('stats').innerHTML=`Nodes: ${rawNodes.filter(visible).length} / ${rawNodes.length}<br>Edges: ${shown} / ${edgeData.length}`;document.getElementById('minValue').textContent=Number(document.getElementById('min').value).toFixed(2)}
function selectNode(id){const related=new Set([id]);edgeData.forEach(e=>{const a=nodeId(e.source),b=nodeId(e.target);if(a===id)related.add(b);if(b===id)related.add(a)});document.querySelectorAll('.node').forEach((g,i)=>g.classList.toggle('active',related.has(rawNodes[i].id)));showDetails(nodeById.get(id))}
function render(){if(window.d3){const sim=d3.forceSimulation(rawNodes).force('link',d3.forceLink(edgeData).id(d=>d.id).distance(115).strength(.35)).force('charge',d3.forceManyBody().strength(-150)).force('center',d3.forceCenter((svg.clientWidth||1200)/2,(svg.clientHeight||800)/2)).force('collision',d3.forceCollide().radius(d=>Math.min(34,16+(degree.get(d.id)||0)*2)+10));sim.on('tick',()=>{draw()});sim.on('end',()=>draw())}else renderFallback()}
['search','kind','min'].forEach(id=>document.getElementById(id).addEventListener('input',draw));svg.addEventListener('wheel',e=>{e.preventDefault();const s=e.deltaY<0?1.1:.9;viewport.setAttribute('transform',`scale(${s})`)});render();
</script></body></html>'''
