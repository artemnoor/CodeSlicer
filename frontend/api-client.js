/* Same-origin client for the local-only CodeSlicer API. */
(function (global) {
  let sessionToken = null;
  async function request(path, options) {
    // All requests are deliberately relative: the local API and this SPA
    // share an origin, and the UI never sends source data to another host.
    const response = await fetch(path, { cache: 'no-store', credentials: 'same-origin', ...options, headers: { ...(options?.headers || {}) } });
    const text = await response.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { error: text }; }
    if (path === '/api/health' && data.session_token) sessionToken = data.session_token;
    if (!response.ok) {
      const detail = data.error || data.message || data.status;
      const error = new Error(detail || `${response.status} ${response.statusText}`);
      error.status = response.status;
      error.payload = data;
      throw error;
    }
    return data;
  }
  const post = (path, payload) => request(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...(sessionToken ? { 'X-CodeSlicer-Session': sessionToken } : {}) }, body: JSON.stringify(payload || {}),
  });
  function requestApprovalToken(pending) {
    return new Promise((resolve) => {
      const approval = pending.approval || {}, details = approval.payload || {};
      const dialog = document.createElement('dialog');
      dialog.className = 'approval-dialog';
      dialog.innerHTML = `<form method="dialog"><h2>Нужно локальное подтверждение</h2><dl><dt>Action</dt><dd></dd><dt>Expires</dt><dd></dd><dt>Exact payload</dt><dd><pre></pre></dd></dl><p>Проверьте параметры, выполните локальную команду и вставьте только выданный одноразовый токен.</p><code></code><label>approval_token<input autocomplete="off" required></label><menu><button value="cancel">Отмена</button><button value="confirm">Повторить действие</button></menu></form>`;
      const values = dialog.querySelectorAll('dd');
      values[0].textContent = approval.action || 'external action';
      values[1].textContent = approval.expires_at || 'unknown';
      dialog.querySelector('pre').textContent = JSON.stringify(details, null, 2);
      dialog.querySelector('code').textContent = pending.next_step || pending.message || '';
      document.body.append(dialog);
      dialog.addEventListener('close', () => { const token = dialog.returnValue === 'confirm' ? dialog.querySelector('input').value.trim() : ''; dialog.remove(); resolve(token); });
      dialog.showModal();
    });
  }
  async function executeApprovedAction(callback, payload) {
    const exactPayload = Object.freeze({ ...(payload || {}) });
    try {
      return await callback(exactPayload);
    } catch (error) {
      const pending = error && error.status === 409 && error.payload && error.payload.status === 'pending_approval' ? error.payload : null;
      if (!pending) throw error;
      // A real host approval is still required. This small local dialog keeps
      // the exact original payload immutable and makes the retry path usable
      // in every existing action without granting browser-side approval.
      const token = await requestApprovalToken(pending);
      if (!token) throw error;
      const approvalId = pending.approval?.approval_id;
      if (!approvalId) throw error;
      return callback({ ...exactPayload, approval_id: approvalId, approval_token: token });
    }
  }
  const approvedPost = (path, payload) => executeApprovedAction((exact) => post(path, exact), payload);
  global.ImpactApi = {
    state: () => request('/api/state'),
    graph: () => request('/api/graph'),
    health: () => request('/api/health'),
    adapters: () => request('/api/adapters'),
    graphifyViewerStatus: () => request('/api/adapters/graphify/viewer/status'),
    tools: () => request('/api/tools'),
    toolCatalog: (payload) => post('/api/tools', payload),
    toolConnect: (id, payload) => approvedPost(`/api/tools/${encodeURIComponent(id)}/connect`, payload),
    toolExecutable: (id, payload) => post(`/api/tools/${encodeURIComponent(id)}/executable`, payload),
    toolDocs: (id, payload) => post(`/api/tools/${encodeURIComponent(id)}/docs`, payload),
    toolDocument: (id, payload) => post(`/api/tools/${encodeURIComponent(id)}/document`, payload),
    toolHelp: (id, payload) => approvedPost(`/api/tools/${encodeURIComponent(id)}/help`, payload),
    toolRun: (id, payload) => approvedPost(`/api/tools/${encodeURIComponent(id)}/run`, payload),
    adapterEnable: (id, payload) => post(`/api/adapters/${encodeURIComponent(id)}/enable`, payload),
    adapterDisable: (id, payload) => post(`/api/adapters/${encodeURIComponent(id)}/disable`, payload),
    adapterImport: (id, payload) => post(`/api/adapters/${encodeURIComponent(id)}/import`, payload),
    nativeProfile: (id, payload) => post(`/api/adapters/${encodeURIComponent(id)}/native-profile`, payload),
    nativeConfigure: (id, payload) => post(`/api/adapters/${encodeURIComponent(id)}/native-config`, payload),
    nativeRun: (id, payload) => approvedPost(`/api/adapters/${encodeURIComponent(id)}/native-run`, payload),
    architecture: (payload) => post('/api/architecture', payload),
    graphifyEnable: (payload) => post('/api/adapters/graphify/enable', payload),
    graphifyDisable: (payload) => post('/api/adapters/graphify/disable', payload),
    graphifyImport: (payload) => post('/api/adapters/graphify/import', payload),
    codegraphEnable: (payload) => post('/api/adapters/codegraph/enable', payload),
    codegraphDisable: (payload) => post('/api/adapters/codegraph/disable', payload),
    codegraphImport: (payload) => post('/api/adapters/codegraph/import', payload),
    scipEnable: (payload) => post('/api/adapters/scip/enable', payload),
    scipDisable: (payload) => post('/api/adapters/scip/disable', payload),
    scipImport: (payload) => post('/api/adapters/scip/import', payload),
    openapiEnable: (payload) => post('/api/adapters/openapi/enable', payload),
    openapiDisable: (payload) => post('/api/adapters/openapi/disable', payload),
    openapiImport: (payload) => post('/api/adapters/openapi/import', payload),
    asyncapiEnable: (payload) => post('/api/adapters/asyncapi/enable', payload),
    asyncapiDisable: (payload) => post('/api/adapters/asyncapi/disable', payload),
    asyncapiImport: (payload) => post('/api/adapters/asyncapi/import', payload),
    otelEnable: (payload) => post('/api/adapters/otel/enable', payload),
    otelDisable: (payload) => post('/api/adapters/otel/disable', payload),
    otelImport: (payload) => post('/api/adapters/otel/import', payload),
    otelLiveEnable: (payload) => post('/api/adapters/otel/live-enable', payload),
    otelLiveDisable: (payload) => post('/api/adapters/otel/live-disable', payload),
    otelLiveStatus: (payload) => post('/api/adapters/otel/live-status', payload),
    cyclonedxEnable: (payload) => post('/api/adapters/cyclonedx/enable', payload),
    cyclonedxDisable: (payload) => post('/api/adapters/cyclonedx/disable', payload),
    cyclonedxImport: (payload) => post('/api/adapters/cyclonedx/import', payload),
    spdxEnable: (payload) => post('/api/adapters/spdx/enable', payload),
    spdxDisable: (payload) => post('/api/adapters/spdx/disable', payload),
    spdxImport: (payload) => post('/api/adapters/spdx/import', payload),
    sarifEnable: (payload) => post('/api/adapters/sarif/enable', payload),
    sarifDisable: (payload) => post('/api/adapters/sarif/disable', payload),
    sarifImport: (payload) => post('/api/adapters/sarif/import', payload),
    lspStatus: () => request('/api/adapters/lsp/status'),
    lspConfigure: (payload) => post('/api/adapters/lsp/configure', payload),
    lspPreflight: (payload) => post('/api/adapters/lsp/preflight', payload),
    lspProbe: (payload) => approvedPost('/api/adapters/lsp/probe', payload),
    lspDisable: (payload) => post('/api/adapters/lsp/disable', payload),
    lspQuery: (payload) => approvedPost('/api/adapters/lsp/query', payload),
    progress: () => request('/api/progress'),
    overview: () => request('/api/overview'),
    inventory: () => request('/api/inventory'),
    graphProjection: (payload) => post('/api/graph/projection', payload),
    graphWorkspace: (payload) => post('/api/graph-workspace', payload),
    analyze: (project_path) => post('/api/analyze', { project_path }),
    cancelAnalyze: () => post('/api/analyze/cancel', {}),
    review: post.bind(null, '/api/review'),
    inspect: post.bind(null, '/api/inspect'),
    investigate: (payload) => approvedPost('/api/investigate', payload),
    ci: (payload) => approvedPost('/api/ci', payload),
    reviewRunTest: (payload) => approvedPost('/api/review/run-test', payload),
    reviewFeedback: (payload) => post('/api/review/feedback', payload),
    reviewHistory: (payload) => post('/api/review/history', payload),
  };
  global.ImpactApi.executeApprovedAction = executeApprovedAction;
})(window);
