export const clientRouter = String.raw`const vscode=typeof acquireVsCodeApi==='function'?acquireVsCodeApi():{getState:()=>undefined,setState:()=>undefined,postMessage:()=>undefined};
const tabs=['start','review','results','tests','architecture','git','guides','tech','history','settings'];
let currentTab=(vscode.getState()||{}).tab||'start';let demoStep=0;let guideId='review';let dragState;
const byId=id=>document.getElementById(id);const isRussian=()=>document.documentElement&&document.documentElement.lang==='ru';
function selectTab(id,focus){if(!tabs.includes(id))return;currentTab=id;document.querySelectorAll('[role=tab]').forEach(tab=>{const selected=tab.dataset.tab===id;tab.setAttribute('aria-selected',String(selected));tab.setAttribute('tabindex',selected?'0':'-1');const panel=byId('panel-'+tab.dataset.tab);if(panel)panel.hidden=!selected});vscode.setState({tab:id});if(focus)document.querySelector('[data-tab="'+id+'"]').focus?.()}
function say(title,text){byId('demo-title').textContent=title;byId('demo-text').textContent=text}
function clearGuideTarget(){document.querySelectorAll('.guide-target').forEach(node=>node.classList?.remove?.('guide-target'))}
function highlight(selector){clearGuideTarget();if(!selector)return;const target=document.querySelector(selector);if(!target)return;target.classList?.add?.('guide-target');const move=()=>target.scrollIntoView?.({block:'center',inline:'nearest'});if(typeof requestAnimationFrame==='function')requestAnimationFrame(move);else move()}
function stopDemo(){byId('demo-guide').hidden=true;clearGuideTarget()}
function guideFlows(){const ru=isRussian();return {
 review:ru?[
  ['1/3 · Выберите изменения','Здесь выберите, что именно хотите проверить: незакоммиченные изменения, staged‑файлы, сравнение веток или diff‑файл.','review','#panel-review .field-group'],
  ['2/3 · Укажите базу','Проверьте, с какой веткой сравниваются изменения. Если нужно, нажмите «Изменить базу».','review','#panel-review .base-readout'],
  ['3/3 · Прочитайте результат','После проверки здесь будут риск, причина, затронутые части кода и доказательства.','results','#panel-results .metric-grid']
 ]:[
  ['1/3 · Choose changes','Choose what to review: working changes, staged files, branches, or a diff file.','review','#panel-review .field-group'],
  ['2/3 · Check the base','Confirm the branch used for comparison. Choose Change base if needed.','review','#panel-review .base-readout'],
  ['3/3 · Read the result','After review, this is where risk, reasons, affected code, and evidence appear.','results','#panel-results .metric-grid']
 ],
 git:ru?[
  ['1/4 · Посмотрите состояние','Эта карточка только показывает ветки, remotes и историю. Она ничего не меняет.','git','[data-guide-anchor="git-status"]'],
  ['2/4 · Создайте ветку','Нажмите эту кнопку. Затем введите имя, например feature/my-task. Git создаст ветку и перейдёт на неё.','git','[data-guide-anchor="git-branch"]'],
  ['3/4 · Подключите remote','Сначала введите имя origin, затем HTTPS или SSH‑адрес. На этом шаге код ещё не отправляется.','git','[data-guide-anchor="git-remote"]'],
  ['4/4 · Проверьте и отправьте','Сначала проверьте направление push, затем внимательно подтвердите отправку. Force push недоступен.','git','[data-guide-anchor="git-push"]']
 ]:[
  ['1/4 · See the state','This card only shows branches, remotes, and history. It changes nothing.','git','[data-guide-anchor="git-status"]'],
  ['2/4 · Create a branch','Select this button, then enter a name such as feature/my-task. Git creates the branch and switches to it.','git','[data-guide-anchor="git-branch"]'],
  ['3/4 · Connect a remote','First enter origin, then an HTTPS or SSH address. No code is sent at this step.','git','[data-guide-anchor="git-remote"]'],
  ['4/4 · Check and push','Check the destination first, then carefully confirm the push. Force push is unavailable.','git','[data-guide-anchor="git-push"]']
 ],
 tests:ru?[
  ['1/2 · Посмотрите рекомендацию','Здесь CodeSlicer объясняет, какой тест связан с изменением и почему его стоит запустить.','tests','#panel-tests .stack'],
  ['2/2 · Запустите только с подтверждением','Кнопка запуска всегда показывает отдельное подтверждение с точной командой.','tests','#panel-tests .stack']
 ]:[
  ['1/2 · Read the recommendation','CodeSlicer explains which test relates to a change and why it is useful.','tests','#panel-tests .stack'],
  ['2/2 · Run only after confirmation','The run button always shows a separate confirmation with the exact command.','tests','#panel-tests .stack']
 ],
 map:ru?[
  ['1/2 · Посмотрите компактную карту','Карта показывает только ближайшие подтверждённые связи, а не весь граф проекта.','architecture','#panel-architecture .graph-console'],
  ['2/2 · Откройте подробности при необходимости','Для большого графа используйте Local Hub. Graphify остаётся отдельным инструментом.','architecture','#panel-architecture .content-section']
 ]:[
  ['1/2 · View the compact map','The map shows only the closest confirmed relationships, not the whole project graph.','architecture','#panel-architecture .graph-console'],
  ['2/2 · Open details when needed','Use Local Hub for the larger graph. Graphify remains a separate tool.','architecture','#panel-architecture .content-section']
 ]
 }}
function normalizedGuide(id){if(id==='git-status'||id==='git-branch'||id==='git-switch'||id==='git-remote'||id==='git-push')return 'git';return ['review','git','tests','map'].includes(id)?id:'review'}
function showDemoStep(step){const flow=guideFlows()[guideId]||guideFlows().review;demoStep=Math.min(step,flow.length-1);const item=flow[demoStep];say(item[0],item[1]);selectTab(item[2],true);highlight(item[3])}
function startDemo(id='review'){guideId=normalizedGuide(id);byId('demo-guide').hidden=false;showDemoStep(0);byId('demo-title').focus?.()}
function moveGuide(event){if(!dragState)return;const guide=byId('demo-guide');guide.style.left=Math.max(8,event.clientX-dragState.x)+'px';guide.style.top=Math.max(8,event.clientY-dragState.y)+'px';guide.style.right='auto';guide.style.bottom='auto'}
document.addEventListener('pointerdown',event=>{const handle=event.target&&event.target.closest&&event.target.closest('[data-guide-handle]');if(!handle)return;const guide=byId('demo-guide');const box=guide.getBoundingClientRect?.();if(!box)return;dragState={x:event.clientX-box.left,y:event.clientY-box.top};handle.setPointerCapture?.(event.pointerId);event.preventDefault?.()});
document.addEventListener('pointermove',moveGuide);document.addEventListener('pointerup',()=>{dragState=undefined});document.addEventListener('pointercancel',()=>{dragState=undefined});
document.addEventListener('keydown',event=>{const tab=event.target&&event.target.closest&&event.target.closest('[role=tab]');if(event.key==='Escape'&&!byId('demo-guide').hidden){stopDemo();return}if(!tab)return;const index=tabs.indexOf(tab.dataset.tab);let next=-1;if(event.key==='ArrowDown'||event.key==='ArrowRight')next=(index+1)%tabs.length;if(event.key==='ArrowUp'||event.key==='ArrowLeft')next=(index-1+tabs.length)%tabs.length;if(event.key==='Home')next=0;if(event.key==='End')next=tabs.length-1;if(next>=0){event.preventDefault?.();selectTab(tabs[next],true)}});
document.addEventListener('click',event=>{const target=event.target&&event.target.closest&&event.target.closest('button');if(!target)return;if(target.dataset.guideHandle!==undefined)return;if(target.dataset.language)return vscode.postMessage({type:'setLanguage',language:target.dataset.language});if(target.dataset.tab)return selectTab(target.dataset.tab,true);if(target.dataset.guide)return startDemo(target.dataset.guide);if(target.dataset.demoStart!==undefined)return startDemo();if(target.dataset.demoNext!==undefined)return showDemoStep(demoStep+1);if(target.dataset.demoStop!==undefined)return stopDemo();if(target.dataset.action)return vscode.postMessage({type:'action',action:target.dataset.action});if(target.dataset.test!==undefined)return vscode.postMessage({type:'runTest',index:Number(target.dataset.test)});if(target.dataset.entity)return vscode.postMessage({type:'entity',entity:target.dataset.entity,file:target.dataset.file,line:Number(target.dataset.line)||undefined})});
if(typeof window!=='undefined')window.addEventListener('message',event=>{if(event.data&&event.data.type==='showDemo')startDemo()});selectTab(currentTab,false);`;
