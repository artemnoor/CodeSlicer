'use strict';
const memoryStorage={};
const storage={
 getItem(k){try{return storage.getItem(k)}catch(e){return memoryStorage[k]??null}},
 setItem(k,v){try{storage.setItem(k,v)}catch(e){memoryStorage[k]=String(v)}},
 removeItem(k){try{storage.removeItem(k)}catch(e){delete memoryStorage[k]}}
};
const $=s=>document.querySelector(s), $$=s=>Array.from(document.querySelectorAll(s));
const toast=(msg)=>{const t=$('#toast');t.textContent=msg;t.classList.add('show');clearTimeout(window.__toast);window.__toast=setTimeout(()=>t.classList.remove('show'),1800)};
const escapeHtml=s=>String(s).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const icon=(id)=>`<svg class="ico"><use href="#${id}"/></svg>`;

/* Legacy design sample data is intentionally kept out of the runtime. The
   browser state below is populated exclusively by /api/graph.
const coreNodes=[
['ui.OrderCreateForm','OrderCreateForm','COMPONENT','typescript','web/src/components/OrderCreateForm.tsx',18,80,90,'frontend'],
['hook.useOrders','useOrders','HOOK','typescript','web/src/hooks/useOrders.ts',8,260,90,'frontend'],
['client.orders.createOrder','createOrder','FUNCTION','typescript','web/src/api/ordersClient.ts',12,440,90,'api_client'],
['http.postJson','postJson','FUNCTION','typescript','web/src/api/http.ts',21,620,90,'http_wrapper'],
['endpoint.POST_orders','POST /api/v1/orders','ENDPOINT','http','contracts/openapi.yaml',44,800,90,'endpoint'],
['route.orders.create_order','create_order','ROUTE','python','app/api/orders.py',42,980,90,'route'],
['service.OrderService.create_order','OrderService.create_order','METHOD','python','app/services/order_service.py',31,980,230,'service'],
['repository.OrderRepository.save','OrderRepository.save','METHOD','python','app/repositories/order_repository.py',54,800,230,'repository'],
['orm.Session.add','Session.add','METHOD','python','site-packages/sqlalchemy/orm/session.py',3463,620,230,'external'],
['model.Order','Order','MODEL','python','app/models/order.py',12,440,230,'model'],
['db.orders','orders','TABLE','sql','db/schema.sql',25,260,230,'database'],
['test.api.test_create_order','test_create_order','TEST','python','tests/api/test_orders.py',16,980,390,'test'],
['test.web.order_form','OrderCreateForm.test','TEST','typescript','web/src/components/OrderCreateForm.test.tsx',20,800,390,'test']
];
const more=[];
const kinds=['FUNCTION','METHOD','CLASS','ROUTE','TEST','CONFIG','MODEL','SERVICE'];
for(let i=0;i<39;i++){
  const lang=i%5===0?'typescript':i%7===0?'sql':'python';
  const kind=kinds[i%kinds.length];
  const col=i%6,row=Math.floor(i/6);
  more.push([`aux.node.${i+1}`,['validate_payload','normalize_money','publish_event','load_customer','apply_discount','reserve_stock','calculate_tax','commit_transaction','retry_policy','serialize_order','audit_log','resolve_tenant'][i%12]+'_'+(i+1),kind,lang,`${lang==='typescript'?'web/src':'app'}/modules/${i%8}/node_${i+1}.${lang==='typescript'?'ts':lang==='sql'?'sql':'py'}`,10+i,95+col*175,520+row*115,kind==='TEST'?'test':kind==='ROUTE'?'route':'internal']);
}
const nodes=[...coreNodes,...more].map((n,i)=>({id:n[0],name:n[1],kind:n[2],language:n[3],file:n[4],line:n[5],x:n[6],y:n[7],role:n[8],confidence:i<13?[.98,.97,.96,.94,.99,.98,.96,.91,.9,.99,.99,.95,.92][i]:Math.max(.42,.96-(i%9)*.06),impact:Math.round(25+((i*17)%71)),canonical:`${n[3]}://${n[4]}#${n[1]}`}));
const edges=[];let eid=1;
const add=(from,to,kind='CALLS',status='confirmed',confidence=.92,source='CONFIRMED')=>edges.push({id:'edge-'+eid++,from,to,kind,status,confidence,source});
add(coreNodes[0][0],coreNodes[1][0]);add(coreNodes[1][0],coreNodes[2][0]);add(coreNodes[2][0],coreNodes[3][0]);add(coreNodes[3][0],coreNodes[4][0],'HTTP_CALL','confirmed',.94);add(coreNodes[4][0],coreNodes[5][0],'ROUTE_DISPATCH','confirmed',.99);add(coreNodes[5][0],coreNodes[6][0],'CALLS','confirmed',.96);add(coreNodes[6][0],coreNodes[7][0],'CALLS','likely',.85,'INFERRED');add(coreNodes[7][0],coreNodes[8][0],'CALLS','likely',.89,'INFERRED');add(coreNodes[7][0],coreNodes[9][0],'WRITES','confirmed',.94);add(coreNodes[9][0],coreNodes[10][0],'MAPS_TO','confirmed',.99);add(coreNodes[11][0],coreNodes[5][0],'COVERS','confirmed',.95);add(coreNodes[12][0],coreNodes[0][0],'COVERS','confirmed',.92);
for(let i=0;i<39;i++){
 const a=more[i][0], target=i%5===0?coreNodes[6][0]:i%5===1?coreNodes[7][0]:i%5===2?more[Math.max(0,i-2)][0]:i%5===3?coreNodes[5][0]:coreNodes[9][0];
 const st=i%13===0?'unresolved':i%9===0?'suspicious':i%4===0?'likely':'confirmed';
 const conf=st==='unresolved'?.35:st==='suspicious'?.48:st==='likely'?.72:.9;
 add(a,target,i%7===0?'IMPORTS':i%6===0?'READS':'CALLS',st,conf,st==='confirmed'?'CONFIRMED':st==='unresolved'?'UNRESOLVED':'INFERRED');
 if(i>2 && i%3===0) add(more[i-1][0],a,'CALLS',i%10===0?'suspicious':'likely',i%10===0?.52:.76,'INFERRED');
}
while(edges.length<68){const i=edges.length%more.length;add(more[i][0],more[(i+7)%more.length][0],'RELATED',i%11===0?'suspicious':'likely',i%11===0?.51:.7,'INFERRED')}
/*

const diagnostics=[
{sev:'high',category:'Неразрешённый вызов',scope:'EventPublisher.publish',file:'app/events/publisher.py:48',explanation:'Тип получателя поступает из динамического реестра плагинов.',action:'Исследовать шаблон провайдера acme-events',lib:'acme-events'},
{sev:'medium',category:'Неоднозначный получатель',scope:'payment.charge',file:'app/services/checkout.py:77',explanation:'Две реализации соответствуют одному протоколу.',action:'Добавить доказательство привязки провайдера',lib:'payments-sdk'},
{sev:'medium',category:'Динамический путь',scope:'API_BASE + route',file:'web/src/api/http.ts:19',explanation:'Базовый URL определяется переменной окружения во время выполнения.',action:'Указать профиль окружения',lib:'axios'},
{sev:'low',category:'Отсутствующий символ',scope:'LegacyOrderDto',file:'app/legacy/adapter.py:12',explanation:'Символ импортируется только внутри TYPE_CHECKING.',action:'Индексировать импорты только для типов',lib:'stdlib'},
{sev:'medium',category:'Неподдерживаемая семантика',scope:'@transactional',file:'app/repositories/order_repository.py:50',explanation:'Семантика декоратора не покрыта текущим пакетом.',action:'Расширить пакет поддержки SQLAlchemy',lib:'sqlalchemy'},
{sev:'low',category:'Неразрешённый префикс маршрута',scope:'router.prefix',file:'app/api/router.py:8',explanation:'Префикс собирается из настроек при запуске.',action:'Зафиксировать конфигурационную константу',lib:'fastapi'},
{sev:'medium',category:'Неразрешённый импорт',scope:'acme_events.kafka',file:'app/events/kafka.py:4',explanation:'Для сторонней библиотеки нет проверенного пакета поддержки.',action:'Запустить исследование библиотеки',lib:'acme-events'},
{sev:'low',category:'Диагностика парсера',scope:'generated/client.ts',file:'web/src/generated/client.ts:1',explanation:'Сгенерированный файл пропущен согласно политике.',action:'Оставить пропуск или изменить фильтр generated',lib:'typescript'}
];
const libraries=[
['fastapi','Python','0.115.0','активна','проверено на реальном проекте','0.98','маршруты, DI, зависимости','2 ч назад'],
['sqlalchemy','Python','2.0.36','активна','доверенный','0.97','ORM, сессии, модели','1 д назад'],
['react','TypeScript','19.0.0','активна','проверено на реальном проекте','0.95','компоненты, хуки','4 ч назад'],
['axios','TypeScript','1.7.9','активна','проверено на тестовом проекте','0.90','HTTP-клиенты, перехватчики','5 д назад'],
['pytest','Python','8.3.4','активна','доверенный','0.98','тесты, фикстуры','3 д назад'],
['vitest','TypeScript','2.1.8','активна','проверено на тестовом проекте','0.91','тесты, моки','6 д назад'],
['pydantic','Python','2.10.4','активна','доверенный','0.98','модели, валидаторы','1 д назад'],
['acme-events','Python','0.4.2','неизвестна','черновик','0.40','только импорты','никогда'],
['react-router','TypeScript','7.1.1','активна','проверено на тестовом проекте','0.88','маршруты, загрузчики','8 д назад'],
['alembic','Python','1.14.0','требует проверки','подготовлен','0.72','миграции','32 д назад'],
['zod','TypeScript','3.24.1','активна','проверено на тестовом проекте','0.89','схемы','4 д назад'],
['tenacity','Python','9.0.0','активна','проверено на тестовом проекте','0.84','декораторы повторов','11 д назад']
];

*/
const nodes=[];const edges=[];let eid=1;const diagnostics=[];const libraries=[];
const nodeById=id=>nodes.find(n=>n.id===id);
function switchView(name){
 $$('.view').forEach(v=>v.classList.toggle('active',v.id==='view-'+name));
 $$('.nav button[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===name));
 $('#sidebar').classList.remove('open');
 storage.setItem('impact-view',name);
 if(name==='graph'){requestAnimationFrame(()=>{fitGraph();resize3d()})}
}
$$('.nav button[data-view]').forEach(b=>b.onclick=()=>switchView(b.dataset.view));
$$('[data-go]').forEach(b=>b.onclick=()=>switchView(b.dataset.go));
$('#menuBtn').onclick=()=>$('#sidebar').classList.toggle('open');
const themeMeta=document.querySelector('meta[name="theme-color"]');
function applyTheme(theme){
  document.documentElement.dataset.theme=theme;
  storage.setItem('impact-theme',theme);
  const use=$('#themeBtn use');
  use.setAttribute('href',theme==='dark'?'#i-sun':'#i-moon');
  $('#themeBtn').title=theme==='dark'?'Включить светлую тему':'Включить тёмную тему';
  if(themeMeta)themeMeta.setAttribute('content',theme==='dark'?'#0d0d0d':'#f4f7f4');
  window.__redraw3d?.();
}
const initialTheme=storage.getItem('impact-theme')||(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');
applyTheme(initialTheme);
$('#themeBtn').onclick=()=>applyTheme(document.documentElement.dataset.theme==='dark'?'light':'dark');

document.addEventListener('keydown',e=>{if(e.key==='Escape'){$('#modal').classList.remove('show');$('#filterPop').classList.remove('open')}});

// Graph render. Both views use the same real GraphDocument through force-graph.
const graph2dEl=$('#graph2d'),graph3dEl=$('#graph3d');
let graph2dEngine=null,graph3dEngine=null,selectedNode=null,selectedEdge=null,graphMode='2d',filteredNodes=nodes.slice();
const statusColor=status=>({confirmed:'#79ffbc',resolved:'#79ffbc',likely:'#79d9da',suspicious:'#ffd76b',unresolved:'#ff8ca0',ambiguous:'#ff8ca0'}[status]||'#9eecc3');
function nodeColor(node){
 if(node.id===selectedNode)return '#effff4';
 if(node.role==='repository'||node.role==='database')return '#c8a6ff';
 if(node.role==='route'||node.role==='endpoint'||node.role==='api_client'||node.role==='http_wrapper')return '#7be0e2';
 if(node.role==='test')return '#ffd76b';
 if(node.role==='external')return '#ff8ca0';
 return '#8dffc4';
}
function graphDegree(){const result=new Map(nodes.map(node=>[node.id,0]));edges.forEach(edge=>{result.set(edge.from,(result.get(edge.from)||0)+1);result.set(edge.to,(result.get(edge.to)||0)+1)});return result}
function visibleEdges(){const ids=new Set(filteredNodes.map(node=>node.id));return edges.filter(edge=>ids.has(edge.from)&&ids.has(edge.to))}
function circularGraphData(){
 const degree=graphDegree(),ordered=[...filteredNodes].sort((a,b)=>(degree.get(b.id)||0)-(degree.get(a.id)||0)||a.id.localeCompare(b.id)),golden=Math.PI*(3-Math.sqrt(5));
 const positions=new Map(ordered.map((node,index)=>{const radius=index===0?0:42+Math.sqrt(index)*22,angle=index*golden;return[node.id,{x:Math.cos(angle)*radius,y:Math.sin(angle)*radius}]}));
 return{nodes:filteredNodes.map(node=>({...node,...positions.get(node.id),degree:degree.get(node.id)||0})),links:visibleEdges().map(edge=>({...edge,source:edge.from,target:edge.to}))};
}
function sphericalGraphData(){
 const degree=graphDegree(),ordered=[...filteredNodes].sort((a,b)=>a.id.localeCompare(b.id)),golden=Math.PI*(3-Math.sqrt(5)),count=Math.max(1,ordered.length),positions=new Map();
 ordered.forEach((node,index)=>{const y=1-(index/(count-1||1))*2,r=Math.sqrt(Math.max(0,1-y*y)),angle=index*golden,depth=Math.min(1,(degree.get(node.id)||0)/8),radius=180-depth*34;positions.set(node.id,{x:Math.cos(angle)*r*radius,y:y*radius,z:Math.sin(angle)*r*radius})});
 return{nodes:filteredNodes.map(node=>{const point=positions.get(node.id);return {...node,...point,fx:point.x,fy:point.y,fz:point.z,degree:degree.get(node.id)||0}}),links:visibleEdges().map(edge=>({...edge,source:edge.from,target:edge.to}))};
}
const manual3d={target:{x:0,y:0,z:0},yaw:.38,pitch:.18,distance:620,drag:null};
function apply3dCamera(duration=0){
 if(!graph3dEngine)return;const c=Math.cos(manual3d.pitch),position={x:manual3d.target.x+manual3d.distance*c*Math.sin(manual3d.yaw),y:manual3d.target.y+manual3d.distance*Math.sin(manual3d.pitch),z:manual3d.target.z+manual3d.distance*c*Math.cos(manual3d.yaw)};
 graph3dEngine.cameraPosition(position,manual3d.target,duration);
}
function reset3dCamera(){manual3d.target={x:0,y:0,z:0};manual3d.yaw=.38;manual3d.pitch=.18;manual3d.distance=620;apply3dCamera(320)}
function install3dControls(){
 const controls=graph3dEngine.controls();if(controls)controls.enabled=false;
 graph3dEl.addEventListener('contextmenu',event=>event.preventDefault());
 graph3dEl.addEventListener('pointerdown',event=>{if(event.button!==0&&event.button!==2)return;manual3d.drag={button:event.button,x:event.clientX,y:event.clientY};event.target.setPointerCapture?.(event.pointerId);if(event.button===2)event.preventDefault()});
 graph3dEl.addEventListener('pointermove',event=>{const drag=manual3d.drag;if(!drag)return;const dx=event.clientX-drag.x,dy=event.clientY-drag.y;drag.x=event.clientX;drag.y=event.clientY;if(drag.button===0){manual3d.yaw+=dx*.006;manual3d.pitch=Math.max(-1.35,Math.min(1.35,manual3d.pitch+dy*.006))}else{const pan=manual3d.distance*.0018;manual3d.target.x-=dx*pan;manual3d.target.y+=dy*pan}apply3dCamera()});
 graph3dEl.addEventListener('pointerup',event=>{manual3d.drag=null;event.target.releasePointerCapture?.(event.pointerId)});graph3dEl.addEventListener('pointercancel',()=>manual3d.drag=null);
 graph3dEl.addEventListener('wheel',event=>{event.preventDefault();manual3d.distance=Math.max(260,Math.min(1800,manual3d.distance*(event.deltaY>0?1.12:.89)));apply3dCamera()},{passive:false});
 graph3dEl.addEventListener('dblclick',event=>{if(graphMode==='3d'){event.preventDefault();reset3dCamera()}});
}
function draw2dNode(node,ctx,scale){
 const linked=selectedNode&&visibleEdges().some(edge=>(edge.from===selectedNode&&edge.to===node.id)||(edge.to===selectedNode&&edge.from===node.id));
 const dim=selectedNode&&node.id!==selectedNode&&!linked,selected=node.id===selectedNode;
 const radius=(selected?5.8:2.1+Math.min(3.2,Math.sqrt(node.degree||0)*.74))/scale;
 ctx.save();ctx.globalAlpha=dim?.14:1;ctx.shadowColor=nodeColor(node);ctx.shadowBlur=(selected?18:7)/scale;
 ctx.fillStyle=nodeColor(node);ctx.beginPath();ctx.arc(node.x,node.y,radius,0,Math.PI*2);ctx.fill();ctx.shadowBlur=0;
 if(selected||scale>2.1){ctx.fillStyle='#ecfff2';ctx.font=`${Math.max(4.5,10/scale)}px ui-monospace,monospace`;ctx.fillText(node.name,node.x+radius+3/scale,node.y-radius-2/scale)}
 ctx.restore();
}
function linkColor(link){if(selectedEdge===link.id)return '#ffffff';if(selectedNode&&link.source?.id!==selectedNode&&link.target?.id!==selectedNode&&link.source!==selectedNode&&link.target!==selectedNode)return 'rgba(124,255,185,.08)';return statusColor(link.status)}
function ensureForceGraphs(){
 if(graph2dEngine&&graph3dEngine)return true;
 if(typeof window.ForceGraph!=='function'||typeof window.ForceGraph3D!=='function'){console.error('Force graph libraries were not loaded');return false}
 graph2dEngine=window.ForceGraph()(graph2dEl).nodeId('id').linkSource('source').linkTarget('target').nodeLabel(node=>`${node.name}\n${node.kind}`).nodeCanvasObjectMode(()=> 'replace').nodeCanvasObject(draw2dNode).linkColor(linkColor).linkWidth(link=>selectedEdge===link.id?2.1:link.status==='confirmed'?1.1:.72).linkDirectionalArrowLength(3.1).linkDirectionalArrowRelPos(.98).linkDirectionalArrowColor(linkColor).onNodeClick(node=>selectNode(node.id)).onLinkClick(link=>selectEdge(link.id)).onBackgroundClick(clearGraphSelection).onNodeHover(node=>graph2dEl.style.cursor=node?'pointer':'grab').backgroundColor('#020806').d3AlphaDecay(.075).d3VelocityDecay(.52).warmupTicks(0).cooldownTicks(90);
 graph2dEngine.d3Force('charge').strength(-76);graph2dEngine.d3Force('link').distance(34).strength(.42);
 graph3dEngine=window.ForceGraph3D()(graph3dEl).nodeId('id').linkSource('source').linkTarget('target').nodeLabel(node=>`${node.name}\n${node.kind}`).nodeColor(nodeColor).nodeVal(node=>node.id===selectedNode?6.5:1.7+Math.min(3.2,node.degree||0)).nodeRelSize(3.3).linkColor(linkColor).linkWidth(link=>selectedEdge===link.id?1.9:link.status==='confirmed'?.95:.56).linkOpacity(.74).linkDirectionalArrowLength(2.25).linkDirectionalArrowRelPos(.98).onNodeClick(node=>selectNode(node.id)).onLinkClick(link=>selectEdge(link.id)).onBackgroundClick(clearGraphSelection).onNodeHover(node=>graph3dEl.style.cursor=node?'pointer':'grab').showNavInfo(false).backgroundColor('#020806').d3AlphaDecay(.1).d3VelocityDecay(.7).warmupTicks(0).cooldownTicks(1);
 install3dControls();
 return true;
}
function resize3d(){
 if(!ensureForceGraphs())return;const stage=$('#graphStage'),width=Math.max(1,stage.clientWidth),height=Math.max(1,stage.clientHeight);
 graph2dEngine.width(width).height(height);graph3dEngine.width(width).height(height);
}
function draw3d(){refreshHighlights()}
function renderGraph(){
 const hasNodes=filteredNodes.length>0;$('#graphEmpty').classList.toggle('show',!hasNodes);if(!ensureForceGraphs())return;
 resize3d();graph2dEngine.graphData(circularGraphData());graph3dEngine.graphData(sphericalGraphData());
 requestAnimationFrame(()=>{if(hasNodes)fitGraph()});
}
function selectNode(id){selectedNode=id;selectedEdge=null;const node=nodeById(id);if(node)renderInspector(node);refreshHighlights();storage.setItem('impact-selected-node',id)}
function selectEdge(id){selectedEdge=id;selectedNode=null;const edge=edges.find(item=>item.id===id);if(edge)showEdgeModal(edge);refreshHighlights()}
function refreshHighlights(){
 if(!graph2dEngine||!graph3dEngine)return;
 graph2dEngine.nodeCanvasObject(draw2dNode).linkColor(linkColor).linkWidth(link=>selectedEdge===link.id?2.1:link.status==='confirmed'?1.1:.72).linkDirectionalArrowColor(linkColor);
 graph3dEngine.nodeColor(nodeColor).nodeVal(node=>node.id===selectedNode?6.5:1.7+Math.min(3.2,node.degree||0)).linkColor(linkColor).linkWidth(link=>selectedEdge===link.id?1.9:link.status==='confirmed'?.95:.56);
}
function clearGraphSelection(){selectedNode=null;selectedEdge=null;$('#inspectorEmpty').style.display='grid';$('#inspectorBody').classList.remove('show');refreshHighlights()}
function fitGraph(){
 if(!graph2dEngine||!filteredNodes.length)return;resize3d();
 if(graphMode==='3d')reset3dCamera();else graph2dEngine.zoomToFit(350,64);
}
function resetGraph(){selectedNode=null;selectedEdge=null;$('#inspectorEmpty').style.display='grid';$('#inspectorBody').classList.remove('show');refreshHighlights();fitGraph()}
function focusGraphNode(node){
 if(!node||!graph2dEngine)return;if(graphMode==='2d'){const rendered=graph2dEngine.graphData().nodes.find(item=>item.id===node.id);if(rendered){graph2dEngine.centerAt(rendered.x,rendered.y,350);graph2dEngine.zoom(3.1,350)}}else{const rendered=graph3dEngine.graphData().nodes.find(item=>item.id===node.id);if(!rendered)return;manual3d.target={x:rendered.x,y:rendered.y,z:rendered.z};manual3d.distance=280;apply3dCamera(480)}
}
window.__redraw3d=draw3d;
$('#fitBtn').onclick=fitGraph;$('#resetBtn').onclick=resetGraph;
$$('[data-mode]').forEach(button=>button.onclick=()=>{
 graphMode=button.dataset.mode;$$('[data-mode]').forEach(item=>item.classList.toggle('active',item===button));
 graph2dEl.classList.toggle('active',graphMode==='2d');graph3dEl.classList.toggle('active',graphMode==='3d');storage.setItem('impact-graph-mode',graphMode);
 requestAnimationFrame(()=>{resize3d();fitGraph();draw3d()});
});
function renderInspector(n){
 $('#inspectorEmpty').style.display='none';$('#inspectorBody').classList.add('show');
 $('#nodeKind').textContent=n.kind+' · '+n.role;$('#nodeName').textContent=n.name;$('#nodeCanonical').textContent=n.canonical;
 const rel=edges.filter(e=>e.from===n.id||e.to===n.id);
 $('#nodeKv').innerHTML=`<div class="kv"><span>Файл</span><code>${escapeHtml(n.file)}:${n.line}</code></div><div class="kv"><span>Язык</span><b>${n.language}</b></div><div class="kv"><span>Уверенность</span><b>${Math.round(n.confidence*100)}%</b></div><div class="kv"><span>Оценка влияния</span><b>${n.impact}</b></div><div class="kv"><span>Доказательства</span><b>${Math.max(1,rel.length+1)} записей</b></div>`;
 $('#nodeConnectionCount').textContent=rel.length;
 $('#nodeRelations').innerHTML=rel.slice(0,8).map(e=>{const other=e.from===n.id?nodeById(e.to):nodeById(e.from);return `<div class="relation" data-rel="${escapeHtml(other.id)}"><b>${escapeHtml(other.name)}</b><br><span class="muted">${e.kind} · ${Math.round(e.confidence*100)}%</span></div>`}).join('')||'<span class="muted">Изолированный узел</span>';
 $$('.relation').forEach(x=>x.onclick=()=>selectNode(x.dataset.rel));
}
function showEdgeModal(e){
 const a=nodeById(e.from),b=nodeById(e.to);$('#modalTitle').textContent=`${a.name} → ${b.name}`;
 const statusLabel={confirmed:'подтверждено',likely:'вероятно',suspicious:'подозрительно',unresolved:'не разрешено'}[e.status]||e.status;
 $('#modalBody').innerHTML=`<div class="tag-list"><span class="status-pill ${e.status==='confirmed'?'good':e.status==='suspicious'?'warn':'bad'}">${statusLabel}</span><span class="tag">${e.kind}</span><span class="tag green">${Math.round(e.confidence*100)}% уверенности</span><span class="tag">${e.source}</span></div><div style="margin-top:18px"><div class="evidence-step"><strong>Тип получателя разрешён</strong><p>Статические данные о типах связывают получателя вызова с конкретной реализацией сервиса.</p></div><div class="evidence-step"><strong>Найдена привязка конструктора</strong><p>Назначение провайдера соединяет параметр конструктора с реализацией репозитория.</p></div><div class="evidence-step"><strong>Метод подтверждён</strong><p>Сигнатура целевого метода соответствует аргументам вызова и области видимости.</p></div></div><div class="notice"><svg class="ico"><use href="#i-check"/></svg><span>Резолвер: <code>constructor_binding_resolver</code>. Объяснение воспроизводится из фактов графа.</span></div>`;
 $('#modal').classList.add('show');
}
$('#closeModal').onclick=()=>$('#modal').classList.remove('show');$('#modal').onclick=e=>{if(e.target.id==='modal')$('#modal').classList.remove('show')};
$('#inspectImpact').onclick=async()=>{if(!selectedNode)return;$('#impactTarget').value=selectedNode;switchView('impact');await runRealImpact()};
$('#copyNode').onclick=()=>{if(selectedNode)navigator.clipboard?.writeText(selectedNode).then(()=>toast('ID узла скопирован')).catch(()=>toast(selectedNode))};
$('#focusNode').onclick=()=>{if(selectedNode)focusGraphNode(nodeById(selectedNode))};
$('#filterBtn').onclick=e=>{e.stopPropagation();$('#filterPop').classList.toggle('open')};document.addEventListener('click',e=>{if(!e.target.closest('#filterPop'))$('#filterPop').classList.remove('open')});
['graphSearch','languageFilter','sourceFilter','confidenceFilter','hideTests','hideExternal'].forEach(id=>$('#'+id).addEventListener(id==='graphSearch'?'input':'change',applyFilters));
function applyFilters(){const q=$('#graphSearch').value.trim().toLowerCase(),lang=$('#languageFilter').value,source=$('#sourceFilter').value,min=+$('#confidenceFilter').value;$('#confLabel').textContent=min.toFixed(2);filteredNodes=nodes.filter(n=>(!q||(n.name+' '+n.id+' '+n.file).toLowerCase().includes(q))&&(lang==='all'||n.language===lang)&&(!$('#hideTests').checked||n.kind!=='TEST')&&(!$('#hideExternal').checked||n.role!=='external'));if(source!=='all'){const ids=new Set(edges.filter(e=>e.source===source&&e.confidence>=min).flatMap(e=>[e.from,e.to]));filteredNodes=filteredNodes.filter(n=>ids.has(n.id))}else if(min>0){const ids=new Set(edges.filter(e=>e.confidence>=min).flatMap(e=>[e.from,e.to]));filteredNodes=filteredNodes.filter(n=>ids.has(n.id))}$('#visibleCount').textContent=`видно ${filteredNodes.length} из ${nodes.length}`;renderGraph()}
$('#clearFilters').onclick=()=>{$('#graphSearch').value='';$('#languageFilter').value='all';$('#sourceFilter').value='all';$('#confidenceFilter').value=0;$('#hideTests').checked=false;$('#hideExternal').checked=false;applyFilters()};
$('#exportJson').onclick=()=>{const blob=new Blob([JSON.stringify({nodes,edges,metadata:realGraphMetadata},null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='graph.json';a.click();URL.revokeObjectURL(a.href);toast('Реальный graph.json экспортирован')};
$('#exportPng').onclick=()=>{const canvas=(graphMode==='3d'?graph3dEl:graph2dEl).querySelector('canvas');if(!canvas){toast('Граф ещё не готов к экспорту');return}const a=document.createElement('a');a.download=`impact-graph-${graphMode}.png`;a.href=canvas.toDataURL('image/png');a.click();toast('PNG экспортирован')};
window.addEventListener('resize',resize3d);

/* Legacy SVG/canvas renderer kept only as historical reference. It is not executed.
function applyTransform(){viewport.setAttribute('transform',`translate(${transform.x} ${transform.y}) scale(${transform.k})`)}
svg.addEventListener('wheel',e=>{e.preventDefault();const rect=svg.getBoundingClientRect(),mx=(e.clientX-rect.left)/rect.width*1100,my=(e.clientY-rect.top)/rect.height*760;const old=transform.k,next=Math.min(3.5,Math.max(.3,old*(e.deltaY>0?.9:1.1)));transform.x=mx-(mx-transform.x)*(next/old);transform.y=my-(my-transform.y)*(next/old);transform.k=next;applyTransform()},{passive:false});
svg.addEventListener('pointerdown',e=>{if(e.target.closest('.node')||e.target.closest('.edge'))return;drag={x:e.clientX,y:e.clientY,tx:transform.x,ty:transform.y};svg.setPointerCapture(e.pointerId)});svg.addEventListener('pointermove',e=>{if(!drag)return;const r=svg.getBoundingClientRect();transform.x=drag.tx+(e.clientX-drag.x)/r.width*1100;transform.y=drag.ty+(e.clientY-drag.y)/r.height*760;applyTransform()});svg.addEventListener('pointerup',()=>drag=null);svg.onclick=e=>{if(e.target===svg){selectedNode=null;selectedEdge=null;$('#inspectorEmpty').style.display='grid';$('#inspectorBody').classList.remove('show');refreshHighlights()}};
function fitGraph(){transform={x:20,y:20,k:.84};applyTransform()}function resetGraph(){transform={x:0,y:0,k:1};applyTransform();selectedNode=null;selectedEdge=null;refreshHighlights()}
$('#fitBtn').onclick=fitGraph;$('#resetBtn').onclick=resetGraph;
$('#filterBtn').onclick=e=>{e.stopPropagation();$('#filterPop').classList.toggle('open')};document.addEventListener('click',e=>{if(!e.target.closest('#filterPop'))$('#filterPop').classList.remove('open')});
['graphSearch','languageFilter','sourceFilter','confidenceFilter','hideTests','hideExternal'].forEach(id=>$('#'+id).addEventListener(id==='graphSearch'?'input':'change',applyFilters));
function applyFilters(){const q=$('#graphSearch').value.trim().toLowerCase(),lang=$('#languageFilter').value,source=$('#sourceFilter').value,min=+$('#confidenceFilter').value;$('#confLabel').textContent=min.toFixed(2);filteredNodes=nodes.filter(n=>(!q||(n.name+' '+n.id+' '+n.file).toLowerCase().includes(q))&&(lang==='all'||n.language===lang)&&(!$('#hideTests').checked||n.kind!=='TEST')&&(!$('#hideExternal').checked||n.role!=='external'));if(source!=='all'){const ids=new Set(edges.filter(e=>e.source===source&&e.confidence>=min).flatMap(e=>[e.from,e.to]));filteredNodes=filteredNodes.filter(n=>ids.has(n.id))}else if(min>0){const ids=new Set(edges.filter(e=>e.confidence>=min).flatMap(e=>[e.from,e.to]));filteredNodes=filteredNodes.filter(n=>ids.has(n.id))}renderGraph();draw3d()}
$('#clearFilters').onclick=()=>{$('#graphSearch').value='';$('#languageFilter').value='all';$('#sourceFilter').value='all';$('#confidenceFilter').value=0;$('#hideTests').checked=false;$('#hideExternal').checked=false;applyFilters()};
$('#exportJson').onclick=()=>{const blob=new Blob([JSON.stringify({nodes,edges,metadata:realGraphMetadata},null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='graph.json';a.click();URL.revokeObjectURL(a.href);toast('Реальный graph.json экспортирован')};
$('#exportPng').onclick=()=>{const clone=svg.cloneNode(true);clone.setAttribute('xmlns','http://www.w3.org/2000/svg');const data=new XMLSerializer().serializeToString(clone),img=new Image(),c=document.createElement('canvas');c.width=1400;c.height=900;img.onload=()=>{const ctx=c.getContext('2d');ctx.fillStyle='#0f0f0f';ctx.fillRect(0,0,c.width,c.height);ctx.drawImage(img,0,0,c.width,c.height);const a=document.createElement('a');a.download='impact-graph.png';a.href=c.toDataURL('image/png');a.click();toast('PNG экспортирован')};img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(data)};

// Интерактивный 3D-режим: тот же GraphDocument, что и в 2D
// Здесь нет декоративных узлов или случайных рёбер: соответствие nodes/edges строго 1:1.
const canvas=$('#canvas3d'),ctx=canvas.getContext('2d');
let rotX=-.22,rotY=.38,camZoom=1,drag3d=null,dragMoved=false,raf3d=0,lastFrame=0;
const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)').matches;
function hash01(text){let h=2166136261;for(let i=0;i<text.length;i++){h^=text.charCodeAt(i);h=Math.imul(h,16777619)}return((h>>>0)%10000)/10000}
function colorForNode(n){
 if(n.role==='frontend')return 'mint';
 if(['service','route','api_client','http_wrapper','endpoint'].includes(n.role))return 'cyan';
 if(['repository','database','model'].includes(n.role))return 'violet';
 if(n.role==='test')return 'amber';
 if(n.role==='external')return 'rose';
 return 'ice';
}
// X/Y наследуются из стабильного 2D-layout. Z вычисляется детерминированно по ID.
// Поэтому переход 2D ↔ 3D не меняет топологию графа и не создаёт новые сущности.
let actual3d=[],visual3dNodes=[],visualIndex=new Map(),visual3dEdges=[];
function rebuild3dData(){
 actual3d=nodes.map((n,i)=>({id:n.id,node:n,actual:true,x:(n.x-520)*.62,y:(n.y-360)*.62,z:(hash01(n.id)-.5)*360+((i%5)-2)*12,size:2.4+Math.min(3.2,n.impact/38),color:colorForNode(n)}));
 visual3dNodes=actual3d;visualIndex=new Map(actual3d.map((n,i)=>[n.id,i]));
 visual3dEdges=edges.map(e=>({a:visualIndex.get(e.from),b:visualIndex.get(e.to),id:e.id,edge:e,status:e.status,actual:true})).filter(e=>e.a!=null&&e.b!=null);
}
const stars=Array.from({length:90},(_,i)=>({x:hash01('star-x-'+i),y:hash01('star-y-'+i),r:.25+hash01('star-r-'+i)*.65,a:.06+hash01('star-a-'+i)*.18}));
function resize3d(){
 const r=canvas.getBoundingClientRect(),d=Math.min(2,window.devicePixelRatio||1);
 canvas.width=Math.max(1,Math.floor(r.width*d));canvas.height=Math.max(1,Math.floor(r.height*d));
 ctx.setTransform(d,0,0,d,0,0);draw3d()
}
function rotate3d(v){
 const cy=Math.cos(rotY),sy=Math.sin(rotY),cx=Math.cos(rotX),sx=Math.sin(rotX);
 const x1=v.x*cy-v.z*sy,z1=v.x*sy+v.z*cy,y1=v.y*cx-z1*sx,z2=v.y*sx+z1*cx;
 return{x:x1,y:y1,z:z2}
}
function projectVisual(v,w,h){
 const q=rotate3d(v),f=720/(760+q.z),scale=Math.min(w,h)/650*camZoom;
 return{x:w/2+q.x*f*scale,y:h/2+q.y*f*scale,z:q.z,p:f,scale}
}
function theme3d(){
 const light=document.documentElement.dataset.theme==='light';
 return light?{
   bg:'#f5f9f6',star:'38,72,48',text:'#182019',
   mint:'47,158,62',cyan:'38,137,141',violet:'112,91,170',amber:'201,131,20',rose:'205,64,91',ice:'70,118,156',
   line:'75,115,84',muted:'102,127,109'
 }:{
   bg:'#061214',star:'133,217,191',text:'#f5fff9',
   mint:'100,239,181',cyan:'111,212,217',violet:'188,173,255',amber:'248,205,83',rose:'255,133,145',ice:'164,205,255',
   line:'98,208,171',muted:'128,178,161'
 };
}
function rgba(rgb,a){return `rgba(${rgb},${a})`}
function visible3dState(){
 const ids=new Set(filteredNodes.map(n=>n.id));
 const visibleEdges=visual3dEdges.filter(e=>ids.has(actual3d[e.a].id)&&ids.has(actual3d[e.b].id));
 return{ids,visibleEdges};
}
function draw3d(){
 if(graphMode!=='3d')return;
 const r=canvas.getBoundingClientRect(),w=r.width,h=r.height,pal=theme3d(),state=visible3dState();
 ctx.clearRect(0,0,w,h);ctx.fillStyle=pal.bg;ctx.fillRect(0,0,w,h);
 stars.forEach(s=>{ctx.globalAlpha=s.a;ctx.fillStyle=rgba(pal.star,1);ctx.beginPath();ctx.arc(s.x*w,s.y*h,s.r,0,Math.PI*2);ctx.fill()});ctx.globalAlpha=1;
 const projected=actual3d.map(v=>projectVisual(v,w,h));
 const neighborIds=new Set();
 if(selectedNode){edges.forEach(e=>{if(e.from===selectedNode)neighborIds.add(e.to);if(e.to===selectedNode)neighborIds.add(e.from)})}
 state.visibleEdges.map(e=>({e,z:(projected[e.a].z+projected[e.b].z)/2})).sort((a,b)=>a.z-b.z).forEach(({e})=>{
   const a=projected[e.a],b=projected[e.b],edge=e.edge;
   const linked=edge.from===selectedNode||edge.to===selectedNode;
   const selected=edge.id===selectedEdge;
   let col=pal.line,alpha=.24,width=.72;
   if(edge.status==='confirmed'){col=pal.mint;alpha=.31}
   else if(edge.status==='likely'){col=pal.cyan;alpha=.27}
   else if(edge.status==='suspicious'){col=pal.amber;alpha=.40}
   else if(edge.status==='unresolved'){col=pal.rose;alpha=.42}
   if(selected||linked){alpha=.92;width=1.55}
   else if(selectedNode){alpha*=.16}
   const depth=Math.max(.25,Math.min(1,(a.p+b.p)/2));
   ctx.strokeStyle=rgba(col,alpha*depth);ctx.lineWidth=width;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke()
 });
 actual3d.map((v,i)=>({v,i,p:projected[i]})).filter(x=>state.ids.has(x.v.id)).sort((a,b)=>a.p.z-b.p.z).forEach(({v,p})=>{
   const selected=v.id===selectedNode,neighbor=neighborIds.has(v.id),dim=!!selectedNode&&!selected&&!neighbor;
   const rad=Math.max(1.15,v.size*p.p*p.scale*(selected?1.55:neighbor?1.18:1));
   const rgb=pal[v.color]||pal.mint,depth=Math.max(.28,Math.min(1.2,p.p));
   ctx.shadowBlur=selected?19:neighbor?10:6;ctx.shadowColor=rgba(rgb,selected?.95:.45);
   ctx.globalAlpha=dim?.18:Math.min(1,.60+depth*.32);
   ctx.fillStyle=rgba(rgb,1);ctx.beginPath();ctx.arc(p.x,p.y,rad,0,Math.PI*2);ctx.fill();
   ctx.shadowBlur=0;ctx.globalAlpha=1;
   if(selected){
     ctx.font='600 11px system-ui';
     const label=v.node.name,tw=Math.min(250,ctx.measureText(label).width+20),lx=Math.min(w-tw-10,p.x+12),ly=Math.max(26,p.y-18);
     ctx.fillStyle=document.documentElement.dataset.theme==='light'?'rgba(255,255,255,.96)':'rgba(7,18,16,.94)';
     ctx.strokeStyle=rgba(pal.mint,.72);ctx.lineWidth=1;ctx.beginPath();ctx.roundRect(lx,ly-17,tw,25,6);ctx.fill();ctx.stroke();
     ctx.fillStyle=pal.text;ctx.fillText(label,lx+10,ly)
   }
 });
 // Счётчик подтверждает, что 3D отображает тот же отфильтрованный граф, что и 2D.
 const visibleEdgeCount=state.visibleEdges.length;
 ctx.font='500 10px ui-monospace,monospace';
 const badge=`${state.ids.size} узлов · ${visibleEdgeCount} связей · 1:1 с 2D`;
 const bw=ctx.measureText(badge).width+20;
 ctx.fillStyle=document.documentElement.dataset.theme==='light'?'rgba(255,255,255,.88)':'rgba(6,18,20,.78)';
 ctx.strokeStyle=rgba(pal.line,.35);ctx.lineWidth=1;ctx.beginPath();ctx.roundRect(12,12,bw,25,7);ctx.fill();ctx.stroke();
 ctx.fillStyle=rgba(pal.muted,1);ctx.fillText(badge,22,29);
}
function animate3d(ts){
 if(graphMode!=='3d'){raf3d=0;return}
 if(!lastFrame)lastFrame=ts;const dt=Math.min(32,ts-lastFrame);lastFrame=ts;
 if(!drag3d&&!reducedMotion)rotY+=dt*.000045;
 draw3d();raf3d=requestAnimationFrame(animate3d)
}
function start3d(){if(!raf3d){lastFrame=0;raf3d=requestAnimationFrame(animate3d)}}
canvas.addEventListener('pointerdown',e=>{drag3d={x:e.clientX,y:e.clientY,rx:rotX,ry:rotY};dragMoved=false;canvas.setPointerCapture(e.pointerId)});
canvas.addEventListener('pointermove',e=>{if(!drag3d)return;const dx=e.clientX-drag3d.x,dy=e.clientY-drag3d.y;if(Math.hypot(dx,dy)>3)dragMoved=true;rotY=drag3d.ry+dx*.006;rotX=Math.max(-1.25,Math.min(1.25,drag3d.rx+dy*.006));draw3d()});
canvas.addEventListener('pointerup',()=>{drag3d=null});
canvas.addEventListener('pointercancel',()=>{drag3d=null});
canvas.addEventListener('wheel',e=>{e.preventDefault();camZoom=Math.max(.42,Math.min(2.8,camZoom*(e.deltaY>0?.91:1.1)));draw3d()},{passive:false});
canvas.addEventListener('dblclick',()=>{rotX=-.22;rotY=.38;camZoom=1;draw3d()});
canvas.addEventListener('click',e=>{
 if(dragMoved)return;const r=canvas.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
 const state=visible3dState();let bestNode=null,nodeDist=18;
 actual3d.forEach(v=>{if(!state.ids.has(v.id))return;const p=projectVisual(v,r.width,r.height),d=Math.hypot(p.x-mx,p.y-my);if(d<nodeDist){nodeDist=d;bestNode=v.node}});
 if(bestNode){selectNode(bestNode.id);draw3d();return}
 // Выбор ребра в 3D использует тот же edge ID, что и в 2D.
 let bestEdge=null,edgeDist=7;
 state.visibleEdges.forEach(e3=>{
   const a=projectVisual(actual3d[e3.a],r.width,r.height),b=projectVisual(actual3d[e3.b],r.width,r.height);
   const vx=b.x-a.x,vy=b.y-a.y,den=vx*vx+vy*vy||1,t=Math.max(0,Math.min(1,((mx-a.x)*vx+(my-a.y)*vy)/den));
   const d=Math.hypot(mx-(a.x+vx*t),my-(a.y+vy*t));if(d<edgeDist){edgeDist=d;bestEdge=e3.edge}
 });
 if(bestEdge){selectEdge(bestEdge.id);draw3d()}
});
window.addEventListener('resize',resize3d);window.__redraw3d=draw3d;
$$('[data-mode]').forEach(b=>b.onclick=()=>{
 graphMode=b.dataset.mode;$$('[data-mode]').forEach(x=>x.classList.toggle('active',x===b));
 svg.classList.toggle('hidden',graphMode==='3d');canvas.classList.toggle('active',graphMode==='3d');
 storage.setItem('impact-graph-mode',graphMode);
 if(graphMode==='3d'){resize3d();start3d();if(filteredNodes.length>1500)toast('3D отключён для слишком большого графа')}
});


*/

// Impact
const importantNodes=nodes.filter(n=>['METHOD','ROUTE','FUNCTION','COMPONENT','HOOK','TEST'].includes(n.kind));['impactTarget','queryTarget'].forEach(id=>$('#'+id).innerHTML=importantNodes.map(n=>`<option value="${escapeHtml(n.id)}">${escapeHtml(n.name)} · ${n.kind}</option>`).join(''));
$('#impactTarget').value='repository.OrderRepository.save';$('#queryTarget').value='repository.OrderRepository.save';
 const chains=[];
function renderImpact(){
 const groups=[['Подтверждено','confirmed'],['Вероятно','likely'],['Подозрительно','suspicious'],['Не разрешено','unresolved']];
 $('#impactChains').innerHTML=groups.map(([title,status])=>`<section class="chain-section"><div class="chain-section-title"><h2><span class="status-pill ${status==='confirmed'?'good':status==='likely'?'good':status==='suspicious'?'warn':'bad'}">${title}</span></h2><span class="muted">${chains.filter(c=>c.status===status).length} цепочек</span></div><div class="chain-list">${chains.filter(c=>c.status===status).map(c=>`<article class="chain ${status}"><div class="chain-main"><i class="chain-status"></i><div class="chain-text"><strong>${c.label}</strong><div class="chain-path">${c.path.join(' → ')}</div></div><div class="chain-score"><strong>${Math.round(c.score*100)}%</strong><small>расстояние ${c.distance}</small></div></div><div class="chain-details"><div class="step-list">${c.path.map((x,j)=>`${j?'<span class="arrow">→</span>':''}<span class="step">${escapeHtml(x)}</span>`).join('')}</div><div class="calc"><b>${c.category}</b><br>Уверенность цепочки определяется самым слабым воспроизводимым ребром, классом доказательств, штрафом за расстояние и пределом неоднозначности. Альтернативных путей: ${status==='confirmed'?2:status==='likely'?1:0}.</div></div></article>`).join('')}</div></section>`).join('');
 $$('.chain-main').forEach(x=>x.onclick=()=>x.parentElement.classList.toggle('open'));
  const rank=[];
 $('#impactRanking').innerHTML=rank.map((r,i)=>`<div class="rank"><span class="num">${i+1}</span><strong>${r[0]}</strong><b>${r[1]}</b></div>`).join('')
}

// Diagnostics
$('#diagList').innerHTML=diagnostics.map(d=>`<article class="diag"><span class="status-pill ${d.sev==='high'?'bad':d.sev==='medium'?'warn':'good'}">${({high:'высокая',medium:'средняя',low:'низкая'}[d.sev]||d.sev)}</span><div><h3>${escapeHtml(d.category)} · ${escapeHtml(d.scope)}</h3><code>${escapeHtml(d.file)}</code></div><p>${escapeHtml(d.explanation)}</p><div class="diag-action"><b>Рекомендуемое действие</b><br>${escapeHtml(d.action)}<br><span class="tag" style="margin-top:5px">${escapeHtml(d.lib)}</span></div></article>`).join('');

// Queries
const queries=[
['Что сломается при изменении?','Восходящее влияние с тестами и ранжированием доказательств.','impact','i-impact'],
['Кто вызывает эту функцию?','Прямые и транзитивные вызывающие узлы.','impact.callers','i-graph'],
['Какие маршруты используют этот сервис?','Пути от сервиса к публичным эндпоинтам.','impact.routes','i-route'],
['Показать DI-цепочку','Привязки конструктора и провайдеров.','explain.di','i-stack'],
['Показать цепочку frontend → backend','React → HTTP → FastAPI.','impact.fe_be','i-activity'],
['Показать путь к базе данных','Нисходящий путь к ORM и таблице.','impact.database','i-code'],
['Почему эти узлы связаны?','Воспроизводимая цепочка доказательств.','explain.edge','i-check'],
['Показать подозрительные рёбра','Связи с низкой уверенностью и предупреждения.','diagnostics.suspicious','i-warning'],
['Какие тесты нужно запустить?','Связанные тесты, ранжированные по влиянию.','impact.tests','i-test'],
['Показать неразрешённые области','Типизированный диагностический запрос.','diagnostics.unknown','i-search']
];
$('#queryGrid').innerHTML=queries.map((q,i)=>`<button class="query-card" data-query="${i}"><span class="qicon">${icon(q[3])}</span><h3>${q[0]}</h3><p>${q[1]}</p><code>${q[2]}</code></button>`).join('');
function runQuery(i){return null}
$$('.query-card').forEach(b=>b.onclick=()=>runQuery(+b.dataset.query));$('#queryTarget').onchange=()=>$('#typedTarget').textContent='типизированная цель: '+$('#queryTarget').value;$('#queryTarget').onchange();

// The browser is a real client of the local API. There is deliberately no
// fallback graph: without a backend response the gate remains visible.
const backendGate=$('#backendGate'), backendGateMessage=$('#backendGateMessage');
let backendState=null,realGraphMetadata={};
const setBackendMessage=(message)=>{backendGateMessage.textContent=message};
const setBackendStatus=(message,good=true)=>{$('#backendStatus').innerHTML=`<i class="dot"></i>${escapeHtml(message)}`;$('#backendStatus').className=good?'status-good':'status-bad'};
const humanStatus=(value)=>({confirmed:'подтверждено',resolved:'подтверждено',likely:'вероятно',suspicious:'подозрительно',unresolved:'не разрешено',ambiguous:'неоднозначно'}[value]||value||'не определено');
const backendGraph=graph=>graph||{nodes:[],edges:[],metadata:{}};

function refreshRealTargets(){
 const candidates=nodes.filter(n=>['FUNCTION','METHOD','ROUTE','TEST','CLASS','CALL_EXPR'].includes(n.kind));
 ['impactTarget','queryTarget'].forEach(id=>{
  const el=$('#'+id);if(!el)return;
  el.innerHTML=candidates.map(n=>`<option value="${escapeHtml(n.id)}">${escapeHtml(n.name)} · ${escapeHtml(n.kind)}</option>`).join('');
  const defaultNode=candidates.find(n=>edges.some(edge=>edge.from===n.id||edge.to===n.id))||candidates[0];if(defaultNode)el.value=defaultNode.id;
 });
 $('#queryTarget').onchange=()=>$('#typedTarget').textContent='типизированная цель: '+($('#queryTarget').value||'—');
 $('#queryTarget').onchange();
}

function renderRealDiagnostics(){
 const report=(backendGraph(backendState?.graph).metadata||{}).unknown_regions||{};
 const regions=report.regions||report.items||report.unknown_regions||[];
 diagnostics.splice(0,diagnostics.length,...(Array.isArray(regions)?regions:[]).map((item,index)=>({
  sev:item.severity||item.sev||'low',category:item.kind||item.category||'Неразрешённая область',scope:item.scope||item.subject||item.fingerprint||`region-${index+1}`,
  file:item.file||item.location?.file||'—',explanation:item.reason||item.explanation||item.message||'Недостаточно доказательств для разрешения.',
  action:item.action||'Добавить недостающий источник доказательств или support pack.',lib:item.library||item.lib||'—'
 })));
 $('#diagList').innerHTML=diagnostics.map(d=>`<article class="diag"><span class="status-pill ${d.sev==='high'?'bad':d.sev==='medium'?'warn':'good'}">${escapeHtml(humanStatus(d.sev))}</span><div><h3>${escapeHtml(d.category)} · ${escapeHtml(d.scope)}</h3><code>${escapeHtml(d.file)}</code></div><p>${escapeHtml(d.explanation)}</p><div class="diag-action"><b>Рекомендуемое действие</b><br>${escapeHtml(d.action)}<br><span class="tag" style="margin-top:5px">${escapeHtml(d.lib)}</span></div></article>`).join('');
}

function applyRealGraph(payload){
 backendState=payload;const graph=backendGraph(payload.graph), metadata=graph.metadata||{}, rawNodes=graph.nodes||[], rawEdges=graph.edges||[];realGraphMetadata=metadata;
  nodes.splice(0,nodes.length,...rawNodes.map((item,index)=>{const p=item.properties||{};const cols=Math.max(1,Math.ceil(Math.sqrt(rawNodes.length)));const rows=Math.max(1,Math.ceil(rawNodes.length/cols));return {id:item.id,name:item.name||item.id,kind:item.kind,language:p.language||'unknown',file:p.file||p.path||'—',line:p.line||0,x:40+(index%cols)*(1020/Math.max(1,cols-1)),y:35+Math.floor(index/cols)*(690/Math.max(1,rows-1)),role:p.semantic_role||p.role||item.kind.toLowerCase(),confidence:Number(p.confidence??1),impact:0,canonical:p.canonical_id||item.id}}));
 edges.splice(0,edges.length,...rawEdges.map(item=>{const p=item.properties||{};const source=item.source||'EXTRACTED';const status=p.status||p.resolution_status||(source==='RUNTIME_CONFIRMED'?'confirmed':source==='AI_PROPOSED'?'unresolved':Number(item.confidence||0)>=.8?'likely':'suspicious');return {id:item.id,from:item.from,to:item.to,kind:item.kind,status,confidence:Number(item.confidence??0),source:source==='RUNTIME_CONFIRMED'?'CONFIRMED':source==='AI_PROPOSED'?'UNRESOLVED':source==='EXTRACTED'?'INFERRED':source}}));filteredNodes=nodes.slice();
 chains.splice(0,chains.length);
 diagnostics.splice(0,diagnostics.length);libraries.splice(0,libraries.length);const invForLibraries=payload.analysis?.inventory||{};const declaredByEco=invForLibraries.declared_dependencies_by_ecosystem||{};const externalByEco=invForLibraries.external_imports_by_ecosystem||{};const localByEco=invForLibraries.local_modules_by_ecosystem||{};const librarySeen=new Set();const ecosystems=new Set([...Object.keys(declaredByEco),...Object.keys(externalByEco)]);ecosystems.forEach(eco=>{const localRoots=localByEco[eco]||[];const candidates=new Set([...(declaredByEco[eco]||[]),...(externalByEco[eco]||[])]);candidates.forEach(name=>{const isLocal=String(name).startsWith('.')||localRoots.some(root=>name===root||String(name).startsWith(root+'/')||String(name).startsWith(root+'.'));if(isLocal)return;const key=`${eco}:${name}`;if(librarySeen.has(key))return;librarySeen.add(key);libraries.push([name,eco,'—','обнаружена','обнаружена','—','—','—'])})});
 $('#projectSelect').value=payload.project_path||'';$('#backendProject').textContent='проект: '+(payload.project_path||'—');
 const fp=metadata.graph_fingerprint||metadata.core_semantic_fingerprint||metadata.full_graph_fingerprint||'—';$('#graphFingerprint').textContent='graph: '+fp;
 const timing=metadata.stage_timings_seconds||{};const seconds=Object.values(timing).reduce((a,b)=>a+Number(b||0),0);$('#analysisTiming').textContent='анализ: '+(seconds?seconds.toFixed(2)+' с':'—');
 const inv=payload.analysis?.inventory||{};const metrics=document.querySelectorAll('#view-overview .metric strong');const routeCount=nodes.filter(n=>n.kind==='ROUTE').length;const testCount=nodes.filter(n=>n.kind==='TEST').length;const libs=(inv.declared_dependencies||[]).length+(inv.external_imports||[]).length;const totals=metadata.resolution_coverage?.totals||{};const exact=Number(totals.resolved_exact||0),inferred=Number(totals.resolved_inferred||0)+Number(totals.support_pack_resolved||0),ambiguous=Number(totals.ambiguous||0),actionable=Number(totals.actionable_unresolved||0);
 [inv.files_count||0,nodes.length,edges.length,routeCount,testCount,libs,exact,inferred,ambiguous,actionable,seconds?seconds.toFixed(2):'—','—'].forEach((value,index)=>{if(metrics[index])metrics[index].textContent=String(value)});
 const title=$('#view-overview h1');if(title)title.textContent=PathName(payload.project_path||'Проект');
 const overviewPath=$('#view-overview .page-head p');if(overviewPath)overviewPath.textContent='Последний анализ: '+new Date((Number(payload.analyzed_at)||Date.now()/1000)*1000).toLocaleString('ru-RU')+' · '+(payload.project_path||'—');
 const unknownCounts=metadata.unknown_regions?.counts||{};const diagMetrics=document.querySelectorAll('#view-diagnostics .metric strong');[Number(unknownCounts.unresolved||0),Number(unknownCounts.suspicious||0),Number(metadata.language_semantic_capabilities?Object.values(metadata.language_semantic_capabilities).filter(x=>x.capabilities?.framework_rules===false).length:0),Number((metadata.quality_gates||{}).errors||0)].forEach((value,index)=>{if(diagMetrics[index])diagMetrics[index].textContent=String(value)});
 const navBadges=$$('.nav button .badge');[nodes.length,unknownCounts.unresolved||0,metadata.incremental_cache?.cache_hit_rate||'—'].forEach((value,index)=>{if(navBadges[index])navBadges[index].textContent=String(value)});
 const signalLists=document.querySelectorAll('#view-overview .signal-list');if(signalLists[0]){const values=[routeCount,testCount,libraries.length,seconds?seconds.toFixed(2)+' с':'—'];signalLists[0].querySelectorAll('strong').forEach((el,index)=>{el.textContent=String(values[index]??'—')})}
 const qualityRate=Number(totals.eligible_callsites||totals.eligible||0)?Math.round(((exact+inferred)/Number(totals.eligible_callsites||totals.eligible))*100):0;const qualityRows=$('#view-overview .quality-list')?.querySelectorAll('.quality-row');if(qualityRows?.[0]){qualityRows[0].querySelector('b').textContent=qualityRate+'%';qualityRows[0].querySelector('i').style.width=qualityRate+'%'}if(qualityRows?.[1]){qualityRows[1].querySelector('b').textContent=routeCount?'100%':'0%';qualityRows[1].querySelector('i').style.width=routeCount?'100%':'0%'}
 const languages=payload.languages||payload.analysis?.languages||[];const health=$('.sidebar-project .project-health p');if(health)health.innerHTML=`${nodes.length} узлов · ${edges.length} рёбер<br>${languages.length} языков`;
 const stack=$('#detectedStack');if(stack){const detectedLibraries=libraries.map(item=>item[0]);stack.innerHTML=languages.map(language=>`<span class="tag green">${escapeHtml(language)}</span>`).concat(detectedLibraries.map(library=>`<span class="tag">${escapeHtml(library)}</span>`)).join('')||'<span class="tag">нет данных</span>'}
 const notices=$('#view-overview').querySelectorAll('.notice');if(notices[0])notices[0].textContent=`Quality guard: ${String((metadata.quality_gates||{}).status||'результат доступен в диагностике')}. Неизвестные области не маскируются под подтверждённые связи.`;
 $('#visibleCount').textContent=`видно ${nodes.length} из ${nodes.length}`;setBackendStatus('Реальный backend подключён',true);backendGate.classList.add('hidden');
 refreshRealTargets();renderRealDiagnostics();renderGraph();renderImpact();fitGraph();window.__redraw3d?.();
}
function PathName(value){return String(value).replace(/[\\/]+$/,'').split(/[\\/]/).pop()||'Проект'}

function clearInitialView(){
 document.querySelectorAll('.metric strong').forEach(el=>el.textContent='—');
 document.querySelectorAll('.quality-list .quality-row b').forEach(el=>el.textContent='—');
 document.querySelectorAll('.quality-list .bar i').forEach(el=>el.style.width='0%');
 document.querySelectorAll('#view-overview .tag-list').forEach(el=>el.innerHTML='<span class="tag">нет данных</span>');
 document.querySelectorAll('#view-overview .notice').forEach(el=>el.textContent='Ожидание данных реального анализа.');
 const title=$('#view-overview h1');if(title)title.textContent='Проект не анализирован';
 const subtitle=$('#view-overview .page-head p');if(subtitle)subtitle.textContent='Укажите путь к проекту и запустите анализ через локальный backend.';
 const health=$('.sidebar-project .project-health p');if(health)health.textContent='Анализ ещё не запускался';
 $$('.nav button .badge').forEach(b=>b.textContent='0');
  const impactNotice=$('#view-impact .notice span');if(impactNotice)impactNotice.textContent='Ожидание реального impact-запроса.';
  document.querySelectorAll('#view-impact .impact-summary strong').forEach(el=>el.textContent='—');
  const status=$('#view-diagnostics .filters-row .status-pill');if(status)status.textContent='анализ ещё не запускался';
}

async function loadRealState(){
 try{
  const response=await fetch('/api/state',{cache:'no-store'});const state=await response.json();
  if(state.has_analysis){const graphResponse=await fetch('/api/graph',{cache:'no-store'});const graphPayload=await graphResponse.json();if(!graphResponse.ok)throw new Error(graphPayload.error||'Graph request failed');applyRealGraph({...state,...graphPayload});await runRealImpact();return}
  if(state.project_path)$('#projectSelect').value=state.project_path;
  setBackendMessage('Backend доступен. Укажите путь к проекту и нажмите «Анализировать».');setBackendStatus('Backend готов, анализ не запущен',false);backendGate.classList.add('hidden');
 }catch(error){setBackendMessage('Не удалось подключиться к /api/state. Запустите impact-engine-local-api на порту 8001.');setBackendStatus('Backend недоступен',false);console.error(error)}
}

async function analyzeFromBackend(){
 const path=$('#projectSelect').value.trim();if(!path){setBackendMessage('Укажите абсолютный путь к проекту.');backendGate.classList.remove('hidden');return}
 const button=$('#analyzeBtn');button.disabled=true;button.innerHTML='<span class="spinner" style="width:15px;height:15px;margin:0"></span><span>Анализируем</span>';setBackendMessage('Реальный анализ выполняется…');backendGate.classList.remove('hidden');
 const progressTimer=setInterval(async()=>{try{const response=await fetch('/api/progress',{cache:'no-store'});const data=await response.json();const current=data.progress?.current;if(current)setBackendMessage(`${current.overall_percent}% · ${current.message} (${current.processed}/${current.total})`)}catch(error){/* analysis request owns the final error */}},500);
 try{const response=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_path:path})});const data=await response.json();if(!response.ok)throw new Error(data.error||'Analysis failed');applyRealGraph(data);await runRealImpact();toast('Реальный анализ проекта завершён')}
 catch(error){setBackendMessage(String(error.message||error));setBackendStatus('Ошибка backend',false);console.error(error)}
 finally{clearInterval(progressTimer);button.disabled=false;button.innerHTML=`${icon('i-play')}<span>Анализировать</span>`}
}
$('#analyzeBtn').onclick=analyzeFromBackend;

async function runRealImpact(){
 const target=$('#impactTarget').value;if(!target)return;
  try{const response=await fetch('/api/impact',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target,direction:$('#impactDirection').value,max_depth:Number($('#impactDepth').value||8),min_confidence:Number($('#impactConfidence').value||0)})});const data=await response.json();if(!response.ok)throw new Error(data.error||'Impact query failed');const result=data.result||{};const edgeById=new Map((result.affected_edges||[]).map(e=>[e.id,e]));chains.splice(0,chains.length,...(result.impact_paths||[]).slice(0,80).map((path,index)=>{const names=[];(path.edges||[]).forEach(edgeId=>{const edge=edgeById.get(edgeId);if(edge){if(!names.length)names.push(edge.from);names.push(edge.to)}});if(!names.length)names.push(path.target);return {status:path.status||'likely',label:`Путь к ${path.target}`,score:Number(path.chain_confidence??path.confidence??0),distance:path.depth||0,path:names,category:path.chain_status||humanStatus(path.status)}}));renderImpact();const summary=document.querySelectorAll('.impact-card strong');if(summary.length>=4){summary[0].textContent=String((result.confirmed||[]).length);summary[1].textContent=String((result.likely||[]).length);summary[2].textContent=String((result.suspicious||[]).length+(result.not_resolved||[]).length);summary[3].textContent=result.context_efficiency?.context_saved_percent!=null?String(result.context_efficiency.context_saved_percent)+'%':'—'}const ranking=result.impact_ranking||[];$('#impactRanking').innerHTML=ranking.map((item,index)=>`<div class="rank"><span class="num">${index+1}</span><strong>${escapeHtml(item.node_id||item.target||'—')}</strong><b>${Math.round(Number(item.impact_score??item.score??0))}</b></div>`).join('');const efficiency=result.context_efficiency||{};const notice=document.querySelector('#view-impact .notice span');if(notice)notice.textContent=efficiency.context_saved_percent!=null?`Измеренная экономия контекста: ${efficiency.context_saved_percent}%.`:'Сокращение контекста не измерено.'}
  catch(error){toast('Impact backend: '+error.message);console.error(error)}
}
$('#runImpact').onclick=async()=>{const b=$('#runImpact');b.disabled=true;b.textContent='Анализируем';await runRealImpact();b.disabled=false;b.innerHTML=`${icon('i-play')}Запустить анализ`};

async function runQueryReal(i){const q=queries[i],target=$('#queryTarget').value;$('#queryResultTitle').textContent=q[0];$('#queryResult').textContent='Запрос к реальному backend…';try{const response=await fetch('/api/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:q[2],target})});const data=await response.json();if(!response.ok)throw new Error(data.error||'Query failed');$('#queryResult').textContent=JSON.stringify(data.result,null,2)}catch(error){$('#queryResult').textContent=JSON.stringify({status:'error',error:error.message},null,2)}}
 $$('.query-card').forEach(b=>b.onclick=()=>runQueryReal(+b.dataset.query));

// No mock state is rendered: all arrays are cleared before the first render.
nodes.splice(0,nodes.length);edges.splice(0,edges.length);diagnostics.splice(0,diagnostics.length);libraries.splice(0,libraries.length);chains.splice(0,chains.length);
clearInitialView();
renderGraph();renderImpact();fitGraph();
loadRealState();
const saved=storage.getItem('impact-view');if(saved&&$('#view-'+saved))switchView(saved);
const savedNode=storage.getItem('impact-selected-node');if(savedNode&&nodeById(savedNode))selectNode(savedNode);
const savedMode=storage.getItem('impact-graph-mode');if(savedMode==='3d')$$('[data-mode="3d"]')[0].click();
