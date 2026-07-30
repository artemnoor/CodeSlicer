import { Uri, WebviewPanel, ViewColumn, window, env } from "vscode";

const CODESLICER_ARCHIVE = "https://github.com/artemnoor/CodeSlicer/archive/refs/heads/main.zip";
const GRAPHIFY_ARCHIVE = "https://github.com/Graphify-Labs/graphify/archive/refs/heads/v8.zip";

type Language = "ru" | "en";

const copy = {
  ru: {
    title: "Загрузить инструменты", eyebrow: "НАЧАЛО РАБОТЫ", heading: "Установите инструменты в удобном порядке",
    intro: "Сначала скачайте CodeSlicer. Затем, если нужна отдельная архитектурная карта, скачайте Graphify. Ничего не устанавливается и не запускается без нажатия кнопки.",
    codeslicer: "1. CodeSlicer", codeText: "Основной локальный анализатор: Git diff, риск, доказательства и рекомендации тестов.",
    downloadCode: "Скачать CodeSlicer", configure: "Уже скачали? Указать CodeSlicer", codeNote: "Откроется официальный ZIP-архив GitHub. После распаковки создайте .venv и установите пакет по инструкции из README.",
    graphify: "2. Graphify — по желанию", graphText: "Отдельный инструмент для обзорной карты архитектуры и сообществ. Он не меняет risk и evidence CodeSlicer.",
    downloadGraph: "Скачать Graphify", graphNote: "Откроется официальный ZIP-архив Graphify. Подключите готовый graph.json в карточке Graphify в боковой панели.",
    safety: "CodeSlicer и Graphify независимы. Эта страница только открывает официальные страницы скачивания — никаких команд, токенов и файлов рабочего проекта она не трогает."
  },
  en: {
    title: "Download tools", eyebrow: "GET STARTED", heading: "Install the tools in a clear order",
    intro: "Download CodeSlicer first. Then, if you want a separate architecture map, download Graphify. Nothing is installed or run until you press a button.",
    codeslicer: "1. CodeSlicer", codeText: "The local analyzer for Git diffs, risk, evidence, and test recommendations.",
    downloadCode: "Download CodeSlicer", configure: "Already downloaded? Choose CodeSlicer", codeNote: "This opens the official GitHub ZIP archive. After extracting it, create a .venv and install the package using its README.",
    graphify: "2. Graphify — optional", graphText: "A separate tool for an architecture map and communities. It never changes CodeSlicer risk or evidence.",
    downloadGraph: "Download Graphify", graphNote: "This opens the official Graphify ZIP archive. Connect a finished graph.json from the Graphify card in the sidebar.",
    safety: "CodeSlicer and Graphify are independent. This page only opens their official download pages — it never runs commands, reads tokens, or touches workspace files."
  }
} as const;

export function renderInstallGuide(language: Language): string {
  const t = copy[language];
  return `<!DOCTYPE html><html lang="${language}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>${t.title}</title><style>
  :root{color-scheme:dark;--green:#50ed7b;--ink:#0b100c;--line:#2a4030;--text:#f0f6f1;--muted:#a8b5ab}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 83% 0,#174d2b 0,transparent 31%),var(--ink);color:var(--text);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:860px;margin:0 auto;padding:44px 28px}.eyebrow{margin:0;color:var(--green);font:700 11px/1 ui-monospace,Consolas,monospace;letter-spacing:.12em}.heading{max-width:620px;margin:10px 0 8px;font-size:32px;letter-spacing:-.04em;line-height:1.07}.intro{max-width:650px;margin:0;color:var(--muted)}.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:28px}.card{display:grid;align-content:start;gap:13px;min-height:310px;padding:21px;border:1px solid var(--line);border-radius:15px;background:linear-gradient(145deg,rgba(30,45,34,.96),rgba(16,24,18,.96));box-shadow:0 18px 52px rgba(0,0,0,.25)}.card.optional{background:linear-gradient(145deg,rgba(30,31,42,.96),rgba(16,18,22,.96))}.number{display:grid;place-items:center;width:34px;height:34px;border-radius:10px;background:rgba(80,237,123,.14);color:var(--green);font:700 13px ui-monospace,Consolas,monospace}.card.optional .number{background:rgba(194,167,255,.15);color:#c2a7ff}.card h2{margin:3px 0 0;font-size:20px;letter-spacing:-.02em}.card p{margin:0;color:var(--muted)}.note{margin-top:auto!important;font-size:12px}.button{display:inline-flex;align-items:center;justify-content:center;min-height:40px;padding:9px 12px;border:1px solid #53c971;border-radius:9px;background:#42db6c;color:#07100a;font-weight:750;cursor:pointer}.button:hover{background:#66f38c}.button.secondary{border-color:var(--line);background:transparent;color:var(--text)}.button.secondary:hover{border-color:#6b9b75;background:rgba(255,255,255,.04)}.safety{margin-top:18px;padding:13px 15px;border-left:3px solid var(--green);border-radius:0 10px 10px 0;background:rgba(80,237,123,.08);color:#cfddd1;font-size:13px}@media(max-width:620px){main{padding:28px 16px}.heading{font-size:27px}.cards{grid-template-columns:1fr}.card{min-height:0}}
  </style></head><body><main><p class="eyebrow">${t.eyebrow}</p><h1 class="heading">${t.heading}</h1><p class="intro">${t.intro}</p><section class="cards"><article class="card"><span class="number">01</span><h2>${t.codeslicer}</h2><p>${t.codeText}</p><button class="button" type="button" data-action="downloadCodeSlicer">${t.downloadCode}</button><button class="button secondary" type="button" data-action="configureCodeSlicer">${t.configure}</button><p class="note">${t.codeNote}</p></article><article class="card optional"><span class="number">02</span><h2>${t.graphify}</h2><p>${t.graphText}</p><button class="button" type="button" data-action="downloadGraphify">${t.downloadGraph}</button><p class="note">${t.graphNote}</p></article></section><p class="safety">${t.safety}</p></main><script>const vscode=acquireVsCodeApi();document.addEventListener("click",event=>{const button=event.target.closest("button[data-action]");if(button)vscode.postMessage({type:"action",action:button.dataset.action})});</script></body></html>`;
}

export function showInstallGuide(language: Language, configure: () => Promise<void>): WebviewPanel {
  const panel = window.createWebviewPanel("codeslicer.downloadTools", copy[language].title, ViewColumn.Active, { enableScripts: true });
  panel.webview.html = renderInstallGuide(language);
  panel.webview.onDidReceiveMessage(async (message: { type?: string; action?: string }) => {
    if (message.type !== "action") return;
    if (message.action === "downloadCodeSlicer") await env.openExternal(Uri.parse(CODESLICER_ARCHIVE));
    if (message.action === "downloadGraphify") await env.openExternal(Uri.parse(GRAPHIFY_ARCHIVE));
    if (message.action === "configureCodeSlicer") await configure();
  });
  return panel;
}
