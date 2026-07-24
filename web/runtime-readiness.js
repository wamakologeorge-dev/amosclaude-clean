(() => {
  const connectionButton = document.getElementById('btn-check-agent-connections');
  const connectionStatus = document.getElementById('agent-connection-status');
  const statusBadge = document.getElementById('agent-status');

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  async function read(path) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      cache: 'no-store',
    });
    const raw = await response.text();
    let payload = {};
    try {
      payload = raw ? JSON.parse(raw) : {};
    } catch {
      payload = { detail: raw || `Invalid response from ${path}` };
    }
    if (!response.ok) {
      throw new Error(payload.detail || `Request failed (${response.status})`);
    }
    return payload;
  }

  function renderContext(context = {}) {
    setText(
      'active-workspace-name',
      context.workspace_id || context.workspace_name || 'Personal workspace',
    );
    setText(
      'active-repository-name',
      context.repository_name || 'No repository selected',
    );
    setText('active-branch-name', context.branch || 'main');
    setText(
      'active-owner-authorization',
      context.owner_authorized || context.role === 'owner'
        ? 'Owner verified'
        : context.role
          ? `${context.role} permission`
          : 'Signed-in session',
    );
  }

  function setBadge(label, failed = false) {
    if (!statusBadge) return;
    statusBadge.textContent = label;
    statusBadge.className = `badge ${failed ? 'badge-failed' : 'badge-success'}`;
  }

  async function checkRuntime() {
    if (connectionButton) connectionButton.disabled = true;
    if (connectionStatus) {
      connectionStatus.textContent = 'Checking repository, GitHub, server, and execution model…';
    }

    try {
      const [health, agent, context, github, model] = await Promise.all([
        read('/health'),
        read('/api/v1/agent'),
        read('/api/v1/core/os/context'),
        read('/api/v1/github/status'),
        read('/api/v1/amomodel/model/status'),
      ]);
      renderContext(context);

      const blockers = [];
      if (!context.active || !context.repository_id) {
        blockers.push('no repository is imported and selected');
      }
      if (!model.available) {
        blockers.push(model.required_action || 'no execution model is configured');
      }
      if (!github.connected) {
        blockers.push('GitHub is not connected');
      }

      if (blockers.length) {
        setBadge('blocked', true);
        if (connectionStatus) {
          connectionStatus.textContent = `Autonomous blocker: ${blockers.join('; ')}.`;
        }
        return;
      }

      setBadge('ready');
      if (connectionStatus) {
        connectionStatus.textContent = [
          `${agent.name || 'Amosclaud Autonomous Agent'} is online.`,
          `Server: ${health.status || 'ok'}.`,
          `Repository: ${context.repository_name}@${context.branch || 'main'}.`,
          `Model: ${model.provider || 'amosclaud'} / ${model.model || 'configured'}.`,
          `GitHub: @${github.connection?.github_login || 'connected'}.`,
        ].join(' ');
      }
    } catch (error) {
      setBadge('error', true);
      if (connectionStatus) {
        connectionStatus.textContent = `Platform needs attention: ${error.message}`;
      }
      renderContext({});
    } finally {
      if (connectionButton) connectionButton.disabled = false;
    }
  }

  connectionButton?.addEventListener(
    'click',
    event => {
      event.preventDefault();
      event.stopImmediatePropagation();
      checkRuntime();
    },
    true,
  );

  window.addEventListener('amosclaud:project-context', event => {
    renderContext(event.detail || {});
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', checkRuntime, { once: true });
  } else {
    checkRuntime();
  }
})();
