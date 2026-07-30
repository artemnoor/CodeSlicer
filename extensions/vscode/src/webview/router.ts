export const clientRouter = String.raw`const vscode=typeof acquireVsCodeApi==='function'?acquireVsCodeApi():{getState:()=>undefined,setState:()=>undefined,postMessage:()=>undefined};
const tabs=['start','check','result','tests','architecture','settings'];
const saved=vscode.getState()||{};let currentTab=tabs.includes(saved.tab)?saved.tab:'start';
function byId(id){return document.getElementById(id)}
function selectTab(id,moveFocus){
  if(!tabs.includes(id))return;
  currentTab=id;
  document.querySelectorAll('[role=tab]').forEach(item=>{
    const selected=item.dataset.tab===id;
    item.setAttribute('aria-selected',String(selected));
    const panel=byId('panel-'+item.dataset.tab);
    if(panel)panel.hidden=!selected;
  });
  vscode.setState({tab:currentTab});
  if(moveFocus){const button=document.querySelector('[data-tab="'+id+'"]');if(button)button.focus()}
}
document.addEventListener('click',event=>{
  const target=event.target&&typeof event.target.closest==='function'?event.target.closest('button'):undefined;
  if(!target)return;
  if(target.dataset.tab){selectTab(target.dataset.tab,true);return;}
  if(target.dataset.action){vscode.postMessage({type:'action',action:target.dataset.action});return;}
  if(target.dataset.test!==undefined){vscode.postMessage({type:'runTest',index:Number(target.dataset.test)});return;}
  if(target.dataset.entity){vscode.postMessage({type:'entity',entity:target.dataset.entity,file:target.dataset.file,line:Number(target.dataset.line)||undefined});}
});
selectTab(currentTab,false);`;
