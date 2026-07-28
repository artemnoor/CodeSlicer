/* Same-origin client for the local-only CodeSlicer API. */
(function (global) {
  let sessionToken = null;
  async function request(path, options) {
    // All requests are deliberately relative: the local API and this SPA
    // share an origin, and the UI never sends source data to another host.
    const response = await fetch(path, { cache: 'no-store', credentials: 'same-origin', ...options });
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
  global.ImpactApi = {
    state: () => request('/api/state'),
    graph: () => request('/api/graph'),
    health: () => request('/api/health'),
    adapters: () => request('/api/adapters'),
    graphifyViewerStatus: () => request('/api/adapters/graphify/viewer/status'),
    tools: () => request('/api/tools'),
    toolCatalog: (payload) => post('/api/tools', payload),
    toolConnect: (id, payload) => post(`/api/tools/${encodeURIComponent(id)}/connect`, payload),
    toolExecutable: (id, payload) => post(`/api/tools/${encodeURIComponent(id)}/executable`, payload),
    toolDocs: (id, payload) => post(`/api/tools/${encodeURIComponent(id)}/docs`, payload),
    toolDocument: (id, payload) => post(`/api/tools/${encodeURIComponent(id)}/document`, payload),
    toolHelp: (id, payload) => post(`/api/tools/${encodeURIComponent(id)}/help`, payload),
    toolRun: (id, payload) => post(`/api/tools/${encodeURIComponent(id)}/run`, payload),
    adapterEnable: (id, payload) => post(`/api/adapters/${encodeURIComponent(id)}/enable`, payload),
    adapterDisable: (id, payload) => post(`/api/adapters/${encodeURIComponent(id)}/disable`, payload),
    adapterImport: (id, payload) => post(`/api/adapters/${encodeURIComponent(id)}/import`, payload),
    nativeProfile: (id, payload) => post(`/api/adapters/${encodeURIComponent(id)}/native-profile`, payload),
    nativeConfigure: (id, payload) => post(`/api/adapters/${encodeURIComponent(id)}/native-config`, payload),
    nativeRun: (id, payload) => post(`/api/adapters/${encodeURIComponent(id)}/native-run`, payload),
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
    lspProbe: (payload) => post('/api/adapters/lsp/probe', payload),
    lspDisable: (payload) => post('/api/adapters/lsp/disable', payload),
    lspQuery: (payload) => post('/api/adapters/lsp/query', payload),
    progress: () => request('/api/progress'),
    overview: () => request('/api/overview'),
    inventory: () => request('/api/inventory'),
    graphProjection: (payload) => post('/api/graph/projection', payload),
    graphWorkspace: (payload) => post('/api/graph-workspace', payload),
    analyze: (project_path) => post('/api/analyze', { project_path }),
    cancelAnalyze: () => post('/api/analyze/cancel', {}),
    review: post.bind(null, '/api/review'),
    inspect: post.bind(null, '/api/inspect'),
    investigate: post.bind(null, '/api/investigate'),
    ci: post.bind(null, '/api/ci'),
    reviewRunTest: (payload) => post('/api/review/run-test', payload),
    reviewFeedback: (payload) => post('/api/review/feedback', payload),
    reviewHistory: (payload) => post('/api/review/history', payload),
  };
})(window);
