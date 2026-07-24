(() => {
  const nativeFetch = window.fetch.bind(window);
  const CONTEXT_KEY = 'amosclaud.activeProjectContext';

  function isAgentRun(input) {
    const url = typeof input === 'string' ? input : input?.url || '';
    return url.includes('/api/v1/agent/run');
  }

  function readStoredContext() {
    try {
      return JSON.parse(window.localStorage.getItem(CONTEXT_KEY) || '{}');
    } catch (_error) {
      return {};
    }
  }

  function storeContext(context) {
    window.localStorage.setItem(CONTEXT_KEY, JSON.stringify(context));
    window.dispatchEvent(new CustomEvent('amosclaud:project-context', { detail: context }));
  }

  async function loadCollection(url) {
    try {
      const response = await nativeFetch(url, { credentials: 'same-origin' });
      if (!response.ok) return [];
      const payload = await response.json();
      return Array.isArray(payload) ? payload : payload.items || payload.repositories || payload.workspaces || [];
    } catch (_error) {
      return [];
    }
  }

  async function loadOperatorMemory() {
    try {
      const response = await nativeFetch('/api/v1/core/os/operator', { credentials: 'same-origin' });
      if (!response.ok) return {};
      const payload = await response.json();
      return payload.agent_metadata || {};
    } catch (_error) {
      return {};
    }
  }

  async function loadServerContext() {
    try {
      const response = await nativeFetch('/api/v1/core/os/context', { credentials: 'same-origin' });
      if (!response.ok) return null;
      const payload = await response.json();
      if (!payload.active) return null;
      return {
        workspace_id: payload.workspace_id || null,
        workspace_name: payload.workspace_id || 'Personal workspace',
        repository_id: payload.repository_id || null,
        repository_name: payload.repository_name || null,
        selected_workspace: payload.workspace_id || 'Personal workspace',
        selected_repository: payload.repository_name || null,
        branch: payload.branch || 'main',
        repository_role: payload.role || null,
        owner_authorization: payload.owner_authorized ? 'session-owner' : payload.role || 'session',
        owner_authorized: Boolean(payload.owner_authorized),
        repository_provider: payload.provider || 'native',
        project_context_source: 'amosclaud-os',
      };
    } catch (_error) {
      return null;
    }
  }

  async function persistServerContext(context) {
    if (!context.repository_id) return;
    try {
      await nativeFetch('/api/v1/core/os/context', {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repository_id: context.repository_id,
          workspace_id: context.workspace_id || null,
          branch: context.branch || 'main',
        }),
      });
    } catch (_error) {
      // Local context remains available when the backend is temporarily unreachable.
    }
  }

  async function resolveProjectContext() {
    const serverContext = await loadServerContext();
    if (serverContext) {
      storeContext(serverContext);
      return serverContext;
    }

    const stored = readStoredContext();
    const repositories = stored.repository_id ? [] : await loadCollection('/api/v1/repositories');
    const workspaces = stored.workspace_id ? [] : await loadCollection('/api/v1/workspaces');
    const repository = repositories.find((item) => item.id === stored.repository_id) || repositories[0] || null;
    const workspace = workspaces.find((item) => item.id === stored.workspace_id) || workspaces[0] || null;
    const context = {
      workspace_id: stored.workspace_id || workspace?.id || null,
      workspace_name: stored.workspace_name || workspace?.name || 'Personal workspace',
      repository_id: stored.repository_id || repository?.id || null,
      repository_name: stored.repository_name || repository?.name || null,
      selected_workspace: stored.selected_workspace || workspace?.name || 'Personal workspace',
      selected_repository: stored.selected_repository || repository?.name || null,
      branch: stored.branch || workspace?.branch || repository?.default_branch || 'main',
      repository_role: stored.repository_role || repository?.role || null,
      owner_authorization: stored.owner_authorization || (repository?.role === 'owner' ? 'session-owner' : 'session'),
      owner_authorized: stored.owner_authorization === 'session-owner' || repository?.role === 'owner',
      repository_provider: stored.repository_provider || 'native',
      project_context_source: 'amosclaud-os',
    };
    storeContext(context);
    await persistServerContext(context);
    return context;
  }

  function classifyCommand(objective) {
    const text = String(objective || '').toLowerCase();
    const repairRequested = /\b(fix|repair|broken|failure|failing|error|bug|regression)\b/.test(text);
    const diagnoseRequested = /\b(inspect|diagnose|doctor|health|audit|analyze|analyse|investigate)\b/.test(text);
    const testRequested = /\b(test|ci|verify|check|lint|build check|big ci)\b/.test(text);
    const releaseRequested = /\b(deploy|publish|release|ship|package)\b/.test(text);
    const issueRequested = /\b(issue|issues|ticket|tickets)\b/.test(text);
    const writeRequested = /\b(build|create|implement|change|edit|write|move|rename|delete|commit|merge|branch|file|folder|repository|issue)\b/.test(text);
    const actionRequested = repairRequested || diagnoseRequested || testRequested || releaseRequested || writeRequested;

    let mode = 'autonomous-check';
    if (repairRequested) mode = 'fix';
    else if (releaseRequested) mode = 'deploy';
    else if (testRequested) mode = 'test';
    else if (writeRequested) mode = 'build';
    else if (diagnoseRequested) mode = 'inspect';

    return { mode, actionRequested, repairRequested, diagnoseRequested, testRequested, releaseRequested, issueRequested, writeRequested };
  }

  function issueDetails(objective, command) {
    if (!command.issueRequested) return {};
    const cleaned = String(objective || '')
      .replace(/^@?amosclaud\s*/i, '')
      .replace(/\b(create|open|add|new)\b/gi, '')
      .replace(/\b(an?|the)?\s*issues?\b/gi, '')
      .replace(/\s+/g, ' ')
      .trim();
    return {
      issue_title: cleaned ? cleaned.slice(0, 120) : null,
      issue_description: String(objective || '').trim(),
      operation: 'create_issue',
    };
  }

  function authorizeObjective(objective, command, context) {
    const original = String(objective || '').trim();
    if (!command.actionRequested) return original;
    if (/\b(do not|don't|show only|explain only|in chat only)\b/i.test(original)) return original;
    const target = context.repository_name ? ` in the selected repository ${context.repository_name}` : '';
    return `${original}. Execute this action now${target} as an authorized engineering command. Make the requested real changes, use the signed-in owner's authorization, run the required checks, and verify the final result.`;
  }

  window.AmosclaudProjectContext = {
    get: readStoredContext,
    set: async (next) => {
      const context = { ...readStoredContext(), ...next };
      storeContext(context);
      await persistServerContext(context);
      return context;
    },
    refresh: resolveProjectContext,
  };

  window.fetch = async (input, init = {}) => {
    if (!isAgentRun(input) || String(init.method || 'GET').toUpperCase() !== 'POST' || !init.body) {
      return nativeFetch(input, init);
    }

    try {
      const payload = JSON.parse(init.body);
      const originalObjective = String(payload.objective || '').trim();
      const command = classifyCommand(originalObjective);
      const [context, operatorMemory] = await Promise.all([
        resolveProjectContext(),
        loadOperatorMemory(),
      ]);
      const {
        actionRequested,
        repairRequested,
        diagnoseRequested,
        testRequested,
        releaseRequested,
        writeRequested,
      } = command;
      payload.objective = authorizeObjective(originalObjective, command, context);
      payload.mode = command.mode;
      payload.branch = context.branch || payload.branch || 'main';
      payload.metadata = {
        ...(payload.metadata || {}),
        ...operatorMemory,
        ...context,
        ...issueDetails(originalObjective, command),
        original_objective: originalObjective,
        original_follow_up: payload.objective,
        source: 'amosclaud-platform-unified-operator',
        operator: 'amosclaud-bot',
        planner: 'codex-style',
        execution_engine: 'amosclaud-autonomous',
        doctor_engine: 'amosclaud-doctor',
        repair_engine: 'amosclaud-fixer',
        command_pipeline: ['receive', 'resolve-context', 'remember-plan', 'authorize', 'inspect', 'diagnose', 'plan', 'act', 'test', 'fix', 'verify', 'report'],
        unified_agent_identity: true,
        autonomous_runtime: true,
        autonomous_mode_selection: true,
        use_agent: actionRequested,
        apply_changes: actionRequested,
        run_doctor: diagnoseRequested || repairRequested || testRequested,
        run_tests: testRequested || repairRequested || writeRequested,
        run_fixer: repairRequested,
        require_owner_permission: writeRequested || repairRequested || releaseRequested,
        require_verification: true,
        return_evidence: true,
        bypass_explain_or_edit_loop: actionRequested,
      };

      return nativeFetch(input, { ...init, body: JSON.stringify(payload) });
    } catch (_error) {
      return nativeFetch(input, init);
    }
  };

  resolveProjectContext();
})();
