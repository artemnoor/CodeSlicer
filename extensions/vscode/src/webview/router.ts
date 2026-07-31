export const clientRouter = String.raw`const vscode=typeof acquireVsCodeApi==='function'?acquireVsCodeApi():{getState:()=>undefined,setState:()=>undefined,postMessage:()=>undefined};
const tabs=['start','review','results','tests','architecture','git','tech','history','settings'];
let currentTab=(vscode.getState()||{}).tab||'start';let demoStep=0;let dragState;
const byId=id=>document.getElementById(id);
const isRussian=()=>document.documentElement&&document.documentElement.lang==='ru';
function selectTab(id,focus){if(!tabs.includes(id))return;currentTab=id;document.querySelectorAll('[role=tab]').forEach(tab=>{const selected=tab.dataset.tab===id;tab.setAttribute('aria-selected',String(selected));tab.setAttribute('tabindex',selected?'0':'-1');const panel=byId('panel-'+tab.dataset.tab);if(panel)panel.hidden=!selected});vscode.setState({tab:id});if(focus)document.querySelector('[data-tab="'+id+'"]').focus?.()}
function say(title,text){byId('demo-title').textContent=title;byId('demo-text').textContent=text}
function stopDemo(){byId('demo-guide').hidden=true}
function guideFlow(){return isRussian()?[
 ['1/7 · Проверка','Выберите источник локальных изменений и базовую ветку. Никакая команда ещё не запускается.','review'],
 ['2/7 · Результат','Здесь появятся риск, причины и только подтверждённые evidence chains.','results'],
 ['3/7 · Тесты','Рекомендации отделены от review. Каждый настоящий запуск всегда запрашивает подтверждение.','tests'],
 ['4/7 · Карта','Это короткий срез canonical graph. Полная карта остаётся в Local Hub.','architecture'],
 ['5/7 · Git','Сначала обновите дерево и проверьте направление push. Force push недоступен.','git'],
 ['6/7 · Покрытие','Здесь видно, где встроенный анализ уверен и как подключаются optional packs.','tech'],
 ['Гид завершён','Вы увидели весь безопасный локальный сценарий. Проект не менялся и процессы не запускались.','start']
 ]:[
 ['1/7 · Review','Choose a local change source and base branch. No command runs yet.','review'],
 ['2/7 · Results','Risk, reasons, and only confirmed evidence chains appear here.','results'],
 ['3/7 · Tests','Recommendations are separate from review. Every real run always asks for confirmation.','tests'],
 ['4/7 · Map','This is a small canonical graph slice. The full map stays in Local Hub.','architecture'],
 ['5/7 · Git','Refresh the tree and verify the exact push destination first. Force push is unavailable.','git'],
 ['6/7 · Coverage','See where built-in analysis is confident and how optional packs are connected.','tech'],
 ['Guide complete','You saw the safe local flow. Your project did not change and no process was started.','start']
 ]}
function showDemoStep(step){demoStep=step;const flow=guideFlow();const item=flow[Math.min(step,flow.length-1)];say(item[0],item[1]);selectTab(item[2],true)}
function startDemo(){const guide=byId('demo-guide');guide.hidden=false;showDemoStep(0);byId('demo-title').focus?.()}
function moveGuide(event){if(!dragState)return;const guide=byId('demo-guide');guide.style.left=Math.max(8,event.clientX-dragState.x)+'px';guide.style.top=Math.max(8,event.clientY-dragState.y)+'px';guide.style.right='auto';guide.style.bottom='auto'}
document.addEventListener('pointerdown',event=>{const handle=event.target&&event.target.closest&&event.target.closest('[data-guide-handle]');if(!handle)return;const guide=byId('demo-guide');const box=guide.getBoundingClientRect?.();if(!box)return;dragState={x:event.clientX-box.left,y:event.clientY-box.top};handle.setPointerCapture?.(event.pointerId);event.preventDefault?.()});
document.addEventListener('pointermove',moveGuide);document.addEventListener('pointerup',()=>{dragState=undefined});document.addEventListener('pointercancel',()=>{dragState=undefined});
document.addEventListener('keydown',event=>{const tab=event.target&&event.target.closest&&event.target.closest('[role=tab]');if(event.key==='Escape'&&!byId('demo-guide').hidden){stopDemo();return}if(!tab)return;const index=tabs.indexOf(tab.dataset.tab);let next=-1;if(event.key==='ArrowDown'||event.key==='ArrowRight')next=(index+1)%tabs.length;if(event.key==='ArrowUp'||event.key==='ArrowLeft')next=(index-1+tabs.length)%tabs.length;if(event.key==='Home')next=0;if(event.key==='End')next=tabs.length-1;if(next>=0){event.preventDefault?.();selectTab(tabs[next],true)}});
document.addEventListener('click',event=>{const target=event.target&&event.target.closest&&event.target.closest('button');if(!target)return;if(target.dataset.guideHandle!==undefined)return;if(target.dataset.language)return vscode.postMessage({type:'setLanguage',language:target.dataset.language});if(target.dataset.tab)return selectTab(target.dataset.tab,true);if(target.dataset.demoStart!==undefined)return startDemo();if(target.dataset.demoNext!==undefined)return showDemoStep(demoStep+1);if(target.dataset.demoStop!==undefined)return stopDemo();if(target.dataset.action)return vscode.postMessage({type:'action',action:target.dataset.action});if(target.dataset.test!==undefined)return vscode.postMessage({type:'runTest',index:Number(target.dataset.test)});if(target.dataset.entity)return vscode.postMessage({type:'entity',entity:target.dataset.entity,file:target.dataset.file,line:Number(target.dataset.line)||undefined})});
if(typeof window!=='undefined')window.addEventListener('message',event=>{if(event.data&&event.data.type==='showDemo')startDemo()});selectTab(currentTab,false);`;
