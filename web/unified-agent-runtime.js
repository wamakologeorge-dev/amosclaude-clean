(() => {
  const nativeFetch = window.fetch.bind(window);

  function isAgentRun(input) {
    const url = typeof input === 'string' ? input : input?.url || '';
    return url.includes('/api/v1/agent/run');
  }

  window.fetch = async (input, init = {}) => {
    if (!isAgentRun(input) || String(init.method || 'GET').toUpperCase() !== 'POST' || !init.body) {
      return nativeFetch(input, init);
    }

    try {
      const payload = JSON.parse(init.body);
      const objective = String(payload.objective || '').toLowerCase();
      const actionRequested = /\b(build|create|fix|repair|change|edit|test|run|deploy|publish|release|commit|implement)\b/.test(objective);
      const repairRequested = /\b(fix|repair|error|failure|broken|failing)\b/.test(objective);

      payload.mode = repairRequested ? 'fix' : actionRequested ? 'build' : (payload.mode || 'autonomous-check');
      payload.metadata = {
        ...(payload.metadata || {}),
        source: 'amosclaud-platform-unified-operator',
        operator: 'amosclaud-bot',
        planner: 'codex-style',
        repair_engine: 'amosclaud-fixer',
        autonomous_runtime: true,
        autonomous_mode_selection: true,
        use_agent: actionRequested,
        apply_changes: actionRequested,
        require_verification: true,
        return_evidence: true,
      };

      return nativeFetch(input, { ...init, body: JSON.stringify(payload) });
    } catch (_error) {
      return nativeFetch(input, init);
    }
  };
})();
