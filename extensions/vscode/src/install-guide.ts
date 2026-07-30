import { Uri, WebviewPanel, ViewColumn, window, env } from "vscode";

export const CODESLICER_ARCHIVE = "https://github.com/artemnoor/CodeSlicer/archive/refs/heads/main.zip";
const GRAPHIFY_ARCHIVE = "https://github.com/Graphify-Labs/graphify/archive/refs/heads/v8.zip";

type Language = "ru" | "en";

export interface InstallGuideActions {
  downloadCodeSlicer: () => Promise<void>;
  setupSkills: () => Promise<void>;
}

const copy = {
  ru: {
    title: "Установка CodeSlicer", eyebrow: "БЫСТРЫЙ СТАРТ", heading: "CodeSlicer — за пару кликов",
    intro: "Нажмите установку: расширение само скачает CodeSlicer в служебную папку VS Code, создаст локальную среду и подключит executable. Папки и пути указывать не нужно.",
    downloadTitle: "1. Установить автоматически", downloadText: "Один клик устанавливает CodeSlicer и сразу подключает его к расширению. Ход установки виден в уведомлении и Output.", downloadCode: "Установить CodeSlicer",
    skillsTitle: "2. IDE и skills — по желанию", skillsText: "Если нужен AI-workflow, откройте короткое меню PowerShell: ↑/↓ — IDE, Space — выбор, Enter — установка.", setupSkills: "Выбрать IDE и skills",
    graphTitle: "Graphify — по желанию", graphText: "Отдельный инструмент для обзорной карты архитектуры. Он не меняет risk и evidence CodeSlicer.", downloadGraph: "Скачать Graphify",
    safety: "CodeSlicer и Graphify независимы. Базовая установка затрагивает только служебную папку VS Code; PowerShell открывается лишь для дополнительного выбора IDE и skills."
  },
  en: {
    title: "Install CodeSlicer", eyebrow: "QUICK START", heading: "CodeSlicer in a couple of clicks",
    intro: "Press install: the extension downloads CodeSlicer into VS Code private storage, creates the local environment, and connects its executable. No folders or paths are required.",
    downloadTitle: "1. Install automatically", downloadText: "One click installs CodeSlicer and connects it to the extension. Progress stays visible in the notification and Output.", downloadCode: "Install CodeSlicer",
    skillsTitle: "2. IDE and skills — optional", skillsText: "For an AI workflow, open the short PowerShell menu: ↑/↓ moves, Space selects, and Enter installs.", setupSkills: "Choose IDE and skills",
    graphTitle: "Graphify — optional", graphText: "A separate tool for an architecture overview. It never changes CodeSlicer risk or evidence.", downloadGraph: "Download Graphify",
    safety: "CodeSlicer and Graphify are independent. Base setup touches only VS Code private storage; PowerShell opens only for the optional IDE and skills selection."
  }
} as const;

export function renderInstallGuide(language: Language): string {
  const t = copy[language];
  return `<!DOCTYPE html><html lang="${language}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>${t.title}</title><style>
  :root{color-scheme:dark;--green:#50ed7b;--ink:#0b100c;--line:#2a4030;--text:#f0f6f1;--muted:#a8b5ab;--card:#101812}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 83% 0,#174d2b 0,transparent 31%),var(--ink);color:var(--text);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:760px;margin:0 auto;padding:44px 28px}.eyebrow{margin:0;color:var(--green);font:700 11px/1 ui-monospace,Consolas,monospace;letter-spacing:.12em}.heading{max-width:700px;margin:10px 0 8px;font-size:34px;letter-spacing:-.04em;line-height:1.07}.intro{max-width:720px;margin:0;color:var(--muted)}.steps{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:28px}.card{display:grid;align-content:start;gap:13px;min-height:255px;padding:21px;border:1px solid var(--line);border-radius:15px;background:linear-gradient(145deg,rgba(30,45,34,.96),var(--card));box-shadow:0 18px 52px rgba(0,0,0,.25)}.card.highlight{border-color:#4c9b60;background:linear-gradient(145deg,rgba(30,63,40,.96),var(--card))}.number{display:grid;place-items:center;width:34px;height:34px;border-radius:10px;background:rgba(80,237,123,.14);color:var(--green);font:700 13px ui-monospace,Consolas,monospace}.card h2{margin:3px 0 0;font-size:20px;letter-spacing:-.02em}.card p{margin:0;color:var(--muted)}.actions{display:grid;gap:8px;margin-top:auto}.button{display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:9px 12px;border:1px solid #53c971;border-radius:9px;background:#42db6c;color:#07100a;font-weight:750;cursor:pointer}.button:hover{background:#66f38c}.button:focus-visible{outline:3px solid #a6ffc0;outline-offset:3px}.button.secondary{border-color:var(--line);background:transparent;color:var(--text)}.button.secondary:hover{border-color:#6b9b75;background:rgba(255,255,255,.04)}.optional{margin-top:14px;padding:18px 21px;border:1px solid var(--line);border-radius:15px;background:rgba(16,24,18,.85)}.optional h2{margin:0 0 4px;font-size:18px}.optional p{margin:0 0 12px;color:var(--muted)}.safety{margin-top:18px;padding:13px 15px;border-left:3px solid var(--green);border-radius:0 10px 10px 0;background:rgba(80,237,123,.08);color:#cfddd1;font-size:13px}@media(max-width:760px){main{padding:28px 16px}.heading{font-size:27px}.steps{grid-template-columns:1fr}.card{min-height:0}}
  </style></head><body><main><p class="eyebrow">${t.eyebrow}</p><h1 class="heading">${t.heading}</h1><p class="intro">${t.intro}</p><section class="steps"><article class="card highlight"><span class="number">01</span><h2>${t.downloadTitle}</h2><p>${t.downloadText}</p><div class="actions"><button class="button" type="button" data-action="downloadCodeSlicer">${t.downloadCode}</button></div></article><article class="card"><span class="number">02</span><h2>${t.skillsTitle}</h2><p>${t.skillsText}</p><div class="actions"><button class="button secondary" type="button" data-action="setupSkills">${t.setupSkills}</button></div></article></section><section class="optional"><h2>${t.graphTitle}</h2><p>${t.graphText}</p><button class="button secondary" type="button" data-action="downloadGraphify">${t.downloadGraph}</button></section><p class="safety">${t.safety}</p></main><script>const vscode=acquireVsCodeApi();document.addEventListener("click",event=>{const button=event.target.closest("button[data-action]");if(button)vscode.postMessage({type:"action",action:button.dataset.action})});</script></body></html>`;
}

export function showInstallGuide(language: Language, actions: InstallGuideActions): WebviewPanel {
  const panel = window.createWebviewPanel("codeslicer.downloadTools", copy[language].title, ViewColumn.Active, { enableScripts: true });
  panel.webview.html = renderInstallGuide(language);
  panel.webview.onDidReceiveMessage(async (message: { type?: string; action?: string }) => {
    if (message.type !== "action") return;
    if (message.action === "downloadCodeSlicer") await actions.downloadCodeSlicer();
    if (message.action === "downloadGraphify") await env.openExternal(Uri.parse(GRAPHIFY_ARCHIVE));
    if (message.action === "setupSkills") await actions.setupSkills();
  });
  return panel;
}
