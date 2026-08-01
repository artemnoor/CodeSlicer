export const clientRouter = String.raw`const vscode=typeof acquireVsCodeApi==='function'?acquireVsCodeApi():{getState:()=>undefined,setState:()=>undefined,postMessage:()=>undefined};
const tabs=['start','review','results','tests','architecture','git','guides','tech','history','settings'];
const savedState=vscode.getState()||{};let currentTab=savedState.tab||'start';let demoStep=Number(savedState.guideStep)||0;let guideId=savedState.guideId||'review';let guideOpen=Boolean(savedState.guideOpen);let dragState;
function persist(){vscode.setState({tab:currentTab,guideStep:demoStep,guideId,guideOpen})}
const byId=id=>document.getElementById(id);const isRussian=()=>document.documentElement&&document.documentElement.lang==='ru';
function selectTab(id,focus){if(!tabs.includes(id))return;currentTab=id;document.querySelectorAll('[role=tab]').forEach(tab=>{const selected=tab.dataset.tab===id;tab.setAttribute('aria-selected',String(selected));tab.setAttribute('tabindex',selected?'0':'-1');const panel=byId('panel-'+tab.dataset.tab);if(panel)panel.hidden=!selected});persist();if(focus)document.querySelector('[data-tab="'+id+'"]').focus?.()}
function say(title,text,status){byId('demo-title').textContent=title;byId('demo-text').textContent=status?text+'\n'+status:text}
function clearGuideTarget(){document.querySelectorAll('.guide-target').forEach(node=>node.classList?.remove?.('guide-target'))}
function highlight(selector){clearGuideTarget();if(!selector)return;const target=document.querySelector(selector);if(!target)return;target.classList?.add?.('guide-target');const move=()=>target.scrollIntoView?.({block:'center',inline:'nearest'});if(typeof requestAnimationFrame==='function')requestAnimationFrame(move);else move()}
function stopDemo(){guideOpen=false;persist();byId('demo-guide').hidden=true;clearGuideTarget()}
function guideFlows(){const ru=isRussian();return {
 review:ru?[
  ['1/4 · Выберите изменения','Выберите, что проверить: изменения в рабочей папке, staged‑файлы, сравнение веток или diff‑файл.','review','#panel-review .field-group'],
  ['2/4 · Укажите базовую ветку','Проверьте, с какой веткой сравниваются изменения. Если нужно, выберите «Изменить базу».','review','#panel-review .base-readout'],
  ['3/4 · Запустите проверку','Нажмите «Запустить проверку». CodeSlicer анализирует только локальный Git diff и не отправляет ваш код в GitHub.','review','[data-action="review"]'],
  ['4/4 · Прочитайте результат','После проверки откройте результат: риск, причина, затронутые части кода и доказательства.','results','#panel-results .metric-grid']
 ]:[
  ['1/4 · Choose changes','Choose working changes, staged files, branch comparison, or a diff file.','review','#panel-review .field-group'],
  ['2/4 · Check the base branch','Confirm the branch used for comparison. Choose Change base if needed.','review','#panel-review .base-readout'],
  ['3/4 · Run the review','Choose Run review. CodeSlicer analyzes only a local Git diff and never sends your code to GitHub.','review','[data-action="review"]'],
  ['4/4 · Read the result','Open Results to see risk, reasons, affected code, and evidence.','results','#panel-results .metric-grid']
 ],
 git:ru?[
  ['1/5 · Посмотрите состояние Git','Эта карточка показывает ветки, remotes и историю. Она ничего не меняет.','git','[data-guide-anchor="git-status"]'],
  ['2/5 · Создайте ветку','Введите понятное имя, например feature/my-task. Git создаст ветку и сразу перейдёт на неё.','git','[data-guide-anchor="git-branch"]'],
  ['3/5 · Переключитесь при необходимости','Если рабочая ветка уже существует, выберите её. При незавершённых изменениях Git объяснит, почему переход недоступен.','git','[data-guide-anchor="git-switch"]'],
  ['4/5 · Подключите remote','Сначала введите имя origin, затем HTTPS или SSH‑адрес. На этом шаге код ещё не отправляется.','git','[data-guide-anchor="git-remote"]'],
  ['5/5 · Проверьте и отправьте','Сначала проверьте направление push, затем внимательно подтвердите отправку. Force push недоступен.','git','[data-guide-anchor="git-push"]']
 ]:[
  ['1/5 · View Git status','This card shows branches, remotes, and history. It changes nothing.','git','[data-guide-anchor="git-status"]'],
  ['2/5 · Create a branch','Enter a clear name such as feature/my-task. Git creates the branch and switches to it.','git','[data-guide-anchor="git-branch"]'],
  ['3/5 · Switch if needed','Choose an existing working branch. If unfinished changes prevent it, Git explains why switching is unavailable.','git','[data-guide-anchor="git-switch"]'],
  ['4/5 · Connect a remote','First enter origin, then an HTTPS or SSH address. No code is sent at this step.','git','[data-guide-anchor="git-remote"]'],
  ['5/5 · Check and push','Check the destination first, then carefully confirm the push. Force push is unavailable.','git','[data-guide-anchor="git-push"]']
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
function extraGuideFlow(id,ru){const flows=ru?{
 start:[
  ['1/3 · Посмотрите статус проекта','На главном экране видно, есть ли папка, Git и готовый CodeSlicer runtime. Ничего не запускается автоматически.','start','#panel-start'],
  ['2/3 · Подготовьте папку','Если папка пустая, откройте проект или импортируйте репозиторий. Если Git ещё не подключён, инициализируйте его одной кнопкой.','start','#panel-start .action-row'],
  ['3/3 · Перейдите к проверке','Когда проект готов, выберите «Проверка изменений». Так вы увидите риск и рекомендуемые тесты до commit.','review','#panel-review .field-group']
 ],
 github:[
  ['1/3 · Откройте настройки','GitHub нужен только для проверки Pull Request. Обычная проверка изменений работает полностью локально.','settings','#panel-settings .info-card--secure'],
  ['2/3 · Выберите безопасный вход','Можно использовать вход VS Code OAuth или сохранить личный token в Secret Storage VS Code. Token не попадёт в Git remote и логи.','settings','[data-action="configureGitHubToken"]'],
  ['3/3 · Выберите GitHub PR','После входа выберите GitHub PR как источник изменений. Diff анализируется локально в вашем workspace.','review','#panel-review .field-group']
 ],
 graphify:[
  ['1/3 · Откройте карту CodeSlicer','Сначала посмотрите подтверждённые связи CodeSlicer. Это основной источник риска и evidence.','architecture','#panel-architecture .graph-console'],
  ['2/3 · Подключите готовый Graphify','Graphify не скачивается автоматически. Если он уже настроен, подключите его как отдельную архитектурную карту.','architecture','[data-action="configureGraphify"]'],
  ['3/3 · Не смешивайте результаты','Graphify помогает исследовать архитектуру, но не изменяет риск и доказательства CodeSlicer.','architecture','#panel-architecture .content-section']
 ]
}:{
 start:[
  ['1/3 · Check the project status','The overview shows whether the folder, Git, and the CodeSlicer runtime are ready. Nothing starts automatically.','start','#panel-start'],
  ['2/3 · Prepare the folder','For an empty folder, open a project or import a repository. If Git is missing, initialize it with one action.','start','#panel-start .action-row'],
  ['3/3 · Move to review','When the project is ready, choose Review changes to see risk and recommended tests before a commit.','review','#panel-review .field-group']
 ],
 github:[
  ['1/3 · Open settings','GitHub is only needed for pull-request review. Local change review works fully offline.','settings','#panel-settings .info-card--secure'],
  ['2/3 · Choose a safe sign-in','Use VS Code OAuth or store a personal token in VS Code Secret Storage. The token never goes into a Git remote or logs.','settings','[data-action="configureGitHubToken"]'],
  ['3/3 · Choose GitHub PR','After signing in, choose GitHub PR as the change source. The diff is analyzed locally in your workspace.','review','#panel-review .field-group']
 ],
 graphify:[
  ['1/3 · Open the CodeSlicer map','Start with confirmed CodeSlicer relationships. They are the main source of risk and evidence.','architecture','#panel-architecture .graph-console'],
  ['2/3 · Connect existing Graphify','Graphify is never downloaded automatically. Connect it as a separate architecture map only if it is already configured.','architecture','[data-action="configureGraphify"]'],
  ['3/3 · Keep results separate','Graphify helps explore architecture but never changes CodeSlicer risk or evidence.','architecture','#panel-architecture .content-section']
 ]
};return flows[id]}
function normalizedGuide(id){if(id==='git-status'||id==='git-branch'||id==='git-switch'||id==='git-remote'||id==='git-push')return 'git';return ['start','review','git','tests','map','github','graphify'].includes(id)?id:'review'}
function currentFlow(){return guideFlows()[guideId]||extraGuideFlow(guideId,isRussian())||guideFlows().review}
function expectedAction(){const rules={review:{0:'source',2:'review'},git:{0:'showGit',1:'createBranch',2:'switchBranch',3:'addRemote',4:'pushBranch'},tests:{1:'runTest'},map:{0:'showGraph'},github:{1:'githubAuth'},graphify:{1:'configureGraphify'},start:{1:'initGit'}};return rules[guideId]?.[demoStep]}
function actionMatches(expected,action){return expected==='source'?String(action).startsWith('source'):expected==='githubAuth'?['configureGitHubToken','sourceGitHub'].includes(String(action)):expected===action}
function waitingCopy(action){const ru=isRussian();const names={source:ru?'выберите источник изменений':'choose a change source',review:ru?'запустите проверку':'run the review',showGit:ru?'обновите состояние Git':'refresh Git status',createBranch:ru?'создайте ветку':'create a branch',switchBranch:ru?'переключите ветку':'switch a branch',addRemote:ru?'подключите remote':'connect a remote',pushBranch:ru?'отправьте ветку':'push the branch',runTest:ru?'запустите тест после подтверждения':'run the test after confirmation',showGraph:ru?'покажите карту':'show the map',githubAuth:ru?'войдите в GitHub или сохраните токен':'sign in to GitHub or save a token',configureGraphify:ru?'подключите Graphify':'connect Graphify',initGit:ru?'инициализируйте Git':'initialize Git'};return (ru?'Рекомендуемое действие: ':'Recommended action: ')+(names[action]||action)+'. '+(ru?'Можно нажать «Далее», чтобы пропустить этот шаг.':'You can choose Next to skip this step.')}
function showDemoStep(step,status){const flow=currentFlow();demoStep=Math.min(step,flow.length-1);const item=flow[demoStep];const expected=expectedAction();say(item[0],item[1],status|| (expected?waitingCopy(expected):''));selectTab(item[2],true);highlight(item[3]);persist()}
function advanceGuide(status){const flow=currentFlow();if(demoStep>=flow.length-1){say(isRussian()?'Гид завершён':'Guide complete',isRussian()?'Сценарий пройден. Вы можете продолжить работу в любой вкладке.':'This journey is complete. You can continue in any tab.',status||'');guideOpen=false;persist();clearGuideTarget();return}showDemoStep(demoStep+1,status)}
function startDemo(id='review'){guideId=normalizedGuide(id);demoStep=0;guideOpen=true;byId('demo-guide').hidden=false;showDemoStep(0);byId('demo-title').focus?.()}
function moveGuide(event){if(!dragState)return;const guide=byId('demo-guide');guide.style.left=Math.max(8,event.clientX-dragState.x)+'px';guide.style.top=Math.max(8,event.clientY-dragState.y)+'px';guide.style.right='auto';guide.style.bottom='auto'}
document.addEventListener('pointerdown',event=>{const handle=event.target&&event.target.closest&&event.target.closest('[data-guide-handle]');if(!handle)return;const guide=byId('demo-guide');const box=guide.getBoundingClientRect?.();if(!box)return;dragState={x:event.clientX-box.left,y:event.clientY-box.top};handle.setPointerCapture?.(event.pointerId);event.preventDefault?.()});
document.addEventListener('pointermove',moveGuide);document.addEventListener('pointerup',()=>{dragState=undefined});document.addEventListener('pointercancel',()=>{dragState=undefined});
document.addEventListener('keydown',event=>{const tab=event.target&&event.target.closest&&event.target.closest('[role=tab]');if(event.key==='Escape'&&!byId('demo-guide').hidden){stopDemo();return}if(!tab)return;const index=tabs.indexOf(tab.dataset.tab);let next=-1;if(event.key==='ArrowDown'||event.key==='ArrowRight')next=(index+1)%tabs.length;if(event.key==='ArrowUp'||event.key==='ArrowLeft')next=(index-1+tabs.length)%tabs.length;if(event.key==='Home')next=0;if(event.key==='End')next=tabs.length-1;if(next>=0){event.preventDefault?.();selectTab(tabs[next],true)}});
document.addEventListener('click',event=>{const target=event.target&&event.target.closest&&event.target.closest('button');if(!target)return;if(target.dataset.guideHandle!==undefined)return;if(target.dataset.language)return vscode.postMessage({type:'setLanguage',language:target.dataset.language});if(target.dataset.tab)return selectTab(target.dataset.tab,true);if(target.dataset.guide)return startDemo(target.dataset.guide);if(target.dataset.demoStart!==undefined)return startDemo();if(target.dataset.demoNext!==undefined)return advanceGuide();if(target.dataset.demoStop!==undefined)return stopDemo();if(target.dataset.action){const action=target.dataset.action;const expected=guideOpen&&expectedAction();if(expected&&!actionMatches(expected,action))say(isRussian()?'Сначала другой шаг':'A different step comes first',waitingCopy(expected));return vscode.postMessage({type:'action',action,guide:guideOpen?{id:guideId,step:demoStep,expected}:undefined})}if(target.dataset.test!==undefined){const expected=guideOpen&&expectedAction();if(expected&&!actionMatches(expected,'runTest'))say(isRussian()?'Сначала другой шаг':'A different step comes first',waitingCopy(expected));return vscode.postMessage({type:'runTest',index:Number(target.dataset.test),guide:guideOpen?{id:guideId,step:demoStep,expected}:undefined})}if(target.dataset.entity)return vscode.postMessage({type:'entity',entity:target.dataset.entity,file:target.dataset.file,line:Number(target.dataset.line)||undefined})});
if(typeof window!=='undefined')window.addEventListener('message',event=>{const data=event.data||{};if(data.type==='showDemo')return startDemo();if(data.type==='openTab'&&tabs.includes(data.tab))return selectTab(data.tab,true);if(data.type==='guideEvent'&&guideOpen){const expected=expectedAction();if(!expected||!actionMatches(expected,data.action))return;if(data.status==='success')return advanceGuide(isRussian()?'Шаг выполнен. Переходим дальше.':'Step complete. Moving on.');const message=data.message||(isRussian()?'Действие не завершилось. Проверьте подсказку VS Code и попробуйте ещё раз.':'The action did not finish. Check the VS Code hint and try again.');say(isRussian()?'Шаг ещё не выполнен':'This step is not complete',message,waitingCopy(expected))}});selectTab(currentTab,false);if(guideOpen){byId('demo-guide').hidden=false;showDemoStep(demoStep)} `;
