'use strict';

// LSP is an explicit local process: data-adapter-action="configure-lsp" is
// rendered only when the backend exposes the configure/probe capability.

/* One local-first SPA. Dynamic values are rendered with textContent/createElement;
 * the only SVG markup is created through the SVG DOM API. */
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
const listen = (selector, event, handler) => { const node = $(selector); if (node) node.addEventListener(event, handler); };
const SVG_NS = 'http://www.w3.org/2000/svg';
let graphRenderSequence = 0;
const state = {
  ready: false, project: '', hasAnalysis: false, analysis: null, graph: null, overview: null,
  inventory: null, adapters: [], tools: [], review: null, projection: null, inspect: null, investigate: null,
  selectedEntity: '', selectedFile: '', reviewFilter: 'all', showMore: false, mapLevel: 'overview',
  mapKind: '', mapWorkspace: 'impact', mapSource: '', lastTest: null, analyzedAt: null, modalOpener: null, route: 'review', pending: new Set(),
  apiCompatibility: null, toolRuntimeError: null,
};

// Review is the daily product entry point. The map and Graphify remain the
// deliberate next levels when a developer needs to investigate evidence.
const routeAliases = { architecture: 'map', 'code-map': 'map', overview: 'review', inspect: 'review', investigate: 'map', automation: 'review', settings: 'review', ci: 'review', 'tool-graphify': 'graphify' };
const routeNames = { review: 'Проверка изменений', map: 'Карта проекта', sources: 'Локальные источники', graphify: 'Graphify' };
const unwrap = (response) => response?.report?.result || response?.result || response?.report || response || {};
const unique = (items) => [...new Set((items || []).filter(Boolean).map(String))];
const textOf = (value, fallback = '—') => value === null || value === undefined || value === '' ? fallback : String(value);
const describe = (value) => {
  if (value === null || value === undefined || value === '') return 'Нет подробного объяснения.';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.map((item) => describe(item)).join(' · ') || 'Нет данных.';
  if (typeof value === 'object') {
    for (const key of ['claim', 'reason', 'description', 'summary', 'heuristic', 'message']) if (value[key]) return describe(value[key]);
    if (Array.isArray(value.evidence_locations) && value.evidence_locations.length) return `Evidence: ${value.evidence_locations.map((item) => `${item.file || item.path || 'файл'}${item.line ? `:${item.line}` : ''}`).join(', ')}`;
    return 'Данные есть, но текстового объяснения нет.';
  }
  return String(value);
};
const riskLevel = (risk) => String(risk?.level || 'UNKNOWN').toUpperCase();
const statusLabel = (value) => ({ fresh: 'Актуален', ready: 'Готов', stale: 'Устарел', missing: 'Нет графа', incomplete: 'Неполный', unsupported: 'Ограничен', error: 'Ошибка', unknown: 'Неизвестно', running: 'Анализ идёт' }[String(value || '').toLowerCase()] || textOf(value, 'Неизвестно'));
const languageFor = (path) => ({ py: 'Python', js: 'JavaScript', jsx: 'JavaScript', ts: 'TypeScript', tsx: 'TypeScript', go: 'Go', java: 'Java', cs: 'C#' }[(String(path).split('.').pop() || '').toLowerCase()] || 'Неанализируемый язык');
const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

function el(tag, className, label) { const node = document.createElement(tag); if (className) node.className = className; if (label !== undefined) node.textContent = label; return node; }
function attr(node, values) { Object.entries(values || {}).forEach(([key, value]) => { if (value !== undefined && value !== null) node.setAttribute(key, String(value)); }); return node; }
function button(label, className = 'button secondary', values = {}) { return attr(el('button', className, label), { type: 'button', ...values }); }
function clear(node) { if (node) node.replaceChildren(); return node; }
function append(parent, ...children) { children.filter(Boolean).forEach((child) => parent.append(child)); return parent; }
function tag(label, className = '') { return el('span', `tag ${className}`.trim(), label); }
function cardTitle(eyebrow, title, detail) { const wrap = el('div', 'card-heading'); if (eyebrow) append(wrap, el('span', 'eyebrow', eyebrow)); append(wrap, el('h2', '', title)); if (detail) append(wrap, el('p', 'muted', detail)); return wrap; }
function stateCard(title, detail, kind = '') { const node = el('div', `state-card ${kind}`.trim()); append(node, el('strong', '', title), detail ? el('p', '', detail) : null); return node; }
function showState(message, kind = '') { const node = $('#globalState'); if (!node) return; node.textContent = message; node.className = `state-card ${kind}`.trim(); }
function setText(selector, value) { const node = $(selector); if (node) node.textContent = textOf(value); }
function isHighRisk(review = state.review) { return ['HIGH', 'CRITICAL'].includes(riskLevel(review?.risk)); }
function dataPayload(body) { const payload = unwrap(body); return payload && typeof payload === 'object' ? payload : {}; }

function normalizeRoute(value) {
  const raw = String(value || '').replace(/^#/, '').split('?')[0] || 'review';
  if (raw === 'graphify') return 'graphify';
  if (/^tool-[a-z0-9_-]+$/i.test(raw)) return raw === 'tool-graphify' ? 'graphify' : 'map';
  return routeAliases[raw] || (routeNames[raw] ? raw : 'review');
}
function routeQuery() { const hash = location.hash.slice(1); const index = hash.indexOf('?'); return new URLSearchParams(index >= 0 ? hash.slice(index + 1) : ''); }
function navigate(route, params = {}) {
  const canonical = normalizeRoute(route);
  const query = new URLSearchParams(params).toString();
  const hash = `#${canonical}${query ? `?${query}` : ''}`;
  if (location.hash !== hash) location.hash = hash; else renderRoute();
}
function showOnboarding(visible) { $('#onboarding').hidden = !visible; $('#routeViews').hidden = visible; }
function renderRoute() {
  state.route = normalizeRoute(location.hash);
  const routeView = state.route;
  $$('.route-view').forEach((view) => view.classList.toggle('active', view.dataset.routeView === routeView));
  $$('[data-route]').forEach((link) => link.classList.toggle('active', normalizeRoute(link.dataset.route) === state.route));
  if (!state.ready || !state.hasAnalysis) { showOnboarding(true); return; }
  showOnboarding(false);
  if (state.route === 'review') loadReview();
  if (state.route === 'map') loadProjection();
  if (state.route === 'sources') loadSources();
  if (state.route === 'graphify') loadGraphify();
}

function updateStatus() {
  const overview = state.overview || {};
  const freshness = overview.freshness || state.review?.graph_freshness || {};
  const coverage = overview.coverage || {};
  setText('#statusProject', `Проект: ${state.project || '—'}`);
  setText('#headerProjectPath', state.project || '—');
  setText('#statusFreshness', `Граф: ${statusLabel(freshness.status)}`);
  const languages = coverage.languages || [];
  setText('#statusCoverage', `Покрытие: ${languages.length ? `${languages.filter((item) => item.status === 'supported').length}/${languages.length} языков` : statusLabel(coverage.status)}`);
  setText('#statusAdapters', `Дополнения: ${state.adapters.filter((item) => item.enabled).length}`);
}
function renderWarnings(target, warnings) { clear(target); unique(warnings).forEach((warning) => append(target, stateCard('Ограничение', warning, 'warning-state'))); }

function normalizeChangedFiles(review) {
  const files = review?.changed?.files || review?.changed_files || [];
  return files.map((item) => typeof item === 'string' ? { path: item, additions: 0, deletions: 0, lines: [] } : { path: item.path || item.file || 'Неизвестный файл', additions: Number(item.additions || item.added || 0), deletions: Number(item.deletions || item.deleted || 0), lines: item.lines || [] });
}
function normalizeTests(review) { return review?.test_recommendations || review?.tests || review?.review_projection?.tests || []; }
function normalizeImpacts(review) { return review?.top_impacts || review?.review_projection?.candidates || []; }

async function loadOverview(force = false) {
  if (!state.project || (!force && state.overview)) { if (state.route === 'overview') renderOverview(); return; }
  const target = $('#overviewContent'); if (target) { clear(target); target.append(stateCard('Загружаю обзор проекта…', 'Данные берутся из local API.', 'loading')); }
  try {
    const results = await Promise.allSettled([ImpactApi.overview(), ImpactApi.state(), ImpactApi.progress(), ImpactApi.inventory(), ImpactApi.adapters()]);
    const [overview, current, progress, inventory, adapters] = results;
    if (overview.status === 'rejected') throw overview.reason;
    state.overview = overview.value || {}; state.analysis = current.status === 'fulfilled' ? current.value.analysis : state.analysis; state.analyzedAt = current.status === 'fulfilled' ? current.value.analyzed_at : state.analyzedAt;
    state.inventory = inventory.status === 'fulfilled' ? inventory.value.inventory || {} : null;
    state.adapters = adapters.status === 'fulfilled' ? adapters.value.adapters || [] : state.adapters;
    state.progress = progress.status === 'fulfilled' ? progress.value.progress : null;
    updateStatus(); renderOverview();
    if (!state.projection) loadProjection(true);
  } catch (error) { if (target) { clear(target); target.append(stateCard('Не удалось загрузить обзор', error.message, 'error-state')); } showState(`Ошибка local API: ${error.message}`, 'error-state'); }
}
function signalList() {
  const result = []; const overview = state.overview || {}; const freshness = overview.freshness || {};
  if (freshness.status === 'stale') result.push(['Граф устарел', 'Исходные файлы новее сохранённого графа.', 'warning']);
  if (['unsupported', 'incomplete'].includes(overview.coverage?.status)) result.push(['Неполное покрытие', 'Часть файлов или языков не подтверждена текущим анализом.', 'warning']);
  state.adapters.filter((item) => item.enabled && ['stale', 'outdated'].includes(String(item.freshness?.status))).forEach((item) => result.push(['Артефакт дополнения устарел', textOf(item.id), 'warning']));
  (overview.diagnostics || []).slice(0, 4).forEach((item) => result.push(['Ошибка анализа', describe(item), 'danger']));
  if (isHighRisk()) result.push(['Высокий риск в текущей проверке', 'Review той же рабочей копии сообщает высокий риск.', 'danger']);
  if (state.lastTest && !state.lastTest.passed) result.push(['Тест не прошёл', 'Это результат запуска теста, а не утверждение об ошибке CodeSlicer.', 'danger']);
  return result;
}
function renderOverview() {
  const target = $('#overviewContent'); if (!target || !state.overview) return; clear(target);
  const overview = state.overview; const graph = overview.graph || {}; const coverage = overview.coverage || {}; const signals = signalList();
  const grid = el('div', 'overview-grid');
  const project = el('article', 'panel project-card'); append(project, cardTitle('О ПРОЕКТЕ', overview.project?.name || 'Локальный проект', 'Абсолютный путь выбран явно пользователем.')); append(project, el('code', 'project-path', overview.project?.path || state.project));
  const status = el('div', 'project-status'); append(status, tag(statusLabel(overview.status), overview.status === 'ready' ? 'good' : 'warn'), el('span', 'muted', `Граф: ${statusLabel(overview.freshness?.status)}`)); project.append(status);
  const meta = el('div', 'project-meta'); const analyzedAt = state.analyzedAt || state.analysis?.analyzed_at; append(meta, metric('Последний анализ', analyzedAt ? new Date(analyzedAt * 1000).toLocaleString('ru-RU') : 'Не записан'), metric('Узлы', graph.nodes ?? '—'), metric('Связи', graph.edges ?? '—')); project.append(meta); grid.append(project);
  const attention = el('article', 'panel attention-card'); append(attention, cardTitle('СИГНАЛЫ', 'Что требует внимания', `${signals.length} активных сигналов`)); if (!signals.length) attention.append(stateCard('Сигналов нет', 'Проверка не нашла дополнительных ограничений.', 'empty-state')); signals.slice(0, 6).forEach(([title, detail, kind]) => { const row = el('div', `signal-row ${kind}`); append(row, el('span', 'status-key', kind === 'danger' ? '!' : '?'), el('div', '', '')); row.lastChild.append(el('strong', '', title), el('p', '', detail)); attention.append(row); }); if (isHighRisk()) attention.append(button('Открыть проверку', 'link-button', { 'data-route': 'review' })); grid.append(attention);
  const stats = el('article', 'panel stats-card'); append(stats, cardTitle('СОСТОЯНИЕ', 'Факты анализа', 'Только данные выбранного проекта.')); const statsGrid = el('div', 'stats-grid'); append(statsGrid, metric('Файлы', state.inventory?.files?.length ?? '—'), metric('Языки', coverage.languages?.length ?? '—'), metric('Узлы', graph.nodes ?? '—'), metric('Исключено', overview.excluded?.count ?? 0)); stats.append(statsGrid); const languageList = el('div', 'language-list'); (coverage.languages || []).slice(0, 8).forEach((item) => { const row = el('div', 'coverage-row'); append(row, el('span', '', textOf(item.language)), el('span', item.status === 'supported' ? 'good-text' : 'warn-text', `${item.files || 0} файлов · ${statusLabel(item.status)}`)); languageList.append(row); }); if (!languageList.children.length) languageList.append(el('p', 'muted', 'Покрытие пока не отдано API.')); stats.append(languageList); grid.append(stats);
  const quick = el('article', 'panel quick-card'); append(quick, cardTitle('БЫСТРЫЕ ДЕЙСТВИЯ', 'Что сделать сейчас', 'Действия выполняются только после клика.')); [['review', 'Проверить изменения', 'GET/POST review'], ['map', 'Открыть карту кода', 'Bounded projection'], ['inspect', 'Найти символ', 'Inspect по сущности'], ['analyze', 'Обновить анализ', 'Analyze + progress polling']].forEach(([route, title, detail]) => { const item = button('', 'quick-action', route === 'analyze' ? { 'data-action': 'analyze' } : { 'data-route': route, 'aria-label': title }); append(item, el('strong', '', title), el('small', 'muted', detail), el('span', 'arrow', '→')); quick.append(item); }); grid.append(quick);
  const map = el('article', 'panel map-preview'); append(map, cardTitle('КАРТА ПРОЕКТА', 'Компактная карта модулей', 'Канонический граф, bounded до небольшого числа узлов.')); const preview = el('div', 'mini-graph'); const previewNodes = state.projection?.nodes || []; if (previewNodes.length) renderMiniGraph(preview, state.projection); else preview.append(el('p', 'muted', overview.graph?.available ? 'Карта будет загружена по запросу.' : 'Актуального графа нет.')); map.append(preview, button('Открыть карту', 'link-button', { 'data-route': 'map' })); grid.append(map);
  const areas = el('article', 'panel areas-card'); append(areas, cardTitle('ОБЛАСТИ', 'Обнаруженные области проекта')); let areaValues = state.inventory?.directories || state.inventory?.areas || state.inventory?.top_level_directories || []; if (!Array.isArray(areaValues) || !areaValues.length) { const derived = new Set((state.inventory?.files || []).map((file) => String(file).replace(/\\/g, '/').split('/')[0]).filter((value) => value && value !== '.')); areaValues = [...derived]; } if (Array.isArray(areaValues) && areaValues.length) areaValues.slice(0, 12).forEach((item) => areas.append(tag(typeof item === 'string' ? item : item.path || item.name, 'neutral'))); else areas.append(el('p', 'muted', 'Backend не вернул перечень областей.')); grid.append(areas);
  target.append(grid);
}
function metric(label, value) { const node = el('div', 'metric'); append(node, el('strong', '', textOf(value)), el('span', 'muted', label)); return node; }

function renderReview() {
  const target = $('#reviewContent'); if (!target || !state.review) return; clear(target); const review = state.review; const files = normalizeChangedFiles(review); const impacts = normalizeImpacts(review); const tests = normalizeTests(review); const filteredFiles = files.filter((item) => state.reviewFilter === 'all' || (state.reviewFilter === 'api' ? /api|route|openapi/i.test(item.path) : state.reviewFilter === 'tests' ? /test|spec/i.test(item.path) : state.reviewFilter === 'high' ? isHighRisk(review) : true));
  const layout = el('div', 'review-grid');
  const left = el('aside', 'panel file-list'); append(left, cardTitle('CHANGES', 'Изменённые файлы', files.length ? `${files.length} файлов` : 'Пустой diff')); const filters = el('div', 'filter-row'); [['all', 'Все'], ['api', 'API'], ['tests', 'Тесты'], ['high', 'Высокий риск']].forEach(([value, label]) => { const f = button(label, `filter-button ${state.reviewFilter === value ? 'active' : ''}`, { 'data-review-filter': value }); filters.append(f); }); left.append(filters); if (!files.length) left.append(stateCard('Изменений относительно выбранной ветки не найдено', 'Проверьте base branch или передайте diff явно.', 'empty-state')); filteredFiles.forEach((file) => { const row = button('', `file-row ${state.selectedFile === file.path ? 'selected' : ''}`, { 'data-review-file': file.path, 'aria-label': file.path }); append(row, el('span', 'status-key', isHighRisk(review) ? '!' : '·'), el('span', '', '')); row.lastChild.append(el('code', '', file.path), el('small', 'muted', `${file.additions} добавлено · ${file.deletions} удалено · ${languageFor(file.path)}`)); left.append(row); }); layout.append(left);
  const center = el('div', 'review-center'); const risk = review.risk || {}; const riskCard = el('article', 'panel impact-summary'); append(riskCard, cardTitle('РИСК И ВЛИЯНИЕ', `${riskLevel(risk) === 'UNKNOWN' ? 'Риск не определён' : `${riskLevel(risk)} · ${riskLevel(risk) === 'HIGH' || riskLevel(risk) === 'CRITICAL' ? 'Высокое влияние' : 'Ограниченное влияние'}`}`, `Оценка относится к текущему Review, не к запуску теста.`)); const banner = el('div', `risk-banner ${riskLevel(risk).toLowerCase()}`); append(banner, el('span', 'status-key', riskLevel(risk) === 'HIGH' || riskLevel(risk) === 'CRITICAL' ? '!' : '?'), el('span', '', describe(risk.reason || risk.reasons || 'Backend не передал текст причины.'))); riskCard.append(banner); const stats = el('div', 'impact-stats'); append(stats, metric('Изменённые файлы', files.length), metric('Главные затронутые сущности', impacts.length), metric('Уверенность', textOf(risk.confidence, '—'))); riskCard.append(stats); center.append(riskCard);
  const impactSection = attr(el('section', 'impact-section'), { id: 'reviewItems' }); append(impactSection, cardTitle('РЕЗУЛЬТАТ', state.selectedFile ? `Влияние для ${state.selectedFile}` : 'Главные затронутые сущности', 'Максимум пять карточек; остальные доступны по запросу.')); const visible = (state.showMore ? impacts : impacts.slice(0, 5)).filter((item) => !state.selectedFile || !item.file || item.file === state.selectedFile); if (!visible.length) impactSection.append(stateCard(state.selectedFile ? 'Для выбранного файла нет отдельного impact item' : 'Затронутых сущностей не найдено', 'Это не означает, что код исправен; означает, что backend не подтвердил связь.', 'empty-state')); visible.forEach((item) => impactSection.append(impactCard(item))); if (impacts.length > 5) impactSection.append(button(state.showMore ? 'Скрыть дополнительные' : `Показать ещё (${impacts.length - 5})`, 'link-button', { 'data-action': 'toggle-more' })); center.append(impactSection);
  const evidence = el('article', 'panel evidence-card'); append(evidence, cardTitle('EVIDENCE', 'Подтверждение и ограничения')); (review.chains || []).slice(0, 5).forEach((chain) => { const row = el('div', 'evidence-row'); append(row, el('span', 'status-key', chain.status === 'confirmed' ? '✓' : '?'), el('div', '', '')); row.lastChild.append(el('strong', '', `${chain.confidence || '—'} · ${chain.summary || chain.id || 'Цепочка'}`), el('small', 'muted', `Статус: ${textOf(chain.status)} · Источники: ${unique(chain.evidence_ids || []).join(', ') || 'не указаны'}`)); evidence.append(row); }); (review.warnings || []).slice(0, 6).forEach((warning) => evidence.append(el('p', 'warning-text', warning))); if (!review.chains?.length && !review.warnings?.length) evidence.append(el('p', 'muted', 'Backend не вернул цепочки или предупреждения.')); center.append(evidence); layout.append(center);
  const right = el('aside', 'panel test-panel'); append(right, cardTitle('LOCAL TESTS', 'Что проверить', 'Запуск только через /api/review/run-test после подтверждения.')); if (!tests.length) right.append(stateCard('Targeted tests не предложены', review.incomplete ? 'Рекомендации скрыты из-за неполного покрытия.' : 'Fallback suite не отдан backend.', 'empty-state')); tests.slice(0, 10).forEach((test) => right.append(testRow(test))); const runSelected = button('Запустить выбранные тесты', 'button primary', { 'data-action': 'run-selected-tests' }); runSelected.disabled = !tests.some((test) => test.file); right.append(runSelected); const fallback = review.fallback_suite || review.fallback_tests || review.review_projection?.fallback_suite; if (fallback) { right.append(el('h3', 'subheading', 'Fallback suite')); right.append(el('p', 'muted', describe(fallback))); } const result = el('div', 'test-result'); if (state.lastTest) renderTestResult(result, state.lastTest); right.append(result); layout.append(right); target.append(layout);
}
function impactCard(item) { const entity = item.entity_id || item.id || item.symbol || 'Неизвестная сущность'; const row = el('article', 'impact-card'); append(row, tag(textOf(item.kind, 'ENTITY'), 'entity-kind'), el('div', '', '')); row.lastChild.append(el('h3', '', textOf(item.label || item.symbol || entity)), el('p', 'muted', `${textOf(item.file, 'Файл не указан')}${item.line ? `:${item.line}` : ''} · ${textOf(item.impact_class || item.class, 'Ограниченный анализ')}`), el('small', 'muted', `Статус: ${textOf(item.confidence, 'неизвестен')} · ${describe(item.why_affected || item.why || item.reason)}`)); const actions = el('div', 'impact-actions'); append(actions, button('Почему затронуто', 'link-button', { 'data-impact-action': 'inspect', 'data-entity': entity, 'aria-label': 'Why affected?' }), button('Доказательства', 'link-button', { 'data-impact-action': 'evidence', 'data-entity': entity }), button('Исследовать связи', 'link-button', { 'data-impact-action': 'investigate', 'data-entity': entity, 'aria-label': 'Open chain' }), button('Открыть код', 'link-button', { 'data-impact-action': 'open-file', 'data-file': item.file || '', 'aria-label': 'Open file ↗' })); row.append(actions); return row; }
function testRow(test) { const file = test.file || ''; const row = el('label', 'test-row'); const check = el('input'); check.type = 'checkbox'; check.checked = true; check.dataset.testFile = file; const copy = el('span'); append(copy, el('strong', '', textOf(test.symbol || test.node || test.name, 'Рекомендованный тест')), el('small', 'muted', textOf(test.command, file || 'Команда будет определена backend при запуске')), el('small', 'muted', `Причина: ${describe(test.reason || test.heuristic || 'Связь с изменённой областью')}`)); append(row, check, copy); row.dataset.testFile = file; row.addEventListener('click', (event) => { if (event.target === check || event.target.closest('button')) return; }); row.addEventListener('dblclick', () => file && confirmTest(test)); return row; }
function renderTestResult(target, result) { clear(target); const ok = result.passed === true; const title = result.status === 'timeout' ? 'Тест превысил лимит времени' : ok ? 'Тест завершился успешно' : 'Тест не прошёл'; append(target, el('h3', '', title), el('p', 'muted', 'Это результат команды теста, а не утверждение, что CodeSlicer нашёл ошибку.')); if (result.command) target.append(el('code', 'command-output', Array.isArray(result.command) ? result.command.join(' ') : result.command)); target.append(el('p', 'muted', `Статус: ${textOf(result.status)} · exit code: ${textOf(result.exit_code, '—')}`)); if (result.stdout) target.append(el('pre', 'output', result.stdout)); if (result.stderr) target.append(el('pre', 'output error-output', result.stderr)); }

async function loadReview(force = false) { if (!state.project) return; const target = $('#reviewContent'); if (target && (force || !state.review)) { clear(target); target.append(stateCard('Сверяю изменения с каноническим графом…', 'Review выполняется локально.', 'loading')); } if (!force && state.review) { renderReview(); return; } state.pending.add('review'); try { const response = await ImpactApi.review({ project_path: state.project, refresh: 'auto', max_results: 10, run_tests: 'suggested', entity: state.selectedEntity || undefined }); state.review = dataPayload(response); renderWarnings($('#reviewWarnings'), [...(state.review.warnings || []), ...(state.review.coverage || []).filter((item) => item.status !== 'supported').map((item) => `${item.path || item.language}: ${statusLabel(item.status)}`)]); renderReview(); updateStatus(); } catch (error) { if (target) { clear(target); target.append(stateCard('Review недоступен', error.message, 'error-state')); } } finally { state.pending.delete('review'); } }

function renderMiniGraph(target, projection) { clear(target); const scene = createNetworkGraph(projection, { compact: true }); target.append(scene.svg); }
function svgEl(tagName, values, label) { const node = document.createElementNS(SVG_NS, tagName); attr(node, values); if (label !== undefined) node.textContent = label; return node; }
function truncate(value, length) { const text = String(value || ''); return text.length > length ? `${text.slice(0, length - 1)}…` : text; }

function isExternalGraphItem(item) {
  return Boolean(item?.overlay || item?.canonical === false || String(item?.evidence_source || item?.source || '').toLowerCase() !== 'codeslicer');
}

function graphOrder(nodes, edges, limit) {
  const degree = new Map(nodes.map((node) => [node.id, 0]));
  edges.forEach((edge) => {
    if (degree.has(edge.from)) degree.set(edge.from, degree.get(edge.from) + 1);
    if (degree.has(edge.to)) degree.set(edge.to, degree.get(edge.to) + 1);
  });
  const index = new Map(nodes.map((node, position) => [node.id, position]));
  const byImportance = (left, right) => (degree.get(right.id) - degree.get(left.id)) || (index.get(left.id) - index.get(right.id));
  const selected = nodes.find((node) => node.id === state.selectedEntity && degree.get(node.id) > 0);
  const hub = selected || [...nodes].sort(byImportance)[0];
  if (!hub) return { hub: null, nodes: [], degree };
  const neighbours = new Set();
  edges.forEach((edge) => {
    if (edge.from === hub.id) neighbours.add(edge.to);
    if (edge.to === hub.id) neighbours.add(edge.from);
  });
  const firstRing = nodes.filter((node) => neighbours.has(node.id) && node.id !== hub.id).sort(byImportance);
  const remaining = nodes.filter((node) => node.id !== hub.id && !neighbours.has(node.id)).sort(byImportance);
  return { hub, nodes: [hub, ...firstRing, ...remaining].slice(0, limit), degree };
}

function radialPositions(nodes, hub, compact) {
  const width = compact ? 720 : 1100;
  const height = compact ? 240 : 750;
  const center = { x: Math.round(width * 0.5), y: Math.round(height * 0.5) };
  const positions = new Map();
  if (!hub) return { width, height, positions };
  positions.set(hub.id, center);
  const r1Limit = compact ? 8 : 12;
  const r2Limit = compact ? 16 : 24;
  const r1 = nodes.slice(1, 1 + r1Limit);
  const r2 = nodes.slice(1 + r1Limit, 1 + r1Limit + r2Limit);
  const r3 = nodes.slice(1 + r1Limit + r2Limit);
  const putRing = (ring, radiusX, radiusY, offset = -Math.PI / 2) => ring.forEach((node, index) => {
    const angle = offset + (Math.PI * 2 * index / Math.max(ring.length, 1));
    positions.set(node.id, { x: Math.round(center.x + Math.cos(angle) * radiusX), y: Math.round(center.y + Math.sin(angle) * radiusY) });
  });
  putRing(r1, compact ? 128 : 200, compact ? 74 : 160);
  putRing(r2, compact ? 218 : 360, compact ? 94 : 280, -Math.PI / 2 + 0.2);
  putRing(r3, compact ? 300 : 480, compact ? 120 : 370, -Math.PI / 2 + 0.4);
  return { width, height, positions };
}

let activeGraphNavigator = null;

function createNetworkGraph(projection, { compact = false } = {}) {
  const allNodes = projection.nodes || [];
  const allEdges = projection.edges || [];
  const requestedLimit = compact ? 10 : Math.min(allNodes.length, 42);
  const ordered = graphOrder(allNodes, allEdges, requestedLimit);
  const visibleNodes = ordered.nodes;
  const visibleIds = new Set(visibleNodes.map((node) => node.id));
  const candidateEdges = allEdges.filter((edge) => visibleIds.has(edge.from) && visibleIds.has(edge.to));
  const hubEdges = candidateEdges.filter((edge) => edge.from === ordered.hub?.id || edge.to === ordered.hub?.id);
  const visibleEdges = candidateEdges.length ? candidateEdges : hubEdges;
  const { width, height, positions } = radialPositions(visibleNodes, ordered.hub, compact);
  const svg = svgEl('svg', { class: `projection-svg ${compact ? 'projection-svg-mini' : ''}`, viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': compact ? 'Компактная карта проекта' : 'Карта связей выбранного графа' });
  const filterId = `graph-glow-${++graphRenderSequence}`;
  const defs = svgEl('defs', {});
  const filter = svgEl('filter', { id: filterId, x: '-120%', y: '-120%', width: '340%', height: '340%' });
  filter.append(svgEl('feGaussianBlur', { stdDeviation: compact ? 5 : 7, result: 'blur' }), svgEl('feMerge', {}));
  filter.lastChild.append(svgEl('feMergeNode', { in: 'blur' }), svgEl('feMergeNode', { in: 'SourceGraphic' }));
  defs.append(filter); svg.append(defs, svgEl('title', {}, compact ? 'Компактная карта связей проекта' : 'Интерактивная карта связей проекта'));

  const nodeViews = [];
  const edgeViews = [];
  visibleEdges.forEach((edge) => {
    const from = positions.get(edge.from); const to = positions.get(edge.to);
    if (!from || !to) return;
    const external = isExternalGraphItem(edge);
    const line = svgEl('line', { x1: from.x, y1: from.y, x2: to.x, y2: to.y, class: `graph-edge ${external ? 'additional' : ''}`.trim(), 'data-edge-id': edge.id || `${edge.from}->${edge.to}` });
    edgeViews.push({ edge, line }); svg.append(line);
  });
  visibleNodes.forEach((node) => {
    const point = positions.get(node.id); if (!point) return;
    const external = isExternalGraphItem(node);
    const isHub = node.id === ordered.hub?.id;
    const group = svgEl('g', { class: `projection-node-link network-node${isHub ? ' is-hub' : ''}${external ? ' is-external' : ''}`, tabindex: '0', role: 'button', 'aria-label': `${node.name || node.id}. ${isHub ? 'Центральный узел. ' : ''}Открыть сведения`, 'data-projection-entity': node.id });
    group.append(svgEl('title', {}, `${node.name || node.id} · ${node.kind || 'ENTITY'}`));
    if (isHub) group.append(svgEl('circle', { cx: point.x, cy: point.y, r: compact ? 24 : 33, class: 'graph-halo', filter: `url(#${filterId})` }));
    group.append(svgEl('circle', { cx: point.x, cy: point.y, r: isHub ? (compact ? 10 : 13) : (compact ? 4 : 6), class: external ? 'node-additional' : 'node-canonical' }));
    group.append(svgEl('text', { x: point.x, y: point.y - (isHub ? (compact ? 18 : 24) : 11), class: `graph-label graph-node-caption${isHub ? ' is-visible' : ''}` }, truncate(node.name || node.id, compact ? 18 : 25)));
    group.addEventListener('click', () => { if (!svg.dataset.dragging) selectProjectionNode(node); });
    group.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectProjectionNode(node); } });
    group.addEventListener('pointerenter', () => focusNetworkNode(node.id));
    group.addEventListener('focus', () => focusNetworkNode(node.id));
    group.addEventListener('pointerleave', () => focusNetworkNode(''));
    group.addEventListener('blur', () => focusNetworkNode(''));
    nodeViews.push({ node, group }); svg.append(group);
  });
  function focusNetworkNode(nodeId) {
    const related = new Set(nodeId ? [nodeId] : []);
    if (nodeId) visibleEdges.forEach((edge) => { if (edge.from === nodeId) related.add(edge.to); if (edge.to === nodeId) related.add(edge.from); });
    nodeViews.forEach(({ node, group }) => { group.classList.toggle('is-muted', Boolean(nodeId) && !related.has(node.id)); group.classList.toggle('is-focused', node.id === nodeId); });
    edgeViews.forEach(({ edge, line }) => { const connected = edge.from === nodeId || edge.to === nodeId; line.classList.toggle('is-muted', Boolean(nodeId) && !connected); line.classList.toggle('is-active', Boolean(nodeId) && connected); });
  }
  return { svg, visibleNodes, visibleEdges, totalNodes: allNodes.length, width, height };
}

function attachGraphNavigator(scene) {
  const svg = scene?.svg;
  if (!svg) return null;
  const initial = { x: 0, y: 0, width: scene.width, height: scene.height };
  const view = { ...initial };
  const minScale = 0.42;
  const maxScale = 3;
  let pointer = null;
  let moved = false;
  const zoomLevel = () => Math.round((initial.width / view.width) * 100);
  const redraw = () => {
    svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.width} ${view.height}`);
    setText('#graphZoomLevel', `${zoomLevel()}%`);
  };
  const clamp = () => {
    const padX = view.width * 0.32;
    const padY = view.height * 0.32;
    view.x = Math.max(-padX, Math.min(initial.width - view.width + padX, view.x));
    view.y = Math.max(-padY, Math.min(initial.height - view.height + padY, view.y));
  };
  const zoom = (factor, originX = initial.width / 2, originY = initial.height / 2) => {
    const nextWidth = Math.max(initial.width / maxScale, Math.min(initial.width / minScale, view.width / factor));
    const actual = nextWidth / view.width;
    const nextHeight = view.height * actual;
    view.x = originX - (originX - view.x) * actual;
    view.y = originY - (originY - view.y) * actual;
    view.width = nextWidth;
    view.height = nextHeight;
    clamp(); redraw();
  };
  const reset = () => { Object.assign(view, initial); redraw(); };
  const pan = (deltaX, deltaY) => {
    view.x -= deltaX * view.width / Math.max(1, svg.getBoundingClientRect().width);
    view.y -= deltaY * view.height / Math.max(1, svg.getBoundingClientRect().height);
    clamp(); redraw();
  };
  svg.setAttribute('tabindex', '0');
  svg.setAttribute('aria-label', 'Интерактивная карта связей. Тяните пустую область, используйте колесо для масштаба, клавиши плюс, минус, ноль и стрелки для управления.');
  svg.addEventListener('wheel', (event) => {
    event.preventDefault();
    const rect = svg.getBoundingClientRect();
    const originX = view.x + (event.clientX - rect.left) / Math.max(1, rect.width) * view.width;
    const originY = view.y + (event.clientY - rect.top) / Math.max(1, rect.height) * view.height;
    zoom(event.deltaY < 0 ? 1.16 : 1 / 1.16, originX, originY);
  }, { passive: false });
  svg.addEventListener('pointerdown', (event) => {
    if (event.target !== svg) return;
    pointer = { id: event.pointerId, x: event.clientX, y: event.clientY };
    moved = false;
    svg.setPointerCapture?.(event.pointerId);
    svg.classList.add('is-panning');
  });
  svg.addEventListener('pointermove', (event) => {
    if (!pointer || pointer.id !== event.pointerId) return;
    const dx = event.clientX - pointer.x; const dy = event.clientY - pointer.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
    pan(dx, dy); pointer.x = event.clientX; pointer.y = event.clientY;
  });
  const finishPan = (event) => {
    if (!pointer || (event && pointer.id !== event.pointerId)) return;
    svg.dataset.dragging = moved ? 'true' : '';
    window.setTimeout(() => { delete svg.dataset.dragging; }, 0);
    pointer = null; svg.classList.remove('is-panning');
  };
  svg.addEventListener('pointerup', finishPan);
  svg.addEventListener('pointercancel', finishPan);
  svg.addEventListener('keydown', (event) => {
    const key = event.key;
    if (key === '+' || key === '=') { event.preventDefault(); zoom(1.16); }
    else if (key === '-') { event.preventDefault(); zoom(1 / 1.16); }
    else if (key === '0') { event.preventDefault(); reset(); }
    else if (key === 'ArrowLeft') { event.preventDefault(); pan(48, 0); }
    else if (key === 'ArrowRight') { event.preventDefault(); pan(-48, 0); }
    else if (key === 'ArrowUp') { event.preventDefault(); pan(0, 48); }
    else if (key === 'ArrowDown') { event.preventDefault(); pan(0, -48); }
  });
  redraw();
  return { zoomIn: () => zoom(1.16), zoomOut: () => zoom(1 / 1.16), reset };
}

async function loadProjection(force = false) {
  if (!state.project || state.route !== 'map' && !force) return;
  const target = $('#graphProjectionContent'); const status = $('#graphProjectionStatus') || $('#graphProjectionState');
  if (target && (force || !state.projection)) { clear(target); target.append(stateCard('Загружаю выбранный граф…', 'Каждый источник остаётся отдельным; показываются только явные bridge-связи.', 'loading')); }
  try {
    let response;
    if (state.mapWorkspace === 'impact') {
      const filters = { node_kinds: state.mapKind ? [state.mapKind] : [], edge_kinds: [], evidence_sources: [], evidence_classes: [], relation_scopes: [], min_confidence: 0 };
      response = await ImpactApi.graphProjection({ project_path: state.project, level: state.mapLevel, query: $('#graphProjectionQuery')?.value.trim() || '', filters, max_nodes: 120, max_edges: 200 });
      response.workspace = { id: 'impact', title: 'Влияние изменений', ranking_owner: true };
    } else {
      response = await ImpactApi.graphWorkspace({ project_path: state.project, workspace: state.mapWorkspace, source_id: state.mapSource || undefined, max_nodes: 120, max_edges: 200 });
    }
    state.projection = response;
    renderWorkspaceControls(response.workspaces || [], response.selected_source);
    const workspaceName = response.workspace?.title || 'CodeSlicer';
    const bridgeText = response.total_bridges ? ` · ${response.total_bridges} bridge-связей` : '';
    if (status) status.textContent = `${workspaceName} · ${statusLabel(response.status)} · ${response.nodes?.length || 0} узлов · ${response.edges?.length || 0} связей${bridgeText}${response.truncated ? ' · результат ограничен' : ''}`;
    renderMapMetrics(response, workspaceName);
    renderProjection(response); updateEntitySuggestions(response.nodes || []);
  } catch (error) { if (target) { clear(target); target.append(stateCard('Карта недоступна', error.message, 'error-state')); } if (status) status.textContent = 'Выбранный граф не отдан API.'; renderMapMetrics(null); }
}

function renderMapMetrics(projection, workspaceName = '—') {
  const nodeTotal = Number(projection?.total_nodes ?? projection?.nodes?.length ?? 0);
  const edgeTotal = Number(projection?.total_edges ?? projection?.edges?.length ?? 0);
  const graphify = state.mapWorkspace !== 'impact';
  setText('#mapWorkspaceMetric', projection ? workspaceName : '—');
  setText('#mapNodeMetric', projection ? String(nodeTotal) : '—');
  setText('#mapEdgeMetric', projection ? String(edgeTotal) : '—');
  setText('#mapMeterLabel', projection
    ? (graphify ? 'Фиолетовый — отдельная карта Graphify. Она не меняет результаты CodeSlicer.' : 'Зелёный — основной граф CodeSlicer для анализа зависимостей и влияния.')
    : 'Ожидаю данные выбранной карты.');
  $('#mapMeterPrimary')?.style.setProperty('width', graphify ? '0%' : projection ? '100%' : '0%');
  $('#mapMeterSecondary')?.style.setProperty('width', graphify && projection ? '100%' : '0%');
  $('#mapMeterLabel')?.parentElement?.classList.toggle('graphify', graphify && Boolean(projection));
}

function graphifyTool() { return state.tools.find((item) => item.id === 'graphify'); }
function graphifyAdapter() { return state.adapters.find((item) => item.id === 'graphify'); }

async function loadGraphify() {
  const target = $('#graphifyContent');
  if (!target || !state.project) return;
  clear(target);
  target.append(stateCard('Проверяю Graphify…', 'Проверяется только локальная конфигурация.', 'loading'));
  try {
    const [adapters, tools, viewerStatus] = await Promise.allSettled([
      ImpactApi.adapters(),
      state.apiCompatibility ? Promise.resolve({ tools: [] }) : ImpactApi.tools(),
      ImpactApi.graphifyViewerStatus(),
    ]);
    state.adapters = adapters.status === 'fulfilled' ? adapters.value.adapters || [] : state.adapters;
    state.tools = tools.status === 'fulfilled' ? tools.value.tools || [] : state.tools;
    const adapter = graphifyAdapter() || {};
    const tool = graphifyTool();
    const nativeViewer = viewerStatus.status === 'fulfilled' ? viewerStatus.value : {};
    clear(target);
    const panel = el('article', 'graphify-panel');
    // An adapter artifact can exist while its upstream HTML is missing or
    // stale. Only the viewer endpoint may declare the iframe displayable.
    const viewerReady = nativeViewer.status === 'ready';
    const artifactReady = viewerReady;
    const workspaceReady = Boolean(tool?.connected || tool?.repository?.cloned);
    append(panel,
      el('span', 'eyebrow', artifactReady ? 'ГОТОВО К ПРОСМОТРУ' : 'НЕ ПОДКЛЮЧЕНО'),
      el('h2', '', artifactReady ? 'Архитектурная карта Graphify готова' : 'Подключите Graphify по желанию'),
      el('p', '', artifactReady
        ? 'Graphify уже построил отдельную карту. Она расширяет обзор архитектуры, но не меняет рекомендации CodeSlicer.'
        : 'Graphify нужен только для широкой архитектурной карты. Базовая карта CodeSlicer продолжит работать без него.'),
    );
    const facts = el('div', 'graphify-facts');
    append(facts,
      metric('Статус', artifactReady ? 'Готов' : 'Не подключён'),
      metric('Workspace', workspaceReady ? 'Локально' : 'Не подключён'),
      metric('Влияние на CodeSlicer', 'Нет'),
    );
    panel.append(facts);
    const actions = el('div', 'graphify-actions');
    if (!workspaceReady) actions.append(button('Подключить Graphify', artifactReady ? 'button secondary' : 'button primary', { 'data-graphify-action': 'connect' }));
    panel.append(actions);
    panel.append(el('p', 'graphify-note', workspaceReady
      ? 'Graphify работает в отдельном локальном workspace. Его граф остаётся отдельным от графа CodeSlicer.'
      : 'Подключение требует подтверждения: будет создан локальный workspace Graphify. Исходный код вашего проекта наружу не отправляется.'));
    target.append(panel);
    if (viewerReady) {
      const viewer = el('section', 'native-graphify-viewer');
      append(
        viewer,
        el('span', 'eyebrow', 'ОРИГИНАЛЬНЫЙ VIEWER GRAPHIFY'),
        el('h2', '', 'Карта, отрисованная самим Graphify'),
        el('p', 'muted', 'Это отдельный HTML-рендерер Graphify. CodeSlicer не преобразует его в свою SVG-карту и не меняет его узлы, связи или комьюнити.')
      );
      const frame = el('iframe', 'graphify-native-frame');
      attr(frame, {
        src: '/api/adapters/graphify/viewer',
        title: 'Оригинальная визуализация Graphify',
        loading: 'lazy',
        sandbox: 'allow-scripts',
        referrerpolicy: 'no-referrer',
      });
      viewer.append(frame);
      target.append(viewer);
    } else if (nativeViewer.graph_available) {
      target.append(stateCard(
        nativeViewer.status === 'stale' ? 'Graphify-карта устарела' : 'Graphify viewer ещё не подготовлен',
        nativeViewer.status === 'stale'
          ? 'Граф изменился после последнего renderer. Обновите Graphify, чтобы открыть актуальную карту.'
          : 'Граф Graphify найден, но локальный HTML renderer ещё не создал безопасную автономную визуализацию.',
        'warning-state'
      ));
    }
  } catch (error) {
    clear(target);
    target.append(stateCard('Graphify сейчас недоступен', error.message, 'error-state'));
  }
}

async function handleGraphifyAction(action) {
  if (action.dataset.graphifyAction === 'open') {
    // Graphify is intentionally not projected through CodeSlicer's SVG map.
    // Its own upstream HTML viewer has different communities and interactions.
    navigate('graphify');
    await loadGraphify();
    return;
  }
  if (state.apiCompatibility) {
    showState(staleApiToolMessage(), 'error-state');
    return;
  }
  if (!window.confirm('Подключить Graphify? CodeSlicer создаст отдельный локальный workspace Graphify. Для клонирования upstream-репозитория Graphify будет использована сеть. Продолжить?')) return;
  action.disabled = true;
  const original = action.textContent;
  action.textContent = 'Подключаю…';
  try {
    await ImpactApi.toolConnect('graphify', { project_path: state.project, confirmed: true });
    await loadTools();
    showState('Graphify подключён локально. Постройте или откройте его отдельную карту.');
    await loadGraphify();
  } catch (error) {
    showState(`Не удалось подключить Graphify: ${error.message}`, 'error-state');
  } finally {
    action.disabled = false;
    action.textContent = original;
  }
}
function renderWorkspaceControls(workspaces, selectedSource = '') {
  const select = $('#graphWorkspaceSource'); if (!select) return;
  const active = (workspaces || []).find((item) => item.id === state.mapWorkspace);
  if (!state.mapSource && selectedSource && (active?.source_ids || []).includes(selectedSource)) state.mapSource = selectedSource;
  clear(select); if (!(active?.source_ids || []).length || state.mapWorkspace === 'impact') { const placeholder = el('option', '', 'Источник не требуется'); placeholder.value = ''; select.append(placeholder); }
  (active?.source_ids || []).forEach((id) => { const option = el('option', '', id); option.value = id; if (id === state.mapSource) option.selected = true; select.append(option); });
  select.disabled = !(active?.source_ids || []).length || state.mapWorkspace === 'impact';
}
function renderProjection(projection) {
  const target = $('#graphProjectionContent');
  if (!target) return;
  clear(target);
  if (!(projection.nodes || []).length) {
    target.append(stateCard(projection.status === 'missing' ? 'Актуального графа нет' : 'В выбранном графе нет узлов', projection.diagnostics?.[0] || 'Подключите локальный источник или выберите другую задачу.', 'empty-state'));
    return;
  }
  const scene = createNetworkGraph(projection);
  activeGraphNavigator = attachGraphNavigator(scene);
  const canvasNote = el('p', 'graph-canvas-note', scene.totalNodes > scene.visibleNodes.length
    ? `На карте ${scene.visibleNodes.length} из ${scene.totalNodes} узлов. Центр — наиболее связанная сущность; наведите или выберите точку, чтобы увидеть её связи.`
    : 'Центр — наиболее связанная сущность. Наведите или выберите точку, чтобы увидеть её связи.');
  target.append(scene.svg, canvasNote);
}

function selectProjectionNode(node) {
  const inspector = $('#mapInspector'); if (!inspector) return;
  clear(inspector);
  state.selectedEntity = node.id;
  const source = node.canonical === false ? (node.evidence_source || node.source || 'внешний источник') : 'CodeSlicer';
  const properties = node.properties || {};
  const identity = properties.canonical_identity || node.canonical_identity || {};
  const location = identity.location || {};
  const file = node.file || properties.file || properties.source_file || node.provenance?.source_file || (location.file && location.file !== '<external>' ? location.file : '');
  const line = node.line || properties.line || properties.lineno || location.line;
  const edges = state.projection?.edges || [];
  const incoming = edges.filter((edge) => edge.to === node.id);
  const outgoing = edges.filter((edge) => edge.from === node.id);
  const nodeById = new Map((state.projection?.nodes || []).map((item) => [item.id, item]));
  const connectionName = (edge, direction) => {
    const id = direction === 'in' ? edge.from : edge.to;
    return nodeById.get(id)?.name || id || 'неизвестная сущность';
  };
  const kind = String(node.kind || 'ENTITY');
  const role = {
    MODULE: 'Модуль объединяет связанные части кода.',
    CLASS: 'Класс группирует состояние и поведение.',
    METHOD: 'Метод реализует отдельный шаг логики.',
    FUNCTION: 'Функция выполняет отдельное действие.',
    ROUTE: 'Маршрут является точкой входа API.',
    TEST: 'Тест проверяет поведение связанного кода.',
  }[kind] || 'Сущность показана как часть текущего графа связей.';
  const linkedKinds = unique([...incoming, ...outgoing].map((edge) => edge.kind).filter(Boolean));
  const evidence = [...incoming, ...outgoing].flatMap((edge) => edge.evidence || []).find((item) => item?.description);
  inspector.append(
    el('span', 'eyebrow', node.canonical === false ? 'УЗЕЛ GRAPHIFY' : 'УЗЕЛ ПРОЕКТА'),
    el('h2', '', node.name || node.external_id || node.id),
    tag(kind, node.canonical === false ? 'neutral' : 'good'),
    el('p', 'node-summary', role),
  );
  const facts = el('dl', 'node-facts');
  const addFact = (label, value) => { const row = el('div', ''); row.append(el('dt', '', label), el('dd', '', value)); facts.append(row); };
  addFact('Источник', source);
  addFact('Входящие связи', String(incoming.length));
  addFact('Исходящие связи', String(outgoing.length));
  if (linkedKinds.length) addFact('Типы связей', linkedKinds.slice(0, 3).join(', '));
  if (identity.module || properties.scope) addFact('Контекст', identity.module || properties.scope);
  inspector.append(facts);
  if (file) inspector.append(el('code', 'node-file', `${file}${line ? `:${line}` : ''}`));
  const connections = el('div', 'node-connections');
  const sample = [...incoming.slice(0, 2).map((edge) => ({ edge, direction: 'in' })), ...outgoing.slice(0, 2).map((edge) => ({ edge, direction: 'out' }))];
  if (sample.length) {
    connections.append(el('h3', '', 'Ближайшие связи'));
    sample.forEach(({ edge, direction }) => connections.append(el('p', '', `${direction === 'in' ? '←' : '→'} ${connectionName(edge, direction)} · ${edge.kind || 'RELATED'}`)));
    inspector.append(connections);
  }
  inspector.append(el('p', 'node-evidence', evidence?.description
    ? `Evidence: ${evidence.description}`
    : node.canonical === false
      ? 'Это часть отдельной архитектурной карты Graphify. Она не меняет выводы CodeSlicer.'
      : 'Подсвеченные линии показывают связи, отданные текущей проекцией CodeSlicer.'));
}
function updateEntitySuggestions(nodes = []) { const datalist = $('#entitySuggestions'); if (!datalist) return; clear(datalist); const all = unique([...(state.graph?.nodes || []).map((node) => node.id || node.name), ...nodes.filter((node) => node.canonical !== false).map((node) => node.id || node.name)]); all.slice(0, 500).forEach((value) => datalist.append(attr(el('option'), { value }))); }
async function openInspect(entity) {
  if (!state.project || !entity) return;
  state.selectedEntity = entity;
  const loading = el('p', '', 'Ищу подтверждённые связи в текущем графе…');
  openModal('Информация о сущности', loading, [button('Закрыть', 'button secondary', { 'data-close-overlay': 'true' })]);
  try {
    const report = dataPayload(await ImpactApi.inspect({ project_path: state.project, entity, refresh: 'never', max_context: 12 }));
    state.inspect = report;
    const body = el('div', 'modal-copy');
    const resolved = report.resolved_entity;
    if (!resolved) {
      body.append(el('p', '', report.why_not_confirmed?.[0] || 'Сущность не удалось однозначно определить.'));
      (report.candidates || []).slice(0, 8).forEach((candidate) => body.append(button(candidate.name || candidate.id, 'button secondary', { 'data-palette-entity': candidate.id })));
    } else {
      append(body, el('strong', '', resolved.name || resolved.id), el('p', 'muted', `${resolved.kind || 'ENTITY'} · ${resolved.properties?.file || resolved.file || 'файл не указан'}`), el('p', '', `Уверенность: ${report.confidence?.level || 'не указана'} (${report.confidence?.value ?? '—'}).`));
      const links = [...(report.direct_upstream || []), ...(report.direct_downstream || [])].slice(0, 8);
      if (links.length) { body.append(el('h3', '', 'Прямые связи')); links.forEach((edge) => body.append(el('p', 'muted', `${edge.kind || 'RELATED'} · ${edge.from || ''} → ${edge.to || ''}`))); }
    }
    openModal('Информация о сущности', body, [button('Исследовать связи', 'button primary', { 'data-modal-investigate': entity }), button('Закрыть', 'button secondary', { 'data-close-overlay': 'true' })]);
  } catch (error) { openModal('Информация о сущности', el('p', 'warning-text', error.message), [button('Закрыть', 'button secondary', { 'data-close-overlay': 'true' })]); }
}

async function openInvestigation(entity) {
  if (!state.project || !entity) return;
  state.selectedEntity = entity;
  openModal('Исследование связей', el('p', '', 'Строю ограниченный путь влияния…'), [button('Закрыть', 'button secondary', { 'data-close-overlay': 'true' })]);
  try {
    const report = dataPayload(await ImpactApi.investigate({ project_path: state.project, entity, direction: 'both', depth: 4, max_nodes: 80, max_edges: 160, overlay: 'codeslicer', refresh: 'never' }));
    state.investigate = report;
    const body = el('div', 'modal-copy');
    if (!report.resolved_entity) body.append(el('p', '', report.why_not_confirmed?.[0] || 'Не удалось построить путь для этой сущности.'));
    else {
      append(body, el('strong', '', report.resolved_entity.name || report.resolved_entity.id), el('p', '', `Показано ${report.nodes?.length || 0} узлов и ${report.edges?.length || 0} связей.`));
      (report.edges || []).slice(0, 12).forEach((edge) => body.append(el('p', 'muted', `${edge.kind || 'RELATED'} · ${edge.from || ''} → ${edge.to || ''}`)));
      if (report.truncated) body.append(el('p', 'warning-text', 'Результат ограничен для читаемости.'));
    }
    openModal('Исследование связей', body, [button('Закрыть', 'button secondary', { 'data-close-overlay': 'true' })]);
  } catch (error) { openModal('Исследование связей', el('p', 'warning-text', error.message), [button('Закрыть', 'button secondary', { 'data-close-overlay': 'true' })]); }
}
async function loadInspect(entity) { if (!state.project || !entity) return; state.selectedEntity = entity; if (state.route !== 'inspect') navigate('inspect', { entity }); const target = $('#inspectContent'); if (target) { clear(target); target.append(stateCard('Ищу подтверждённые связи…', 'Inspect выполняется по текущему графу.', 'loading')); } try { const response = await ImpactApi.inspect({ project_path: state.project, entity, refresh: 'never', max_context: 12 }); state.inspect = dataPayload(response); renderInspect(state.inspect); } catch (error) { if (target) { clear(target); target.append(stateCard('Не удалось разобрать сущность', error.message, 'error-state')); } } }
function renderInspect(report) { const target = $('#inspectContent'); if (!target) return; clear(target); if (report.resolved_entity === null) { target.append(stateCard(report.status === 'needs_selection' ? 'Нужно выбрать сущность' : 'Совпадение не найдено', report.why_not_confirmed?.[0] || 'Попробуйте имя из подсказок.', 'empty-state')); (report.candidates || []).forEach((candidate) => target.append(button(candidate.name || candidate.id, 'candidate-button', { 'data-candidate': candidate.id }))); return; } const entity = report.resolved_entity; const panel = el('article', 'panel inspect-card'); append(panel, cardTitle('СУЩНОСТЬ', entity.name || entity.id, `${entity.kind || 'ENTITY'} · ${entity.properties?.file || entity.file || 'файл не указан'}`)); const facts = el('div', 'fact-grid'); append(facts, metric('Confidence', report.confidence?.level || '—'), metric('Значение', report.confidence?.value ?? '—'), metric('Связей', (report.direct_upstream || []).length + (report.direct_downstream || []).length)); panel.append(facts); panel.append(el('p', 'panel-copy', `Источники: ${unique(report.confidence?.provenance || []).join(', ') || 'не указаны'}.`)); if (report.why_not_confirmed?.length) report.why_not_confirmed.slice(0, 4).forEach((item) => panel.append(el('p', 'warning-text', describe(item)))); const actions = el('div', 'inspect-actions'); append(actions, button('Проверить влияние', 'button primary', { 'data-inspect-action': 'review', 'data-entity': entity.id }), button('Исследовать', 'button secondary', { 'data-inspect-action': 'investigate', 'data-entity': entity.id }), button('Открыть код ↗', 'button secondary', { 'data-inspect-action': 'open-file', 'data-file': entity.properties?.file || entity.file || '', 'aria-label': 'Open file ↗' })); panel.append(actions); const links = el('div', 'connection-list'); append(links, el('h3', '', 'Связи и evidence')); [...(report.why_affected || []), ...(report.direct_upstream || []).map((edge) => ({ claim: 'upstream', edge })), ...(report.direct_downstream || []).map((edge) => ({ claim: 'downstream', edge }))].slice(0, 16).forEach((item) => { const edge = item.edge || item; const row = el('div', 'evidence-row'); append(row, el('span', 'status-key', item.claim ? '✓' : '?'), el('div', '', '')); row.lastChild.append(el('strong', '', `${edge.kind || 'RELATED'} · ${edge.from || ''} → ${edge.to || ''}`), el('small', 'muted', `${describe(item.claim || edge.description)} · источник: ${edge.source || 'CodeSlicer'}`)); links.append(row); }); if (!links.children.length) links.append(el('p', 'muted', 'Прямых связей не отдано.')); panel.append(links); target.append(panel); }

async function loadInvestigation(entity = $('#investigateEntity')?.value.trim()) { if (!state.project || !entity) return; state.selectedEntity = entity; if (state.route !== 'investigate') navigate('investigate', { entity }); const target = $('#investigateContent'); if (target) { clear(target); target.append(stateCard('Строю ограниченный путь…', 'Исследование запускается только по явному действию.', 'loading')); } try { const response = await ImpactApi.investigate({ project_path: state.project, entity, direction: $('#investigateDirection').value, depth: Number($('#investigateDepth').value || 8), max_nodes: Number($('#investigateNodes').value || 80), max_edges: Number($('#investigateEdges').value || 160), overlay: 'codeslicer', semantic_context: $('#investigateSemantic').checked, lsp_context: $('#investigateLsp').checked, boundary_context: $('#investigateBoundary').checked, otel_context: $('#investigateOtel').checked, security_context: $('#investigateSecurity').checked, external_graph_context: $('#investigateExternalGraph').checked, joern_context: $('#investigateJoern').checked, refresh: 'never' }); state.investigate = dataPayload(response); renderInvestigation(state.investigate); } catch (error) { if (target) { clear(target); target.append(stateCard('Исследование не выполнено', error.message, 'error-state')); } } }
function renderInvestigationGraph(report) {
  const root = report.resolved_entity;
  const nodeMap = new Map();
  if (root?.id) nodeMap.set(root.id, root);
  (report.nodes || []).forEach((node) => nodeMap.set(node.id, node));
  (report.edges || []).forEach((edge) => [edge.from, edge.to].filter(Boolean).forEach((id) => {
    if (!nodeMap.has(id)) nodeMap.set(id, { id, name: id, kind: 'ENTITY', properties: {} });
  }));
  if (!nodeMap.size) return stateCard('Нет узлов для визуализации', 'Backend не вернул bounded graph.', 'empty-state');
  const graph = {
    nodes: [...nodeMap.values()].map((node) => ({ ...node, canonical: true, evidence_source: 'codeslicer' })),
    edges: (report.edges || []).filter((edge) => nodeMap.has(edge.from) && nodeMap.has(edge.to)).map((edge) => ({ ...edge, canonical: true, evidence_source: 'codeslicer' })),
  };
  const scene = createNetworkGraph(graph);
  scene.svg.classList.remove('projection-svg');
  scene.svg.classList.add('investigate-network-svg');
  scene.svg.setAttribute('aria-label', 'Радиальная карта исследования');
  const wrapper = el('div', 'investigate-graph');
  append(wrapper, el('p', 'muted', 'Карта показывает ближайшие подтверждённые связи вокруг выбранной сущности. Для полного bounded closure используйте список evidence ниже.'), scene.svg);
  return wrapper;
}
function filteredInvestigation(report) { const rootId = report.resolved_entity?.id; const symbolsOnly = $('#investigateSymbolsOnly')?.checked; const hideTechnical = $('#investigateHideTechnical')?.checked !== false; const confirmedOnly = $('#investigateConfirmedOnly')?.checked; const nodes = (report.nodes || []).filter((node) => { if (node.id === rootId) return true; const kind = String(node.kind || '').toUpperCase(); if (symbolsOnly && !['METHOD', 'FUNCTION', 'CLASS', 'INTERFACE', 'ROUTE', 'HTTP_ROUTE', 'COMPONENT', 'MODULE', 'FILE'].includes(kind)) return false; if (hideTechnical && (['ASSIGNMENT', 'CALL_EXPR', 'STRING', 'NUMBER', 'BOOLEAN', 'ARRAY', 'OBJECT', 'KEY', 'NULL'].includes(kind) || node.properties?.builtin)) return false; return true; }); const allowed = new Set([rootId, ...nodes.map((node) => node.id)].filter(Boolean)); const edges = (report.edges || []).filter((edge) => allowed.has(edge.from) && allowed.has(edge.to) && (!confirmedOnly || edge.confirmed === true || edge.resolution === 'confirmed' || edge.quality?.status === 'confirmed')); return { ...report, nodes, edges, visited_nodes: nodes.length + (rootId && !nodes.some((node) => node.id === rootId) ? 1 : 0), visited_edges: edges.length, filter_summary: { symbols_only: Boolean(symbolsOnly), hide_technical: hideTechnical, confirmed_only: Boolean(confirmedOnly) } }; }
function ensureInvestigationFilters() { const grid = $('.advanced-grid'); if (!grid || $('#investigateSymbolsOnly')) return; [['investigateSymbolsOnly', 'Только символы', false], ['investigateHideTechnical', 'Скрыть assignments', true], ['investigateConfirmedOnly', 'Только подтверждённые связи', false]].forEach(([id, label, checked]) => { const wrapper = el('label'); const input = el('input'); input.type = 'checkbox'; input.id = id; input.checked = checked; input.addEventListener('change', () => { if (state.investigate) renderInvestigation(state.investigate); }); append(wrapper, input, document.createTextNode(` ${label}`)); grid.append(wrapper); }); }
function renderInvestigation(report) { const target = $('#investigateContent'); if (!target) return; clear(target); if (!report.resolved_entity) { target.append(stateCard(report.status === 'needs_selection' ? 'Нужно выбрать реальную сущность' : 'Совпадение не найдено', 'Граф не считается пустым из-за отсутствия совпадения.', 'empty-state')); (report.candidates || []).forEach((candidate) => target.append(button(candidate.name || candidate.id, 'candidate-button', { 'data-candidate-investigate': candidate.id }))); return; } const filtered = filteredInvestigation(report); const header = el('div', 'result-toolbar'); append(header, el('span', 'eyebrow', 'РЕЗУЛЬТАТ ИССЛЕДОВАНИЯ'), tag(filtered.truncated ? 'Ограничен' : 'Готов', filtered.truncated ? 'warn' : 'good')); target.append(header); const stats = el('div', 'stats-inline'); append(stats, metric('Bounded nodes', filtered.visited_nodes ?? filtered.nodes?.length ?? 0), metric('Связи', filtered.visited_edges ?? filtered.edges?.length ?? 0), metric('Глубина', filtered.max_depth ?? '—')); target.append(stats); target.append(renderInvestigationGraph(filtered)); const evidence = el('div', 'evidence-box'); append(evidence, el('strong', '', 'Источники'), el('p', 'muted', `Канонический граф CodeSlicer${filtered.architecture_overlay ? ' · дополнительный граф подключён как отдельный контекст' : ''}.`)); const activeFilters = Object.entries(filtered.filter_summary || {}).filter(([, value]) => value).map(([key]) => key).join(', '); if (activeFilters) evidence.append(el('p', 'muted', `Активные фильтры отображения: ${activeFilters}.`)); (filtered.warnings || []).forEach((warning) => evidence.append(el('p', 'warning-text', warning))); target.append(evidence); }

async function loadSources(force = false) { if (!state.project) return; const target = $('#sourcesContent'); if (target && (force || !state.adapters.length)) { clear(target); target.append(stateCard('Загружаю статусы локальных источников…', '', 'loading')); } try { const [architecture, adapters, lsp] = await Promise.all([ImpactApi.architecture({ project_path: state.project, overlay: 'codeslicer' }), ImpactApi.adapters(), ImpactApi.lspStatus()]); const architectureData = dataPayload(architecture); const mappingById = Object.fromEntries((architectureData.adapters || []).map((item) => [item.id, item.mapping_summary]).filter((item) => item[1])); state.adapters = (adapters.adapters || []).map((item) => ({ ...item, mapping_summary: mappingById[item.id] || item.mapping_summary })); state.lsp = lsp; renderSources(architectureData); updateStatus(); } catch (error) { if (target) { clear(target); target.append(stateCard('Статусы источников недоступны', error.message, 'error-state')); } } }
const sourceGroups = { lsp: 'Точнее перейти к коду', scip: 'Точнее перейти к коду', openapi: 'Увидеть API и события', asyncapi: 'Увидеть API и события', graphify: 'Расширить карту архитектуры', codegraph: 'Расширить карту архитектуры', gortex: 'Глобальная навигация и несколько репозиториев', otel: 'Подтвердить работу приложения', joern: 'Безопасность и зависимости', cyclonedx: 'Безопасность и зависимости', spdx: 'Безопасность и зависимости', sarif: 'Безопасность и зависимости' };
// The ordinary path is import → enable. Paths to executables and native commands are
// intentionally hidden until the user explicitly opens the advanced section.
sourceCard = function simpleSourceCard(item) {
  const id = item.id, card = el('article', 'panel source-card');
  const isLsp = id === 'lsp' || item.backend === 'agent_lsp';
  const manifest = item.manifest || {}, native = item.native || {}, status = item.status || 'unknown';
  const mapping = item.mapping_summary || {};
  const linked = Number(mapping.matched_nodes || 0) + Number(mapping.matched_relationships || 0);
  const mappingText = mapping.status === 'linked' ? `Связано с текущим проектом: ${linked}.` : mapping.status === 'unlinked' ? `Импортирован, но 0 связей сопоставлено с текущим проектом (${Number(mapping.unresolved_nodes || 0)} сущностей не сопоставлены).` : '';
  append(card, cardTitle('', manifest.display_name || item.display_name || adapterLabels[id] || id, `${statusLabel(status)} · ${statusLabel(item.freshness?.status)}`), tag(item.enabled ? 'Включён в карту' : status === 'imported' ? 'Импортирован' : 'Не подключён', item.enabled ? 'good' : 'neutral'), el('p', 'muted', mappingText || item.instruction || 'Работает локально и не меняет базовый рейтинг рисков автоматически.'));
  if (native.capabilities?.length) { const facts = el('details', 'native-capabilities'); facts.append(el('summary', '', 'Что добавит этот источник')); const list = el('ul', 'muted'); native.capabilities.forEach((capability) => list.append(el('li', '', capability))); facts.append(list); if (native.upstream_url) { const link = el('a', 'muted', 'Документация инструмента'); link.href = native.upstream_url; link.target = '_blank'; link.rel = 'noreferrer'; facts.append(link); } card.append(facts); }
  if (id === 'otel') { const live = item.live_receiver || {}; card.append(el('p', 'muted', live.enabled ? 'Приёмник принимает только OTLP/HTTP JSON с localhost. Сырые trace-данные не сохраняются.' : 'Включите локальный приём runtime trace по желанию. Приложение и внешний порт сами не запускаются.'), button(live.enabled ? 'Остановить локальный приём' : 'Включить локальный приём', 'button secondary', { 'data-adapter-action': live.enabled ? 'otel-live-disable' : 'otel-live-enable', 'data-adapter-id': id })); if (live.enabled && live.endpoint) card.append(el('code', 'native-output', `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${live.endpoint}\nOTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/json`)); }
  if (isLsp) { const row = el('div', 'adapter-actions'), input = el('input'); attr(input, { placeholder: 'Абсолютный путь к local LSP или agent-lsp', 'data-lsp-executable': 'true' }); append(row, input, button('Настроить fallback', 'button secondary', { 'data-adapter-action': 'configure-lsp', 'data-adapter-id': id }), button('Проверить Agent-LSP / LSP', 'button secondary', { 'data-adapter-action': 'lsp-probe', 'data-adapter-id': id }), button('Проверить окружение', 'button secondary', { 'data-adapter-action': 'lsp-preflight', 'data-adapter-id': id }), button('Отключить', 'button secondary', { 'data-adapter-action': 'lsp-disable', 'data-adapter-id': id })); card.append(el('p', 'muted', `Semantic backend: ${state.lsp?.adapter?.backend || item.backend || 'native_stdio'}. Agent-LSP владеет warm sessions и skills; CodeSlicer хранит только отдельный evidence overlay.`), row); }
  else { const row = el('div', 'adapter-actions'), input = el('input'); attr(input, { placeholder: id === 'gortex' ? 'Путь к Gortex .json или .graphml' : 'Путь к локальному артефакту', 'data-adapter-path': id }); append(row, input, button('Импортировать', 'button secondary', { 'data-adapter-action': 'import', 'data-adapter-id': id }), button('Включить в карту', 'button secondary', { 'data-adapter-action': 'enable', 'data-adapter-id': id }), button('Отключить', 'button secondary', { 'data-adapter-action': 'disable', 'data-adapter-id': id })); card.append(row); }
  if (!isLsp && (native.operations?.length || native.platform?.status !== 'supported')) { const advanced = el('details', 'native-setup'); advanced.append(el('summary', '', 'Дополнительно: запустить локальный инструмент')); const platform = native.platform || {}; if (platform.status && platform.status !== 'supported') advanced.append(el('p', 'warning-text', platform.message || platform.status)); advanced.append(el('p', 'muted', native.available ? `Найден локальный executable: ${native.discovered_executable}. Любой запуск требует вашего клика.` : 'Укажите существующий абсолютный путь к уже установленному инструменту. CodeSlicer ничего не скачивает сам.')); const config = el('div', 'adapter-actions'), executable = el('input'); attr(executable, { placeholder: 'Абсолютный путь к executable / .bat', value: native.configured_executable || '', 'data-native-executable': id }); append(config, executable, button('Сохранить путь', 'button secondary', { 'data-adapter-action': 'configure-native', 'data-adapter-id': id })); advanced.append(config); if (native.operations?.length) { const actions = el('div', 'adapter-actions'); native.operations.forEach((operation) => actions.append(button(operation.title, 'button secondary', { 'data-native-action': operation.id, 'data-adapter-id': id, title: operation.description, disabled: native.available ? null : 'disabled' }))); advanced.append(actions); } card.append(advanced); }
  return card;
};
const adapterLabels = { scip: 'SCIP', otel: 'OpenTelemetry', cyclonedx: 'CycloneDX', sarif: 'SARIF', spdx: 'SPDX', openapi: 'OpenAPI', asyncapi: 'AsyncAPI', graphify: 'Graphify', codegraph: 'CodeGraph', gortex: 'Gortex', joern: 'Joern', lsp: 'LSP' };
const baseSourceCard = sourceCard;
sourceCard = function runtimeSourceCard(item) {
  const card = baseSourceCard(item); const tool = state.tools.find((candidate) => candidate.id === item.id);
  if (!tool) return card;
  const action = tool.connected ? button(`Открыть ${tool.title}`, 'button primary', { 'data-route': `tool-${tool.id}` }) : button(`Подключить полный ${tool.title}`, 'button primary', { 'data-tool-action': 'connect', 'data-tool-id': tool.id });
  card.append(el('p', 'muted', tool.connected ? 'Подключён полный upstream workspace: документация и команды доступны в отдельной вкладке.' : 'Подключение клонирует полный upstream-репозиторий локально только после подтверждения.'), action);
  return card;
};
function renderToolNavigation() { const target = $('#toolNavigation'); if (!target) return; clear(target); const connected = state.tools.filter((tool) => tool.connected); target.hidden = !connected.length; connected.forEach((tool, index) => { const link = el('a', '', ''); attr(link, { href: `#tool-${tool.id}`, 'data-route': `tool-${tool.id}` }); append(link, el('span', 'nav-index', String(index + 1).padStart(2, '0')), el('strong', '', tool.title)); target.append(link); }); }
function staleApiToolMessage() { return 'Запущенный local API не поддерживает управление upstream-инструментами. Вероятно, frontend новее работающего сервера. Остановите старый процесс и запустите impact-engine-local-api из этой версии CodeSlicer.'; }
async function loadTools() { if (!state.project) return; if (state.apiCompatibility) { state.tools = []; state.toolRuntimeError = staleApiToolMessage(); renderToolNavigation(); return; } try { const result = await ImpactApi.tools(); state.tools = result.tools || []; state.toolRuntimeError = null; renderToolNavigation(); } catch (error) { state.tools = []; state.toolRuntimeError = error?.status === 404 ? staleApiToolMessage() : `Не удалось загрузить список upstream-инструментов: ${error.message}`; renderToolNavigation(); } }
async function loadToolWorkspace(toolId) { const target = $('#toolWorkspaceContent'); if (!target) return; let tool = state.tools.find((item) => item.id === toolId); if (!tool) { await loadTools(); tool = state.tools.find((item) => item.id === toolId); } if (!tool) { clear(target); target.append(stateCard(state.apiCompatibility ? 'Требуется перезапуск local API' : 'Инструмент не найден', state.toolRuntimeError || 'Откройте Источники и подключите доступный upstream-инструмент.', 'error-state')); return; } clear(target); const view = el('div', 'tool-workspace'); const heading = el('div', 'page-heading'); append(heading, el('div', '', '')); heading.firstChild.append(el('span', 'eyebrow', 'UPSTREAM / ПОЛНЫЙ ИНСТРУМЕНТ'), el('h1', '', tool.title), el('p', 'muted', tool.purpose)); view.append(heading); const status = el('article', 'panel'); append(status, cardTitle('ЛОКАЛЬНЫЙ WORKSPACE', tool.repository?.cloned ? 'Репозиторий подключён' : 'Протокол подключён', tool.repository?.commit ? `commit ${tool.repository.commit}` : 'Исходники остаются отдельно от CodeSlicer.'), el('p', 'muted', tool.repository?.path || 'Для LSP используется указанный локальный сервер.'), tag(tool.executable?.configured ? 'Executable настроен' : 'Executable не настроен', tool.executable?.configured ? 'good' : 'warn')); view.append(status);
  if (toolId === 'graphify') {
    const viewerCard = el('article', 'panel');
    append(viewerCard, cardTitle('РЕЗУЛЬТАТ GRAPHIFY', 'Нативный граф Graphify выбранного проекта', 'Показывается только артефакт graphify-out/graph.json, созданный Graphify. Если его нет, сначала настройте Graphify и явно постройте архитектурный граф.'));
    const iframe = el('iframe', 'graphify-iframe');
    attr(iframe, { src: '/api/adapters/graphify/viewer', sandbox: 'allow-scripts', referrerpolicy: 'no-referrer', style: 'width: 100%; height: 750px; border: 1px solid #2a2a4e; border-radius: 8px; background: #0f0f1a;' });
    viewerCard.append(iframe);
    view.append(viewerCard);
  }
  const executable = el('article', 'panel'); const executableInput = el('input'); attr(executableInput, { placeholder: 'Абсолютный путь к локальному executable', value: tool.executable?.path || '', 'data-tool-executable': tool.id }); append(executable, cardTitle('EXECUTABLE', 'Полный upstream CLI', 'Укажите установленный локальный бинарник или .bat; CodeSlicer не подменяет команды.'), el('div', 'adapter-actions', '')); executable.lastChild.append(executableInput, button('Сохранить executable', 'button secondary', { 'data-tool-action': 'executable', 'data-tool-id': tool.id }), button('Показать реальный --help', 'button secondary', { 'data-tool-action': 'help', 'data-tool-id': tool.id, disabled: tool.executable?.configured ? null : 'disabled' })); view.append(executable);
  const commands = el('article', 'panel'); const argv = el('textarea', 'tool-command-input'); attr(argv, { placeholder: 'Аргументы в JSON-массиве, например:\n["query", "symbol", "AuthService", "--format", "json"]', 'data-tool-argv': tool.id }); append(commands, cardTitle('RAW COMMAND', 'Любая команда upstream CLI', 'Команда передаётся как argv без shell. Запуск всегда требует отдельного подтверждения.'), argv, button('Запустить команду', 'button primary', { 'data-tool-action': 'run', 'data-tool-id': tool.id, disabled: tool.executable?.configured ? null : 'disabled' })); view.append(commands);
  const docs = el('article', 'panel'); const query = el('input'); attr(query, { placeholder: 'Поиск по документации upstream', 'data-tool-doc-query': tool.id }); append(docs, cardTitle('ДОКУМЕНТАЦИЯ ИСХОДНИКА', `${tool.documentation?.indexed || 0} локальных документов`, 'Agent и пользователь читают файлы из локального клона; ничего не отправляется наружу.'), el('div', 'adapter-actions', '')); docs.lastChild.append(query, button('Искать документы', 'button secondary', { 'data-tool-action': 'docs', 'data-tool-id': tool.id })); const results = el('div', 'tool-doc-list'); results.dataset.toolDocs = tool.id; docs.append(results); view.append(docs); target.append(view); }
async function handleToolAction(action) { const id = action.dataset.toolId; const kind = action.dataset.toolAction; action.disabled = true; const original = action.textContent; try { let response; if (kind === 'connect') { if (!window.confirm(`Будет клонирован полный upstream-репозиторий ${id} в .codeslicer/tool-runtime/${id}. Сеть будет использована только для этого Git clone. Продолжить?`)) return; response = await ImpactApi.toolConnect(id, { project_path: state.project, confirmed: true }); await loadTools(); await loadSources(true); navigate(`tool-${id}`); } else if (kind === 'executable') { const executable = $(`[data-tool-executable="${CSS.escape(id)}"]`)?.value.trim(); response = await ImpactApi.toolExecutable(id, { project_path: state.project, executable }); await loadTools(); await loadToolWorkspace(id); } else if (kind === 'help') { response = await ImpactApi.toolHelp(id, { project_path: state.project }); append($('#toolWorkspaceContent'), el('pre', 'output', response.output || 'Нет вывода.')); } else if (kind === 'docs') { const query = $(`[data-tool-doc-query="${CSS.escape(id)}"]`)?.value.trim() || ''; response = await ImpactApi.toolDocs(id, { project_path: state.project, query }); const target = $(`[data-tool-docs="${CSS.escape(id)}"]`); clear(target); (response.documents || []).forEach((doc) => { const item = button('', 'tool-doc', { 'data-tool-document': doc.path, 'data-tool-id': id }); append(item, el('strong', '', doc.title || doc.path), el('small', '', doc.path), el('small', 'muted', doc.excerpt || '')); target.append(item); }); } else if (kind === 'run') { const value = $(`[data-tool-argv="${CSS.escape(id)}"]`)?.value || '[]'; let argv; try { argv = JSON.parse(value); } catch (_) { throw new Error('Аргументы должны быть JSON-массивом строк.'); } if (!window.confirm(`Запустить ${id} с указанными аргументами? Инструмент может менять только свой локальный workspace и выбранный проект согласно переданной команде.`)) return; response = await ImpactApi.toolRun(id, { project_path: state.project, argv, confirmed: true }); append($('#toolWorkspaceContent'), el('pre', 'output', `${response.command?.join(' ') || id}\n\n${response.stdout || response.stderr || response.status}`)); } showState(`${id}: действие выполнено локально.`); } catch (error) { showState(`${id}: ${error.message}`, 'error-state'); } finally { action.disabled = false; action.textContent = original; } }
function renderSources(architecture) { const target = $('#sourcesContent'); if (!target) return; clear(target); if (state.toolRuntimeError) target.append(stateCard('Требуется обновить local API', state.toolRuntimeError, 'warning-state')); const items = state.adapters.length ? state.adapters : Object.entries(architecture).filter(([key, value]) => sourceGroups[key] && value && typeof value === 'object').map(([id, value]) => ({ id, ...value })); const grouped = new Map(); items.forEach((item) => { const id = item.id || item.adapter_id; if (!id || id === 'codeslicer') return; const group = sourceGroups[id] || 'Дополнительный локальный контекст'; if (!grouped.has(group)) grouped.set(group, []); grouped.get(group).push({ ...item, id }); }); const canonical = el('article', 'panel source-card canonical-source'); append(canonical, cardTitle('КАНОНИЧЕСКИЙ ИСТОЧНИК', 'CodeSlicer', 'Владеет graph, risk, top-impact и рекомендациями тестов.'), tag('Готов · local-only', 'good'), el('p', 'muted', 'Внешние и дополнительные источники не меняют ranking автоматически.')); target.append(canonical); const quickHub = el('article', 'panel source-card quick-adapters-hub'); const hubActions = el('div', 'adapter-actions quick-hub-actions'); append(quickHub, cardTitle('ДОПОЛНИТЕЛЬНЫЙ ИНСТРУМЕНТ (GRAPHIFY)', 'Нативный запуск и импорт архитектурного графа Graphify', 'Используйте Graphify для построения карт архитектуры и комьюнити.'), hubActions); hubActions.append(
  button('⚡ Graphify (Архитектура)', 'button primary', { 'data-native-action': 'index', 'data-adapter-id': 'graphify' }),
  button('📥 Импортировать graphify-out/graph.json', 'button secondary', { 'data-adapter-action': 'import', 'data-adapter-id': 'graphify' }),
  button('⚡ Включить оверлей Graphify', 'button secondary', { 'data-adapter-action': 'enable', 'data-adapter-id': 'graphify' }),
  button('⏸️ Отключить Graphify', 'button secondary', { 'data-adapter-action': 'disable', 'data-adapter-id': 'graphify' })
); target.append(quickHub); grouped.forEach((cards, title) => { const section = el('section', 'source-group'); section.append(el('h2', '', title)); cards.forEach((item) => section.append(sourceCard(item))); target.append(section); }); if (!grouped.size) target.append(stateCard('Дополнения не зарегистрированы', 'Backend не вернул optional adapters для выбранного проекта.', 'empty-state')); }
function sourceCard(item) { const id = item.id; const card = el('article', 'panel source-card'); const manifest = item.manifest || {}; const native = item.native || {}; const status = item.status || 'unknown'; const mapping = item.mapping_summary || {}; const linkedCount = Number(mapping.matched_nodes || 0) + Number(mapping.matched_relationships || 0); const mappingText = mapping.status === 'unlinked' ? `Импортирован, но 0 связей сопоставлено с текущим проектом (${Number(mapping.unresolved_nodes || 0)} сущностей, ${Number(mapping.unresolved_relationships || 0)} связей не сопоставлены).` : mapping.status === 'linked' ? `Сопоставлено с текущим проектом: ${linkedCount}.` : ''; append(card, cardTitle('', manifest.display_name || item.display_name || adapterLabels[id] || id, `${statusLabel(status)} · свежесть: ${statusLabel(item.freshness?.status)}`)); card.append(tag(item.enabled ? '🟢 Включён в граф' : status === 'imported' ? '🟡 Импортирован (не включён)' : '⚪ Выключен', item.enabled ? 'good' : status === 'imported' ? 'warn' : 'neutral')); card.append(el('p', 'muted', mappingText || item.instruction || 'Добавляет контекст и не меняет канонический рейтинг. Артефакт остаётся локальным.')); if (native.capabilities?.length) { const details = el('details', 'native-capabilities'); details.append(el('summary', '', 'Нативные возможности источника')); const list = el('ul', 'muted'); native.capabilities.forEach((capability) => list.append(el('li', '', capability))); details.append(list); if (native.upstream_url) { const link = el('a', 'muted', 'Открыть upstream-документацию'); link.href = native.upstream_url; link.target = '_blank'; link.rel = 'noreferrer'; details.append(link); } if (native.license_note) details.append(el('p', 'warning-text', native.license_note)); card.append(details); const platform = native.platform || {}; if (platform.status && platform.status !== 'supported') card.append(el('p', 'warning-text', platform.message || platform.status)); const config = el('div', 'adapter-actions'); const executable = el('input'); attr(executable, { placeholder: 'Абсолютный путь к локальному executable / .bat', value: native.configured_executable || '', 'data-native-executable': id }); append(config, executable, button('Сохранить путь', 'button secondary', { 'data-adapter-action': 'configure-native', 'data-adapter-id': id })); card.append(el('p', 'muted', native.available ? `Нативный executable найден: ${native.discovered_executable}. Запуск требует отдельного подтверждения.` : 'Инструмент не найден: укажите существующий абсолютный путь или импортируйте артефакт.'), config); const actions = native.operations || []; if (actions.length) { const row = el('div', 'adapter-actions'); actions.forEach((operation) => row.append(button(operation.title, 'button secondary', { 'data-native-action': operation.id, 'data-adapter-id': id, title: operation.description, disabled: native.available ? null : 'disabled' }))); card.append(row); } } if (id === 'otel') { const live = item.live_receiver || {}; const row = el('div', 'adapter-actions'); append(row, button(live.enabled ? '⏹️ Остановить live-приём' : '▶️ Включить live-приём', 'button secondary', { 'data-adapter-action': live.enabled ? 'otel-live-disable' : 'otel-live-enable', 'data-adapter-id': id })); card.append(el('p', live.enabled ? 'Live receiver принимает только OTLP/HTTP JSON с localhost. Сырые trace payload не сохраняются.' : 'Можно явно включить loopback OTLP/HTTP JSON receiver. Он не открывает внешний порт и не запускает приложение.'), row); if (live.enabled && live.endpoint) card.append(el('code', 'native-output', `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${live.endpoint}\nOTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/json`)); } if (id === 'lsp') { const row = el('div', 'adapter-actions'); const input = el('input'); attr(input, { placeholder: 'Абсолютный путь к локальному LSP', 'data-lsp-executable': 'true' }); append(row, input, button('Настроить', 'button secondary', { 'data-adapter-action': 'configure-lsp', 'data-adapter-id': id }), button('Проверить', 'button secondary', { 'data-adapter-action': 'lsp-probe', 'data-adapter-id': id }), button('Отключить', 'button secondary', { 'data-adapter-action': 'lsp-disable', 'data-adapter-id': id })); card.append(el('p', 'muted', 'LSP — локальный процесс, не файл. Он не запускается без указанного пути.'), row); } else { const row = el('div', 'adapter-actions'); const input = el('input'); attr(input, { placeholder: id === 'gortex' ? 'Абсолютный путь к Gortex .json или .graphml' : 'Абсолютный путь к локальному артефакту', 'data-adapter-path': id }); append(row, input, button('📥 Импортировать', 'button secondary', { 'data-adapter-action': 'import', 'data-adapter-id': id }), button('⚡ Включить в граф', 'button secondary', { 'data-adapter-action': 'enable', 'data-adapter-id': id }), button('⏸️ Отключить', 'button secondary', { 'data-adapter-action': 'disable', 'data-adapter-id': id })); card.append(row); } return card; }

async function loadAutomation() { const target = $('#automationContent'); if (!target || !state.project) return; clear(target); target.append(stateCard('Загружаю CI-отчёт…', '', 'loading')); try { const report = dataPayload(await ImpactApi.ci({ project_path: state.project, refresh: 'auto', run_tests: false })); clear(target); const panel = el('article', 'panel ci-card'); append(panel, cardTitle('CI', `Статус: ${statusLabel(report.status)}`, 'Отчёт получен локально; команды не запускаются без явного действия.')); (report.findings || report.violations || []).slice(0, 20).forEach((finding) => panel.append(el('div', 'evidence-row', `${finding.level || finding.rule || 'Сигнал'} · ${finding.message || finding.reason || describe(finding)}`))); if (!report.findings?.length && !report.violations?.length) panel.append(el('p', 'muted', 'Нарушений или findings не отдано.')); if (report.test_execution) panel.append(el('p', 'muted', `Тестовый запуск: ${textOf(report.test_execution.status)}${report.test_execution.explicit ? ' · выполнен явно' : ' · не запрашивался'}`)); target.append(panel); } catch (error) { clear(target); target.append(stateCard('CI-отчёт недоступен', error.message, 'error-state')); } }

function showProgress(progress) { const panel = $('#progressPanel'); if (!panel) return; panel.hidden = false; const current = progress?.current || progress || {}; const percent = Math.max(0, Math.min(100, Number(current.overall_percent || 0))); setText('#progressStage', statusLabel(current.stage || progress?.status || 'running')); setText('#progressPercent', `${Math.round(percent)}%`); setText('#progressMessage', current.message || 'Локальный анализ продолжается…'); $('#progressBar').style.width = `${percent}%`; }
async function pollAnalysisProgress(shouldStop = () => false) { while (!shouldStop()) { try { const response = await ImpactApi.progress(); const status = String(response.progress?.status || '').toLowerCase(); showProgress(response.progress); /* The first poll can legitimately race the POST /api/analyze handler and still be idle. */ if (['completed', 'cancelled', 'failed'].includes(status)) return response.progress; } catch (_) { /* The analyze request remains the source of truth. */ } if (shouldStop()) return null; await sleep(350); } return null; }
async function startAnalysis(pathValue) { const project = String(pathValue || '').trim(); if (!project) { showState('Укажите абсолютный путь к проекту.', 'error-state'); return; } const previous = { project: state.project, hasAnalysis: state.hasAnalysis, analysis: state.analysis, graph: state.graph, overview: state.overview, review: state.review, projection: state.projection, inspect: state.inspect, investigate: state.investigate, analyzedAt: state.analyzedAt }; state.project = project; $('#projectPath').value = project; $('#onboardingPath').value = project; $('#analyzeButton').disabled = true; $('#onboardingAnalyze').disabled = true; $('#cancelAnalyzeButton').hidden = false; $('#progressPanel').hidden = false; showProgress({ status: 'running', current: { stage: 'starting', message: 'Проверяю путь и строю карту', overall_percent: 0 } }); let stopPolling = false; const request = ImpactApi.analyze(project); const progress = pollAnalysisProgress(() => stopPolling); try { const response = await request; await progress; state.hasAnalysis = true; state.analysis = response; state.graph = response.graph || null; state.overview = null; state.review = null; state.projection = null; await hydrateAnalysis(); $('#progressPanel').hidden = true; navigate('review'); showState('Карта проекта готова.'); } catch (error) { stopPolling = true; await progress.catch(() => {}); $('#progressPanel').hidden = true; state.project = previous.project; state.hasAnalysis = previous.hasAnalysis; state.analysis = previous.analysis; state.graph = previous.graph; state.overview = previous.overview; state.review = previous.review; state.projection = previous.projection; state.inspect = previous.inspect; state.investigate = previous.investigate; state.analyzedAt = previous.analyzedAt; $('#projectPath').value = previous.project || ''; $('#onboardingPath').value = previous.project || ''; const message = /cancel/i.test(error.message) ? 'Построение карты отменено. Предыдущая карта сохранена.' : `Карта не построена: ${error.message}`; $('#onboardingError').hidden = false; $('#onboardingError').textContent = message; showState(message, 'error-state'); if (!previous.hasAnalysis) showOnboarding(true); } finally { $('#analyzeButton').disabled = false; $('#onboardingAnalyze').disabled = false; $('#cancelAnalyzeButton').hidden = true; } }
async function hydrateAnalysis() { try { const current = await ImpactApi.state(); state.hasAnalysis = Boolean(current.has_analysis); state.analysis = current.analysis || state.analysis; state.analyzedAt = current.analyzed_at || state.analyzedAt; const graph = await ImpactApi.graph(); state.graph = graph.graph || graph; } catch (_) { state.hasAnalysis = Boolean(state.graph || state.analysis); } updateEntitySuggestions(state.graph?.nodes || []); updateStatus(); }
async function cancelAnalysis() { try { await ImpactApi.cancelAnalyze(); showState('Запрос на отмену отправлен локальному анализатору.'); } catch (error) { showState(error.message, 'error-state'); } }

function openModal(title, content, actions = []) { state.modalOpener = document.activeElement; setText('#modalTitle', title); const body = $('#modalContent'); clear(body); if (typeof content === 'string') body.append(el('p', '', content)); else body.append(content); const actionBar = $('#modalActions'); clear(actionBar); actions.forEach((item) => actionBar.append(item)); $('#modalBackdrop').hidden = false; $('#modal').focus?.(); const focusable = $$('button, input, select, textarea, [href]', $('#modal')); focusable[0]?.focus(); }
function setMobileDrawer(open) { const drawer = $('#mobileDrawer'); const button = $('#mobileMenuButton'); if (!drawer) return; drawer.hidden = !open; drawer.setAttribute('aria-hidden', open ? 'false' : 'true'); if (button) button.setAttribute('aria-expanded', open ? 'true' : 'false'); }
function closeOverlays() { $$('.overlay').forEach((overlay) => { overlay.hidden = true; overlay.setAttribute('aria-hidden', 'true'); }); setMobileDrawer(false); const opener = state.modalOpener; state.modalOpener = null; if (opener && document.contains(opener)) opener.focus(); }
function confirmTest(test) { const body = el('div', 'confirm-copy'); append(body, el('p', '', 'Будет запущен только безопасный target, который backend разрешит для выбранного файла.'), el('code', '', textOf(test.command, test.file || 'Команда будет определена backend'))); const cancel = button('Отмена', 'button secondary', { 'data-close-overlay': 'true' }); const run = button('Запустить', 'button primary', { 'data-confirm-test': 'true' }); run._test = test; openModal('Подтвердить запуск теста', body, [cancel, run]); }
async function executeTest(test) { closeOverlays(); const resultTarget = $('.test-result'); if (resultTarget) resultTarget.replaceChildren(stateCard('Тест выполняется…', 'Ожидаю ответ /api/review/run-test.', 'loading')); try { state.lastTest = await ImpactApi.reviewRunTest({ project_path: state.project, file: test.file }); renderReview(); showState(state.lastTest.passed ? 'Тест завершился успешно.' : 'Тест не прошёл. Это не равно ошибке CodeSlicer.', state.lastTest.passed ? '' : 'error-state'); } catch (error) { state.lastTest = { status: 'error', passed: false, stderr: error.message }; renderReview(); showState(error.message, 'error-state'); } }
function openEvidence(entity) { const item = normalizeImpacts(state.review).find((candidate) => (candidate.entity_id || candidate.id || candidate.symbol) === entity); const body = el('div', 'modal-copy'); append(body, el('p', '', 'Доказательства строятся из ответа Review и не подменяются данными архива.'), el('p', '', describe(item?.why_affected || item?.why || item?.reason)), el('p', 'muted', `Источники: ${unique(item?.evidence_ids || []).join(', ') || 'не указаны'}`)); openModal('Доказательства влияния', body, [button('Закрыть', 'button secondary', { 'data-close-overlay': 'true' })]); }
function openFileNotice(path) { const body = el('div', 'modal-copy'); append(body, el('p', '', path ? `Файл: ${path}` : 'Файл не указан backend.'), el('p', 'muted', 'Открытие в редакторе не подключено к local API, поэтому действие отключено честно.')); openModal('Открытие кода', body, [button('Закрыть', 'button secondary', { 'data-close-overlay': 'true' })]); }
function openPalette() { const input = $('#paletteInput'); renderPalette(''); $('#paletteBackdrop').hidden = false; input.focus(); }
function searchableNode(node) { const kind = String(node.kind || '').toUpperCase(); const name = String(node.name || ''); const id = String(node.id || ''); const value = `${name} ${id}`.toLowerCase(); return !['ASSIGNMENT', 'CALL_EXPR', 'STRING', 'NUMBER', 'BOOLEAN', 'ARRAY', 'OBJECT', 'KEY', 'NULL', 'EXTERNAL_LIBRARY', 'SUPPORT_PACK', 'LIBRARY'].includes(kind) && !node.properties?.builtin && name.length <= 180 && !/(prompt|system message|developer message|you are an ai|```)/i.test(value); }
function renderPalette(query) { const target = $('#paletteResults'); if (!target) return; clear(target); const q = String(query || '').toLowerCase(); const pages = Object.entries(routeNames).filter(([id]) => id !== 'inspect' && routeNames[id].toLowerCase().includes(q)); const pageGroup = el('div', 'palette-group'); pageGroup.append(el('span', 'eyebrow', 'Экраны')); pages.forEach(([id, name]) => pageGroup.append(button(name, 'palette-item', { 'data-route': id }))); target.append(pageGroup); const graphNodes = [...(state.graph?.nodes || []), ...(state.projection?.nodes || [])].filter(searchableNode); const entities = []; const seen = new Set(); graphNodes.forEach((node) => { const id = String(node.id || node.name); const label = String(node.name || id); const haystack = `${id} ${label} ${node.properties?.file || ''}`.toLowerCase(); if (seen.has(id) || (q && !haystack.includes(q))) return; seen.add(id); entities.push({ id, label }); }); const entityGroup = el('div', 'palette-group'); entityGroup.append(el('span', 'eyebrow', 'Сущности текущего графа')); if (!entities.length) entityGroup.append(el('p', 'muted', 'Совпадений нет.')); entities.slice(0, 30).forEach((item) => entityGroup.append(button(item.label, 'palette-item', { 'data-palette-entity': item.id, title: item.id }))); target.append(entityGroup); }
function openMobileDrawer() { const target = $('#mobileNavigation'); clear(target); $$('[data-route]', $('#mainNavigation')).forEach((link) => { const copy = el('a', '', link.textContent); attr(copy, { href: `#${normalizeRoute(link.dataset.route)}`, 'data-route': normalizeRoute(link.dataset.route) }); target.append(copy); }); setMobileDrawer(true); }

document.addEventListener('click', (event) => {
  const paletteEntity = event.target.closest?.('[data-palette-entity]'); if (paletteEntity) { closeOverlays(); state.selectedEntity = paletteEntity.dataset.paletteEntity; openInspect(state.selectedEntity); return; }
  const route = event.target.closest?.('[data-route]'); if (route) { event.preventDefault(); closeOverlays(); navigate(route.dataset.route); return; }
  const graphifyAction = event.target.closest?.('[data-graphify-action]'); if (graphifyAction) { handleGraphifyAction(graphifyAction); return; }
  const close = event.target.closest?.('[data-close-overlay]'); if (close) { closeOverlays(); return; }
  if (event.target.classList.contains('overlay')) { closeOverlays(); return; }
  const action = event.target.closest?.('[data-action]'); if (action) { const name = action.dataset.action; if (name === 'refresh-overview') { state.overview = null; loadOverview(true); } if (name === 'refresh-review') { state.review = null; loadReview(true); } if (name === 'analyze') startAnalysis($('#projectPath').value); if (name === 'run-selected-tests') { const checked = $$('.test-row input:checked').map((input) => input.dataset.testFile).filter(Boolean); if (!checked.length) { showState('Нет разрешённого target для запуска.', 'warning-state'); } else { confirmTest({ file: checked[0] }); } } if (name === 'toggle-more') { state.showMore = !state.showMore; renderReview(); } return; }
  const filter = event.target.closest?.('[data-review-filter]'); if (filter) { state.reviewFilter = filter.dataset.reviewFilter; renderReview(); return; }
  const file = event.target.closest?.('[data-review-file]'); if (file) { state.selectedFile = file.dataset.reviewFile; renderReview(); return; }
  const impact = event.target.closest?.('[data-impact-action]'); if (impact) { const entity = impact.dataset.entity; if (impact.dataset.impactAction === 'inspect') openInspect(entity); if (impact.dataset.impactAction === 'evidence') openEvidence(entity); if (impact.dataset.impactAction === 'investigate') openInvestigation(entity); if (impact.dataset.impactAction === 'open-file') openFileNotice(impact.dataset.file); return; }
  const projection = event.target.closest?.('[data-projection-action]'); if (projection) { const entity = projection.dataset.projectionEntity; const node = (state.projection?.nodes || []).find((item) => item.id === entity); if (projection.dataset.projectionAction === 'why') selectProjectionNode(node || { id: entity }); if (projection.dataset.projectionAction === 'chain') { if (node?.canonical === false) selectProjectionNode(node); else openInvestigation(entity); } if (projection.dataset.projectionAction === 'copy') navigator.clipboard?.writeText(entity).then(() => showState('ID скопирован.')).catch(() => openModal('Stable ID', el('code', '', entity), [button('Закрыть', 'button secondary', { 'data-close-overlay': 'true' })])); return; }
  const candidate = event.target.closest?.('[data-candidate], [data-candidate-investigate]'); if (candidate) { const entity = candidate.dataset.candidate || candidate.dataset.candidateInvestigate; openInspect(entity); return; }
  const inspectAction = event.target.closest?.('[data-inspect-action]'); if (inspectAction) { const entity = inspectAction.dataset.entity; if (inspectAction.dataset.inspectAction === 'review') { state.selectedEntity = entity; state.review = null; navigate('review', { entity }); loadReview(true); } if (inspectAction.dataset.inspectAction === 'investigate') openInvestigation(entity); if (inspectAction.dataset.inspectAction === 'open-file') openFileNotice(inspectAction.dataset.file); return; }
  const modalInvestigate = event.target.closest?.('[data-modal-investigate]'); if (modalInvestigate) { closeOverlays(); openInvestigation(modalInvestigate.dataset.modalInvestigate); return; }
  const test = event.target.closest?.('[data-test-file]'); if (test?.dataset.testFile && event.detail === 2) confirmTest({ file: test.dataset.testFile, command: test.dataset.testCommand });
  const quickImport = event.target.closest?.('[data-quick-import]'); if (quickImport) handleQuickImport(quickImport);
  const adapter = event.target.closest?.('[data-adapter-action]'); if (adapter) handleAdapterAction(adapter);
  const native = event.target.closest?.('[data-native-action]'); if (native) handleNativeAction(native);
  const toolAction = event.target.closest?.('[data-tool-action]'); if (toolAction) { handleToolAction(toolAction); return; }
  const toolDocument = event.target.closest?.('[data-tool-document]'); if (toolDocument) { ImpactApi.toolDocument(toolDocument.dataset.toolId, { project_path: state.project, path: toolDocument.dataset.toolDocument }).then((response) => openModal(response.path, el('pre', 'output', response.content || ''), [button('Закрыть', 'button secondary', { 'data-close-overlay': 'true' })])).catch((error) => showState(error.message, 'error-state')); return; }
  const mapWorkspace = event.target.closest?.('[data-map-workspace]'); if (mapWorkspace) { state.mapWorkspace = mapWorkspace.dataset.mapWorkspace; state.mapSource = ''; $$('.workspace-tabs [data-map-workspace]').forEach((item) => item.classList.toggle('active', item === mapWorkspace)); loadProjection(true); return; }
  const mapLevel = event.target.closest?.('[data-map-level]'); if (mapLevel) { state.mapLevel = mapLevel.dataset.mapLevel; state.mapKind = ''; $$('.segmented [data-map-level], .segmented [data-map-kind]').forEach((item) => item.classList.toggle('active', item === mapLevel)); loadProjection(true); }
  const mapKind = event.target.closest?.('[data-map-kind]'); if (mapKind) { state.mapKind = mapKind.dataset.mapKind; $$('.segmented [data-map-level], .segmented [data-map-kind]').forEach((item) => item.classList.toggle('active', item === mapKind)); loadProjection(true); }
  const preset = event.target.closest?.('[data-preset]'); if (preset) { $$('.preset').forEach((item) => item.classList.toggle('active', item === preset)); if (preset.dataset.preset !== 'tests') $('#investigateDirection').value = preset.dataset.preset; }
  const confirm = event.target.closest?.('[data-confirm-test]'); if (confirm) executeTest(confirm._test); // property is assigned on the element above
});

async function handleQuickImport(action) { const id = action.dataset.quickImport; const path = window.prompt(`Введите абсолютный путь к локальному артефакту ${id.toUpperCase()}:`, ''); if (!path) return; action.disabled = true; const original = action.textContent; try { const project_path = state.project; await ImpactApi.adapterImport(id, { project_path, artifact_path: path.trim() }); await ImpactApi.adapterEnable(id, { project_path }); showState(`Источник ${id} успешно импортирован и включён в граф.`); await loadSources(true); } catch (error) { showState(`Ошибка импорта ${id}: ${error.message}`, 'error-state'); } finally { action.disabled = false; action.textContent = original; } }
async function handleAdapterAction(action) {
  const id = action.dataset.adapterId;
  const project_path = state.project;
  const original = action.textContent;
  action.disabled = true;
  try {
    let response;
    if (action.dataset.adapterAction === 'import') {
      const path = $(`[data-adapter-path="${CSS.escape(id)}"]`)?.value.trim();
      if (!path) throw new Error('Укажите абсолютный путь к локальному артефакту.');
      response = await ImpactApi.adapterImport(id, { project_path, artifact_path: path });
    } else if (action.dataset.adapterAction === 'enable') response = await ImpactApi.adapterEnable(id, { project_path });
    else if (action.dataset.adapterAction === 'configure-native') {
      const executable = $(`[data-native-executable="${CSS.escape(id)}"]`)?.value.trim();
      if (!executable) throw new Error('Укажите абсолютный путь к уже установленному локальному executable.');
      response = await ImpactApi.nativeConfigure(id, { project_path, executable });
    } else if (action.dataset.adapterAction === 'configure-lsp') {
      const executable = $('[data-lsp-executable]')?.value.trim();
      if (!executable) throw new Error('Укажите абсолютный путь к уже установленному локально LSP.');
      response = await ImpactApi.lspConfigure({ project_path, executable, workspace_roots: [project_path], backend: 'native_stdio', server_family: 'clangd' });
    } else if (action.dataset.adapterAction === 'lsp-preflight') response = await ImpactApi.lspPreflight({ project_path });
    else if (action.dataset.adapterAction === 'lsp-probe') response = await ImpactApi.lspProbe({ project_path });
    else if (action.dataset.adapterAction === 'lsp-disable') response = await ImpactApi.lspDisable({ project_path });
    else if (action.dataset.adapterAction === 'otel-live-enable') response = await ImpactApi.otelLiveEnable({ project_path });
    else if (action.dataset.adapterAction === 'otel-live-disable') response = await ImpactApi.otelLiveDisable({ project_path });
    else if (action.dataset.adapterAction === 'disable') response = await ImpactApi.adapterDisable(id, { project_path });
    if (response) showState(`${id}: ${JSON.stringify(dataPayload(response)).slice(0, 700)}`);
    await loadSources(true);
  } catch (error) { showState(`${id}: ${error.message}`, 'error-state'); }
  finally { action.disabled = false; action.textContent = original; }
}
async function handleNativeAction(action) { const id = action.dataset.adapterId; const operation = action.dataset.nativeAction; const card = action.closest('.source-card'); const operationInfo = state.adapters.find((item) => item.id === id)?.native?.operations?.find((item) => item.id === operation) || {}; let query = ''; if (operationInfo.requires_query) { query = window.prompt(operationInfo.description || 'Введите запрос к локальному инструменту:', ''); if (!query) return; } const confirmed = operationInfo.requires_confirmation === false || window.confirm(`${operationInfo.description || operation}\n\nБудет запущен внешний локальный процесс. CodeSlicer не отправляет код по сети, но сетевое поведение самого инструмента зависит от его конфигурации. Продолжить?`); if (!confirmed) return; action.disabled = true; const original = action.textContent; action.textContent = 'Выполняется…'; try { const result = await ImpactApi.nativeRun(id, { project_path: state.project, operation, query, confirmed: true }); const text = result.status === 'completed' ? `${id}: ${operation} выполнен локально.` : `${id}: ${result.status}. ${result.stderr || result.message || ''}`; showState(text, result.status === 'completed' ? '' : 'error-state'); if (card && (result.stdout || result.stderr)) card.append(el('pre', 'native-output', textOf(result.stdout || result.stderr).slice(-6000))); await loadSources(true); } catch (error) { showState(`${id}: ${error.message}`, 'error-state'); } finally { action.disabled = false; action.textContent = original; } }

document.addEventListener('keydown', (event) => { if (event.key === 'Escape') { closeOverlays(); return; } if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && $('#paletteInput')) { event.preventDefault(); openPalette(); return; } if (event.key === 'Enter' && event.target.matches('#inspectEntity')) openInspect(event.target.value.trim()); if (event.key === 'Enter' && event.target.matches('#investigateEntity')) loadInvestigation(event.target.value.trim()); const modalBackdrop = $('#modalBackdrop'); if (event.key === 'Tab' && modalBackdrop && !modalBackdrop.hidden) { const focusable = $$('button, input, select, textarea, [href]', $('#modal')).filter((item) => !item.disabled); if (!focusable.length) return; const first = focusable[0]; const last = focusable[focusable.length - 1]; if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); } } });
listen('#analyzeButton', 'click', () => startAnalysis($('#projectPath').value));
listen('#onboardingAnalyze', 'click', () => startAnalysis($('#onboardingPath').value));
listen('#cancelAnalyzeButton', 'click', cancelAnalysis);
listen('#graphProjectionButton', 'click', () => loadProjection(true));
listen('#mapRefresh', 'click', () => loadProjection(true));
listen('#graphZoomIn', 'click', () => activeGraphNavigator?.zoomIn());
listen('#graphZoomOut', 'click', () => activeGraphNavigator?.zoomOut());
listen('#graphResetView', 'click', () => activeGraphNavigator?.reset());
listen('#graphWorkspaceSource', 'change', (event) => { state.mapSource = event.target.value; loadProjection(true); });
listen('#graphViewSelect', 'change', (event) => {
  if (event.target.value === 'graphify') {
    // Keep Graphify's original interaction model intact rather than drawing
    // its artifact in CodeSlicer's simplified node-link projection.
    event.target.value = 'impact';
    navigate('graphify');
    return;
  }
  state.mapWorkspace = 'impact';
  state.mapSource = '';
  loadProjection(true);
});
listen('#onboardingPath', 'input', (event) => { $('#projectPath').value = event.target.value; });
window.addEventListener('hashchange', renderRoute);
window.addEventListener('resize', () => { if (window.innerWidth > 900) setMobileDrawer(false); });

async function bootstrap() {
  ensureInvestigationFilters();
  try {
    const [health, current] = await Promise.all([ImpactApi.health(), ImpactApi.state()]);
    if (health.status !== 'ok') throw new Error('local API не готов');
    state.apiCompatibility = health.capabilities?.managed_tools === true ? null : { managedTools: false, apiContract: health.api_contract_version || 'unknown' };
    const configuredProject = current.project_path || '';
    const projectAvailable = current.project_exists !== false;
    state.project = projectAvailable ? configuredProject : '';
    state.hasAnalysis = Boolean(current.has_analysis && projectAvailable);
    state.analysis = current.analysis || null;
    state.analyzedAt = current.analyzed_at || null;
    $('#projectPath').value = state.project;
    $('#onboardingPath').value = state.project;
    state.ready = true;
    if (!projectAvailable && configuredProject) {
      const message = `Папка проекта не найдена: ${configuredProject}. Укажите существующую папку.`;
      const errorTarget = $('#onboardingError');
      errorTarget.hidden = false;
      errorTarget.textContent = message;
      showState(message, 'error-state');
      if (location.hash !== '#review') location.hash = '#review';
      showOnboarding(true);
      return;
    }
    if (state.hasAnalysis) {
      await hydrateAnalysis();
      if (!location.hash) navigate('review'); else renderRoute();
      showState('Карта проекта готова.');
    } else {
      renderRoute();
      if (projectAvailable) showState(state.project ? 'Укажите путь и постройте карту.' : 'Укажите абсолютный путь к локальному проекту.');
    }
  } catch (error) {
    state.ready = true;
    renderRoute();
    showState(`Локальный API недоступен: ${error.message}`, 'error-state');
    const errorTarget = $('#onboardingError');
    errorTarget.hidden = false;
    errorTarget.textContent = 'Запустите impact-engine-local-api на localhost и повторите попытку.';
  }
}
const baseLoadSources = loadSources;
loadSources = async function toolAwareLoadSources(force = false) { await baseLoadSources(force); await loadTools(); if (state.route === 'sources') renderSources({}); };
const baseBootstrap = bootstrap;
bootstrap = async function toolAwareBootstrap() { await baseBootstrap(); await loadTools(); };
bootstrap();
