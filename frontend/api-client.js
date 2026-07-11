/* Thin client for the local Impact Engine HTTP API. */
(function (global) {
  async function request(path, options) {
    const response = await fetch(path, { cache: 'no-store', ...options });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `${response.status} ${response.statusText}`);
    return data;
  }

  global.ImpactApi = {
    state: () => request('/api/state'),
    graph: () => request('/api/graph'),
    analyze: (projectPath) => request('/api/analyze', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_path: projectPath }),
    }),
    impact: (payload) => request('/api/impact', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
    query: (payload) => request('/api/query', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  };
})(window);
