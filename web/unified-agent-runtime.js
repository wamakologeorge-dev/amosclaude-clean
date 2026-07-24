(() => {
  const nativeFetch = window.fetch.bind(window);

  function isAgentRun(input) {
    const url = typeof input === 'string' ? input : input?.url || '';
    return url.includes('/api/v1/agent/run');
  }

  function classifyCommand(objective) {
    const text = String(objective || '').toLowerCase();
    const repairRequested = /\b(fix|repair|broken|failure|failing|error|bug|regression)\b/.test(text);
    const diagnoseRequested = /\b(inspect|diagnose|doctor|health|audit|analyze|analyse|investigate)\b/.test(text);
    const testRequested = /\b(test|ci|verify|check|lint|build check|big ci)\b/.test(text);
    const releaseRequested = /\b(deploy|publish|release|ship|package)\b/.test(text);
    const writeRequested = /\b(build|create|implement|change|edit|write|move|rename|delete|commit|merge|branch|file|folder|repository|issue)\b/.test(text);
    const actionRequested = repairRequested || diagnoseRequested || testRequested || releaseRequested || writeRequested;

    let mode = 'autonomous-check';
    if (repairRequested) mode = 'fix';
    else if (releaseRequested) mode = 'deploy';
    else if (testRequested) mode = 'test';
    else if (writeRequested) mode = 'build';
    else if (diagnoseRequested) mode = 'inspect';

    return { mode, actionRequested, repairRequested, diagnoseRequested, testRequested, releaseRequested, writeRequested };
  }

  function authorizeObjective(objective, command) {
    const original = String(objective || '').trim();
    if (!command.actionRequested) return original;
    if (/\b(do not|don't|show only|explain only|in chat only)\b/i.test(original)) return original;
    if (/\b(make the changes|edit the repository|apply the fix|do it|proceed|run the tests|deploy it)\b/i.test(original)) return original;
    return `${original}. Make the requested real changes, run the required checks, and verify the result.`;
  }

  window.fetch = async (input, init = {}) => {
    if (!isAgentRun(input) || String(init.method || 'GET').toUpperCase() !== 'POST' || !init.body) {
      return nativeFetch(input, init);
    }

    try {
      const payload = JSON.parse(init.body);
      const originalObjective = String(payload.objective || '').trim();
      const command = classifyCommand(originalObjective);
      payload.objective = authorizeObjective(originalObjective, command);
      payload.mode = command.mode;
      payload.metadata = {
        ...(payload.metadata || {}),
        original_objective: originalObjective,
        original_follow_up: payload.objective,
        source: 'amosclaud-platform-command-agent',
        operator: 'amosclaud-bot',
        planner: 'amosclaud-autonomous',
        doctor_engine: 'amosclaud-doctor',
        repair_engine: 'amosclaud-fixer',
        command_pipeline: ['receive', 'inspect', 'diagnose', 'plan', 'act', 'test', 'fix', 'verify', 'report'],
        unified_agent_identity: true,
        autonomous_runtime: true,
        autonomous_mode_selection: true,
        use_agent: command.actionRequested,
        apply_changes: command.writeRequested || command.repairRequested || command.releaseRequested,
        run_doctor: command.diagnoseRequested || command.repairRequested || command.testRequested,
        run_tests: command.testRequested || command.repairRequested || command.writeRequested,
        run_fixer: command.repairRequested,
        require_owner_permission: command.writeRequested || command.repairRequested || command.releaseRequested,
        require_verification: true,
        return_evidence: true,
      };

      return nativeFetch(input, { ...init, body: JSON.stringify(payload) });
    } catch (_error) {
      return nativeFetch(input, init);
    }
  };
})();
