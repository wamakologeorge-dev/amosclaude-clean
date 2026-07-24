(() => {
  const originalFetch = window.fetch.bind(window);
  const allowedModes = new Set(['ask', 'build', 'fix', 'test', 'review', 'deploy', 'monitor']);

  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input?.url || '';
    const method = String(init.method || 'GET').toUpperCase();
    if (url !== '/api/v1/agent/run' || method !== 'POST') return originalFetch(input, init);

    let body = {};
    try { body = JSON.parse(init.body || '{}'); } catch { return originalFetch(input, init); }

    const source = body?.metadata?.source || '';
    if (!String(source).includes('repository')) return originalFetch(input, init);

    const repoLabel = document.getElementById('ws-repo-name')?.textContent?.trim();
    const inferredMode = allowedModes.has(body.mode)
      ? body.mode
      : (/review/i.test(body.objective || '') ? 'review' : /test/i.test(body.objective || '') ? 'test' : undefined);

    const operatorBody = {
      objective: body.objective,
      repository: repoLabel && repoLabel.includes('/') ? repoLabel : null,
      mode: inferredMode,
      require_approval: true,
      source: 'amosclaud-platform-repository',
      metadata: {
        ...(body.metadata || {}),
        branch: body.branch,
        legacy_endpoint: '/api/v1/agent/run'
      }
    };

    return originalFetch('/api/v1/operator/requests', {
      ...init,
      body: JSON.stringify(operatorBody),
      headers: {
        'Content-Type': 'application/json',
        ...(init.headers || {})
      }
    });
  };
})();
