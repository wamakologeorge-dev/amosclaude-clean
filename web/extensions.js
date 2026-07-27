const BASE = '/api/v1/plugins/control-plane';
const state = { plugins: [], health: [], flags: [], servers: [] };
const byId = id => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function setNotice(message, type = '') {
  const node = byId('notice');
  node.textContent = message;
  node.className = `notice${type ? ` ${type}` : ''}`;
}

async function api(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, {
    credentials: 'same-origin',
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  let payload = null;
  try { payload = text ? JSON.parse(text) : null; } catch { payload = { detail: text }; }
  if (response.status === 401) {
    window.location.assign('/login');
    throw new Error('Administrator sign-in required');
  }
  if (!response.ok) {
    const detail = typeof payload?.detail === 'string'
      ? payload.detail
      : payload?.detail?.message || `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return payload;
}

function badge(status) {
  return `<span class="status ${escapeHtml(status)}">${escapeHtml(String(status).replaceAll('_', ' '))}</span>`;
}

function renderPlugins() {
  byId('metric-plugins').textContent = String(state.plugins.length);
  byId('metric-health').textContent = String(state.health.filter(item => item.status === 'ok').length);
  if (!state.plugins.length) {
    byId('plugin-list').innerHTML = '<p class="empty">No plugins loaded.</p>';
    return;
  }
  byId('plugin-list').innerHTML = state.plugins.map(plugin => {
    const contributions = plugin.contributions || {};
    const capabilities = (plugin.capabilities || []).map(item => `<li>${escapeHtml(item)}</li>`).join('');
    return `<article class="plugin-card">
      <header><div><p class="eyebrow">${escapeHtml(plugin.plugin_id)} · v${escapeHtml(plugin.version)}</p><h3>${escapeHtml(plugin.name)}</h3></div>${badge(plugin.status)}</header>
      <p class="muted">${escapeHtml(plugin.description || 'No description')}</p>
      <div class="meta">
        <div><span>Source</span><strong>${escapeHtml(plugin.source)}</strong></div>
        <div><span>Routers</span><strong>${Number(contributions.routers || 0)}</strong></div>
        <div><span>Agent tools</span><strong>${escapeHtml((contributions.agent_tools || []).join(', ') || 'none')}</strong></div>
        <div><span>Feature flags</span><strong>${Number(contributions.feature_flags || 0)}</strong></div>
      </div>
      ${capabilities ? `<ul class="capability-list">${capabilities}</ul>` : ''}
      ${plugin.error ? `<p class="error-text">${escapeHtml(plugin.error)}</p>` : ''}
    </article>`;
  }).join('');
}

function renderFlagOptions() {
  const options = state.flags.map(flag => `<option value="${escapeHtml(flag.key)}">${escapeHtml(flag.key)}</option>`).join('');
  byId('target-flag').innerHTML = options || '<option value="">No flags available</option>';
}

function renderFlags() {
  byId('metric-flags').textContent = String(state.flags.length);
  renderFlagOptions();
  if (!state.flags.length) {
    byId('flag-list').innerHTML = '<p class="empty">No flags registered.</p>';
    return;
  }
  byId('flag-list').innerHTML = state.flags.map(flag => {
    const targets = (flag.targets || []).map(target => `<li>${escapeHtml(target.target_type)}:${escapeHtml(target.target_value)}=${target.enabled ? 'on' : 'off'} <button type="button" data-action="delete-target" data-id="${target.id}" aria-label="Delete target">×</button></li>`).join('');
    return `<article class="flag-card">
      <header><div><p class="eyebrow">${escapeHtml(flag.owner_plugin)}</p><h3>${escapeHtml(flag.key)}</h3></div>${badge(flag.enabled ? 'operational' : 'disabled')}</header>
      <p>${escapeHtml(flag.name)}</p><p class="muted">${escapeHtml(flag.description || '')}</p>
      <div class="meta">
        <div><span>Global state</span><strong>${flag.enabled ? 'Enabled' : 'Disabled'}</strong></div>
        <div><span>Rollout</span><strong>${Number(flag.rollout_percentage || 0)}%</strong></div>
        <div><span>Eligible tiers</span><strong>${escapeHtml((flag.required_tiers || []).join(', ') || 'all')}</strong></div>
        <div><span>Updated</span><strong>${escapeHtml(flag.updated_at || '—')}</strong></div>
      </div>
      <ul class="target-list">${targets || '<li>No targeted overrides</li>'}</ul>
      <div class="actions"><button type="button" data-action="edit-flag" data-key="${escapeHtml(flag.key)}">Edit</button></div>
    </article>`;
  }).join('');
}

function renderServerOptions() {
  const options = state.servers.map(server => `<option value="${escapeHtml(server.id)}">${escapeHtml(server.name)} (${escapeHtml(server.id)})</option>`).join('');
  byId('scope-server').innerHTML = options || '<option value="">No servers available</option>';
}

function renderServers() {
  byId('metric-mcp').textContent = String(state.servers.length);
  renderServerOptions();
  if (!state.servers.length) {
    byId('mcp-list').innerHTML = '<p class="empty">No MCP servers registered.</p>';
    return;
  }
  byId('mcp-list').innerHTML = state.servers.map(server => {
    const scopes = (server.scopes || []).map(scope => `<li>${escapeHtml(scope.scope_type)}:${escapeHtml(scope.scope_value)} <button type="button" data-action="delete-scope" data-id="${scope.id}" aria-label="Delete scope">×</button></li>`).join('');
    return `<article class="mcp-card">
      <header><div><p class="eyebrow">${escapeHtml(server.id)}</p><h3>${escapeHtml(server.name)}</h3></div>${badge(server.enabled ? (server.last_probe_status || 'operational') : 'disabled')}</header>
      <p class="muted">${escapeHtml(server.description || '')}</p>
      <div class="meta">
        <div><span>Endpoint</span><strong>${escapeHtml(server.endpoint)}</strong></div>
        <div><span>Feature flag</span><strong>${escapeHtml(server.feature_flag_key)}</strong></div>
        <div><span>Credential</span><strong>${server.credential_configured ? 'Configured' : 'Not configured'}</strong></div>
        <div><span>Allowed tools</span><strong>${escapeHtml((server.allowed_tools || []).join(', ') || 'all')}</strong></div>
        <div><span>Last probe</span><strong>${escapeHtml(server.last_probe_status || 'never')}</strong></div>
        <div><span>Timeout</span><strong>${Number(server.timeout_seconds || 30)} seconds</strong></div>
      </div>
      <ul class="scope-list">${scopes || '<li>Available to every feature-eligible account</li>'}</ul>
      ${server.last_probe_detail ? `<p class="muted">${escapeHtml(server.last_probe_detail)}</p>` : ''}
      <div class="actions"><button type="button" data-action="probe" data-id="${escapeHtml(server.id)}">Probe tools/list</button><button type="button" data-action="edit-server" data-id="${escapeHtml(server.id)}">Edit</button></div>
    </article>`;
  }).join('');
}

async function loadAll({ quiet = false } = {}) {
  if (!quiet) setNotice('Loading plugin registry, flags, and MCP servers…');
  try {
    const [registry, health, flags, servers] = await Promise.all([
      api('/registry'), api('/registry/health'), api('/flags'), api('/mcp/servers/admin'),
    ]);
    state.plugins = registry.plugins || [];
    state.health = health || [];
    state.flags = flags || [];
    state.servers = servers || [];
    renderPlugins(); renderFlags(); renderServers();
    byId('updated').textContent = `Updated ${new Date().toLocaleTimeString()}`;
    if (!quiet) setNotice('Extension control plane is current.', 'success');
  } catch (error) {
    setNotice(error.message, 'error');
  }
}

byId('flag-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter; button.disabled = true;
  try {
    const key = byId('flag-key').value.trim();
    await api(`/flags/${encodeURIComponent(key)}`, {
      method: 'PUT', body: JSON.stringify({
        name: byId('flag-name').value.trim(),
        description: byId('flag-description').value.trim(),
        enabled: byId('flag-enabled').checked,
        rollout_percentage: Number(byId('flag-rollout').value),
        required_tiers: byId('flag-tiers').value.split(',').map(item => item.trim()).filter(Boolean),
        owner_plugin: 'admin',
      }),
    });
    event.target.reset(); byId('flag-rollout').value = '0';
    setNotice(`Feature flag ${key} saved.`, 'success'); await loadAll({ quiet: true });
  } catch (error) { setNotice(error.message, 'error'); } finally { button.disabled = false; }
});

byId('target-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try {
    await api(`/flags/${encodeURIComponent(byId('target-flag').value)}/targets`, {
      method: 'POST', body: JSON.stringify({ target_type: byId('target-type').value, target_value: byId('target-value').value.trim(), enabled: byId('target-enabled').checked }),
    });
    byId('target-value').value = ''; setNotice('Targeted flag override saved.', 'success'); await loadAll({ quiet: true });
  } catch (error) { setNotice(error.message, 'error'); } finally { button.disabled = false; }
});

byId('flag-list').addEventListener('click', async event => {
  const button = event.target.closest('button[data-action]'); if (!button) return;
  if (button.dataset.action === 'edit-flag') {
    const flag = state.flags.find(item => item.key === button.dataset.key); if (!flag) return;
    byId('flag-key').value = flag.key; byId('flag-name').value = flag.name; byId('flag-description').value = flag.description || ''; byId('flag-enabled').checked = flag.enabled; byId('flag-rollout').value = String(flag.rollout_percentage || 0); byId('flag-tiers').value = (flag.required_tiers || []).join(', '); byId('flag-form').scrollIntoView({ behavior: 'smooth' }); return;
  }
  button.disabled = true;
  try { await api(`/flags/targets/${button.dataset.id}`, { method: 'DELETE' }); setNotice('Flag target removed.', 'success'); await loadAll({ quiet: true }); }
  catch (error) { setNotice(error.message, 'error'); } finally { button.disabled = false; }
});

byId('mcp-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try {
    const id = byId('mcp-id').value.trim();
    const tools = byId('mcp-tools').value.split(/[\n,]/).map(item => item.trim()).filter(Boolean);
    await api(`/mcp/servers/${encodeURIComponent(id)}`, {
      method: 'PUT', body: JSON.stringify({
        name: byId('mcp-name').value.trim(), description: byId('mcp-description').value.trim(), endpoint: byId('mcp-endpoint').value.trim(), auth_header_name: byId('mcp-header').value.trim() || null, auth_secret_env: byId('mcp-secret-env').value.trim() || null, enabled: byId('mcp-enabled').checked, feature_flag_key: byId('mcp-flag').value.trim(), allowed_tools: tools, timeout_seconds: Number(byId('mcp-timeout').value),
      }),
    });
    event.target.reset(); byId('mcp-flag').value = 'mcp.integrations'; byId('mcp-timeout').value = '30';
    setNotice(`MCP server ${id} saved.`, 'success'); await loadAll({ quiet: true });
  } catch (error) { setNotice(error.message, 'error'); } finally { button.disabled = false; }
});

byId('mcp-scope-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try {
    await api(`/mcp/servers/${encodeURIComponent(byId('scope-server').value)}/scopes`, { method: 'POST', body: JSON.stringify({ scope_type: byId('scope-type').value, scope_value: byId('scope-value').value.trim() }) });
    byId('scope-value').value = ''; setNotice('MCP scope assigned.', 'success'); await loadAll({ quiet: true });
  } catch (error) { setNotice(error.message, 'error'); } finally { button.disabled = false; }
});

byId('mcp-list').addEventListener('click', async event => {
  const button = event.target.closest('button[data-action]'); if (!button) return;
  if (button.dataset.action === 'edit-server') {
    const server = state.servers.find(item => item.id === button.dataset.id); if (!server) return;
    byId('mcp-id').value = server.id; byId('mcp-name').value = server.name; byId('mcp-description').value = server.description || ''; byId('mcp-endpoint').value = server.endpoint; byId('mcp-header').value = server.auth_header_name || ''; byId('mcp-secret-env').value = server.auth_secret_env || ''; byId('mcp-enabled').checked = server.enabled; byId('mcp-flag').value = server.feature_flag_key; byId('mcp-tools').value = (server.allowed_tools || []).join('\n'); byId('mcp-timeout').value = String(server.timeout_seconds || 30); byId('mcp-form').scrollIntoView({ behavior: 'smooth' }); return;
  }
  button.disabled = true;
  try {
    if (button.dataset.action === 'probe') { const result = await api(`/mcp/servers/${encodeURIComponent(button.dataset.id)}/probe`, { method: 'POST' }); setNotice(`${button.dataset.id}: ${result.detail}`, result.status === 'operational' ? 'success' : 'error'); }
    if (button.dataset.action === 'delete-scope') { await api(`/mcp/scopes/${button.dataset.id}`, { method: 'DELETE' }); setNotice('MCP scope removed.', 'success'); }
    await loadAll({ quiet: true });
  } catch (error) { setNotice(error.message, 'error'); } finally { button.disabled = false; }
});

byId('refresh').addEventListener('click', () => loadAll());
await loadAll();
window.setInterval(() => loadAll({ quiet: true }), 30000);
