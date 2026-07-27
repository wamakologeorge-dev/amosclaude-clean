const state = {
  overview: null,
  repositories: [],
  loading: false,
};

const byId = id => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function formatNumber(value, fallback = '—') {
  return value === null || value === undefined ? fallback : Number(value).toLocaleString();
}

function formatUsd(value) {
  return value === null || value === undefined
    ? '—'
    : Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
}

function setNotice(message, type = '') {
  const node = byId('notice');
  node.textContent = message;
  node.className = `notice${type ? ` ${type}` : ''}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { detail: text };
  }
  if (response.status === 401) {
    window.location.assign('/login');
    throw new Error('Sign in required');
  }
  if (!response.ok) {
    const detail = typeof payload?.detail === 'string'
      ? payload.detail
      : payload?.detail?.message || `Request failed (${response.status})`;
    const error = new Error(detail);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function repositoryOptions(includeEmpty = false) {
  const writable = state.repositories.filter(item => {
    const permissions = item.permissions || {};
    return permissions.push || permissions.maintain || permissions.admin;
  });
  const items = writable.length ? writable : state.repositories;
  const options = items.map(item => (
    `<option value="${escapeHtml(item.full_name)}">${escapeHtml(item.full_name)}${item.private ? ' · private' : ' · public'}</option>`
  ));
  if (includeEmpty) options.unshift('<option value="">No repository link</option>');
  return options.join('');
}

async function loadRepositories() {
  try {
    const result = await api('/api/v1/github/repositories');
    state.repositories = Array.isArray(result.repositories) ? result.repositories : [];
    const delegation = byId('delegation-repository');
    const asset = byId('asset-repository');
    delegation.innerHTML = repositoryOptions(false) || '<option value="">Import a GitHub repository first</option>';
    asset.innerHTML = repositoryOptions(true) || '<option value="">No repository link</option>';
    delegation.disabled = state.repositories.length === 0;
  } catch (error) {
    byId('delegation-repository').innerHTML = '<option value="">Connect GitHub first</option>';
    byId('asset-repository').innerHTML = '<option value="">No repository link</option>';
    setNotice(error.message, 'error');
  }
}

function statusClass(status) {
  if (status === 'completed' || status === 'operational') return 'operational';
  if (status === 'running' || status === 'queued' || status === 'planning') return '';
  if (status === 'degraded' || status === 'awaiting_approval' || status === 'stale') return 'degraded';
  return 'offline';
}

function renderMetrics(overview) {
  const counts = overview.task_counts || {};
  const active = ['queued', 'running', 'awaiting_approval'].reduce((sum, key) => sum + Number(counts[key] || 0), 0);
  const attention = (overview.delegations || []).filter(item => item.human_attention_required).length;
  byId('metric-active').textContent = formatNumber(active, '0');
  byId('metric-attention').textContent = formatNumber(attention, '0');
  byId('metric-assets').textContent = formatNumber((overview.assets || []).length, '0');
  const edge = overview.execution_fabric?.edge;
  byId('metric-fabric').textContent = edge?.available ? `${edge.eligible_runners.length} edge` : 'Cloud ready';
}

function renderFabric(fabric) {
  byId('fabric-rule').textContent = fabric.selection_rule || '';
  const edge = fabric.edge || {};
  const cloud = fabric.cloud || {};
  byId('fabric-state').textContent = edge.available ? 'Edge + cloud ready' : 'Cloud fallback ready';
  byId('fabric-state').className = 'status operational';
  const runners = (edge.eligible_runners || []).map(runner => `
    <article class="fabric-card">
      <header><h3>${escapeHtml(runner.name)}</h3><span class="status operational">Online edge</span></header>
      <p class="muted">${escapeHtml(runner.version || 'Version not reported')}</p>
      <div class="detail-grid">
        <div><span>Capabilities</span><strong>${escapeHtml((runner.capabilities || []).join(', '))}</strong></div>
        <div><span>Labels</span><strong>${escapeHtml((runner.labels || []).join(', ') || 'none')}</strong></div>
        <div><span>Last seen</span><strong>${escapeHtml(formatDate(runner.last_seen_at))}</strong></div>
      </div>
    </article>`).join('');
  byId('fabric-cards').innerHTML = `
    <article class="fabric-card">
      <header><h3>Controlled cloud lane</h3><span class="status operational">Available</span></header>
      <p class="muted">${escapeHtml(cloud.isolation || 'Locked-down verification runner')}</p>
      <div class="detail-grid">
        <div><span>Target</span><strong>${escapeHtml(cloud.target || 'github')}</strong></div>
        <div><span>Active work</span><strong>${formatNumber(cloud.active_tasks, '0')}</strong></div>
        <div><span>Fallback</span><strong>Automatic</strong></div>
      </div>
    </article>
    ${runners || `<article class="fabric-card"><header><h3>Local edge runners</h3><span class="status degraded">Not eligible yet</span></header><p class="muted">Register an online runner that advertises <code>${escapeHtml(edge.required_capability || 'engineering_workforce_v1')}</code>. Amosclaud will keep using the controlled cloud lane until then.</p></article>`}`;
}

function renderGuardrails(guardrails) {
  const rows = [
    ['Isolated execution', guardrails.require_isolated_execution],
    ['Draft pull request only', guardrails.require_draft_pull_request],
    ['Human merge required', guardrails.require_human_merge],
    ['Rollback checkpoint', guardrails.require_rollback_checkpoint],
    ['Secret masking', guardrails.secret_masking],
    ['Force push', !guardrails.allow_force_push],
    ['Direct protected-branch writes', !guardrails.allow_direct_protected_branch_write],
    ['Automatic merge', !guardrails.allow_auto_merge],
  ];
  byId('guardrail-summary').innerHTML = rows.map(([label, enforced]) => (
    `<li>${escapeHtml(label)}<b>${enforced ? 'ENFORCED' : 'BLOCKED'}</b></li>`
  )).join('');
  byId('guardrail-allowed').value = (guardrails.allowed_paths || []).join('\n');
  byId('guardrail-protected').value = (guardrails.protected_paths || []).join('\n');
  byId('guardrail-branches').value = (guardrails.protected_branches || []).join('\n');
  byId('guardrail-prefix').value = guardrails.branch_prefix || 'amosclaud/workforce';
  byId('guardrail-attempts').value = String(guardrails.max_repair_attempts || 3);
}

function phaseState(phase, status) {
  const order = ['understand', 'plan', 'execute', 'verify', 'deliver'];
  const current = {
    planning: 1,
    awaiting_approval: 1,
    queued: 2,
    running: 3,
    completed: 4,
    failed: 3,
    blocked: 2,
    cancelled: 1,
  }[status] ?? 0;
  const index = order.indexOf(phase);
  if (status === 'completed' || index < current) return 'done';
  if (index === current) return 'active';
  return '';
}

function renderDelegations(delegations) {
  byId('delegation-count').textContent = String(delegations.length);
  if (!delegations.length) {
    byId('delegation-list').innerHTML = '<p class="empty">No delegated work yet.</p>';
    return;
  }
  byId('delegation-list').innerHTML = delegations.map(item => {
    const task = item.task || {};
    const actions = [];
    if (item.status === 'awaiting_approval') {
      actions.push(`<button data-action="approve" data-id="${escapeHtml(item.id)}">Authorize and start</button>`);
    }
    if (['awaiting_approval', 'queued'].includes(item.status)) {
      actions.push(`<button data-action="cancel" data-id="${escapeHtml(item.id)}">Cancel</button>`);
    }
    if (task.pull_request_url) {
      actions.push(`<a href="${escapeHtml(task.pull_request_url)}" target="_blank" rel="noopener noreferrer">Open draft pull request</a>`);
    }
    const plan = (item.plan || []).map(step => (
      `<li class="${phaseState(step.phase, item.status)}">${escapeHtml(step.label)}${step.human_required ? ' · human sign-off' : ''}</li>`
    )).join('');
    return `
      <article class="work-card">
        <header>
          <div><p class="eyebrow">${escapeHtml(item.kind)} · ${escapeHtml(item.repository)}</p><h3>${escapeHtml(item.title)}</h3></div>
          <span class="status ${statusClass(item.status)}">${escapeHtml(item.status.replaceAll('_', ' '))}</span>
        </header>
        <p class="muted">${escapeHtml(item.requirement)}</p>
        <div class="detail-grid">
          <div><span>Execution</span><strong>${escapeHtml(item.execution_target || 'not selected')}</strong></div>
          <div><span>Task</span><strong>${escapeHtml(item.task_id || 'not queued')}</strong></div>
          <div><span>Updated</span><strong>${escapeHtml(formatDate(item.updated_at))}</strong></div>
        </div>
        <ol class="timeline">${plan}</ol>
        ${item.human_attention_reason ? `<p class="notice ${item.status === 'completed' ? 'success' : ''}">${escapeHtml(item.human_attention_reason)}</p>` : ''}
        ${task.summary ? `<p><strong>Result:</strong> ${escapeHtml(task.summary)}</p>` : ''}
        <div class="card-actions">${actions.join('')}</div>
      </article>`;
  }).join('');
}

function renderAssets(assets) {
  byId('asset-count').textContent = String(assets.length);
  if (!assets.length) {
    byId('asset-list').innerHTML = '<p class="empty">No software assets registered.</p>';
    return;
  }
  byId('asset-list').innerHTML = assets.map(asset => {
    const health = asset.health || {};
    const latest = health.latest || {};
    const window24 = health.window_24h || {};
    const business = health.business || {};
    const maintenance = health.autonomous_maintenance || {};
    return `
      <article class="asset-card">
        <header>
          <div><p class="eyebrow">${escapeHtml(asset.asset_type.replaceAll('_', ' '))} · ${escapeHtml(asset.environment)}</p><h3>${escapeHtml(asset.name)}</h3></div>
          <span class="status ${statusClass(health.state)}">${escapeHtml(health.state || 'unknown')}</span>
        </header>
        <p class="health-line">${escapeHtml(asset.repository || 'No repository linked')}</p>
        <div class="detail-grid">
          <div><span>24h uptime</span><strong>${window24.uptime_percent === null || window24.uptime_percent === undefined ? '—' : `${window24.uptime_percent}%`}</strong></div>
          <div><span>Average latency</span><strong>${window24.average_latency_ms === null || window24.average_latency_ms === undefined ? '—' : `${window24.average_latency_ms} ms`}</strong></div>
          <div><span>Errors / requests</span><strong>${formatNumber(window24.errors, '0')} / ${formatNumber(window24.requests, '0')}</strong></div>
          <div><span>CPU / memory</span><strong>${latest.cpu_percent ?? '—'}% / ${latest.memory_mb ?? '—'} MB</strong></div>
          <div><span>Active users</span><strong>${formatNumber(business.active_users)}</strong></div>
          <div><span>Revenue telemetry</span><strong>${formatUsd(business.revenue_usd)}</strong></div>
          <div><span>Patch success</span><strong>${maintenance.patch_success_rate === null || maintenance.patch_success_rate === undefined ? '—' : `${maintenance.patch_success_rate}%`}</strong></div>
          <div><span>Last sample</span><strong>${escapeHtml(formatDate(latest.observed_at))}</strong></div>
          <div><span>Telemetry token</span><strong>${escapeHtml(asset.telemetry_token_prefix || 'hidden')}…</strong></div>
        </div>
        <div class="card-actions">
          <a href="/api/v1/workforce/assets/${encodeURIComponent(asset.id)}/manifest" target="_blank" rel="noopener noreferrer">Portable manifest</a>
          <button data-action="rotate-asset-token" data-id="${escapeHtml(asset.id)}">Rotate telemetry token</button>
        </div>
      </article>`;
  }).join('');
}

async function loadOverview({ quiet = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  if (!quiet) setNotice('Refreshing durable tasks, execution fabric, guardrails, and software assets…');
  try {
    const overview = await api('/api/v1/workforce/overview');
    state.overview = overview;
    renderMetrics(overview);
    renderFabric(overview.execution_fabric || {});
    renderGuardrails(overview.guardrails || {});
    renderDelegations(overview.delegations || []);
    renderAssets(overview.assets || []);
    byId('last-refresh').textContent = `Updated ${new Date().toLocaleTimeString()}`;
    if (!quiet) setNotice('Workforce state is current.', 'success');
  } catch (error) {
    setNotice(error.message, 'error');
  } finally {
    state.loading = false;
  }
}

byId('delegation-kind').addEventListener('change', event => {
  const mode = byId('delegation-mode');
  if (event.target.value === 'bug') mode.value = 'fix';
  if (['epic', 'feature', 'refactor', 'requirement'].includes(event.target.value)) mode.value = 'build';
});

byId('delegation-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = byId('delegate-button');
  const criteria = byId('delegation-criteria').value.split('\n').map(item => item.trim()).filter(Boolean);
  button.disabled = true;
  button.textContent = 'Creating durable work order…';
  try {
    const result = await api('/api/v1/workforce/delegations', {
      method: 'POST',
      body: JSON.stringify({
        repository: byId('delegation-repository').value,
        kind: byId('delegation-kind').value,
        title: byId('delegation-title').value.trim(),
        requirement: byId('delegation-requirement').value.trim(),
        source_reference: byId('delegation-source').value.trim() || null,
        acceptance_criteria: criteria,
        mode: byId('delegation-mode').value,
        execution_preference: byId('delegation-execution').value,
        authorize_changes: byId('delegation-authorize').checked,
      }),
    });
    event.target.reset();
    setNotice(`Delegation ${result.id} entered ${result.status}.`, 'success');
    await loadOverview({ quiet: true });
  } catch (error) {
    setNotice(error.message, 'error');
  } finally {
    button.disabled = false;
    button.textContent = 'Delegate to Amosclaud';
  }
});

byId('delegation-list').addEventListener('click', async event => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  button.disabled = true;
  try {
    const action = button.dataset.action;
    await api(`/api/v1/workforce/delegations/${encodeURIComponent(button.dataset.id)}/${action}`, { method: 'POST' });
    setNotice(action === 'approve' ? 'Delegation authorized and queued.' : 'Delegation cancelled.', 'success');
    await loadOverview({ quiet: true });
  } catch (error) {
    setNotice(error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

byId('guardrail-form').addEventListener('submit', async event => {
  event.preventDefault();
  const lines = id => byId(id).value.split('\n').map(item => item.trim()).filter(Boolean);
  const button = event.submitter;
  button.disabled = true;
  try {
    await api('/api/v1/workforce/guardrails', {
      method: 'PUT',
      body: JSON.stringify({
        allowed_paths: lines('guardrail-allowed'),
        protected_paths: lines('guardrail-protected'),
        protected_branches: lines('guardrail-branches'),
        branch_prefix: byId('guardrail-prefix').value.trim(),
        max_repair_attempts: Number(byId('guardrail-attempts').value),
      }),
    });
    setNotice('Bounded guardrail paths were updated. Immutable safety rules remain enforced.', 'success');
    await loadOverview({ quiet: true });
  } catch (error) {
    setNotice(error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

byId('asset-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    const asset = await api('/api/v1/workforce/assets', {
      method: 'POST',
      body: JSON.stringify({
        name: byId('asset-name').value.trim(),
        repository: byId('asset-repository').value || null,
        asset_type: byId('asset-type').value,
        environment: byId('asset-environment').value,
        target_url: byId('asset-url').value.trim() || null,
        license_reference: byId('asset-license').value.trim() || null,
        transfer_notes: byId('asset-transfer').value.trim() || null,
      }),
    });
    byId('asset-token-value').textContent = asset.telemetry_token;
    byId('asset-token').hidden = false;
    event.target.reset();
    setNotice(`Software asset ${asset.name} registered. Copy its telemetry credential now.`, 'success');
    await loadOverview({ quiet: true });
  } catch (error) {
    setNotice(error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

byId('asset-list').addEventListener('click', async event => {
  const button = event.target.closest('button[data-action="rotate-asset-token"]');
  if (!button) return;
  button.disabled = true;
  try {
    const result = await api(`/api/v1/workforce/assets/${encodeURIComponent(button.dataset.id)}/rotate-token`, { method: 'POST' });
    byId('asset-token-value').textContent = result.telemetry_token;
    byId('asset-token').hidden = false;
    setNotice('Telemetry credential rotated. The previous credential is invalid.', 'success');
    await loadOverview({ quiet: true });
  } catch (error) {
    setNotice(error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

byId('refresh-all').addEventListener('click', () => loadOverview());

await loadRepositories();
await loadOverview();
window.setInterval(() => loadOverview({ quiet: true }), 15000);
