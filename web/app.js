/**
 * Amoscloud AI Platform — shared dashboard JavaScript.
 *
 * This file is loaded by more than one page. Every DOM element outside the
 * shared top bar is therefore optional and must be checked before use.
 */

const API = window.location.origin;

function $(id) { return document.getElementById(id); }

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function bind(id, eventName, handler) {
  const element = $(id);
  if (element) element.addEventListener(eventName, handler);
  return element;
}

function showToast(msg, type = 'info') {
  const container = $('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast toast--${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

function statusBadge(status) {
  if (!status) return '<span class="badge badge-default">unknown</span>';
  const value = String(status).toLowerCase();
  let className = 'badge-default';
  if (['success', 'completed', 'healthy', 'ok'].includes(value)) className = 'badge-success';
  else if (['running', 'active', 'in_progress'].includes(value)) className = 'badge-running';
  else if (['pending', 'queued', 'waiting'].includes(value)) className = 'badge-pending';
  else if (['failed', 'error', 'cancelled'].includes(value)) className = 'badge-failed';
  return `<span class="badge ${className}">${escapeHtml(status)}</span>`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmtDate(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

function addAgentReport(message, muted = false) {
  const replies = $('agent-replies');
  if (!replies) return;
  const item = document.createElement('div');
  item.className = muted ? 'agent-reply muted' : 'agent-reply';
  item.textContent = message;
  if (replies.querySelector('.muted')) replies.innerHTML = '';
  replies.prepend(item);
}

async function fetchAgent() {
  const status = $('agent-status');
  if (!status) return;
  try {
    const response = await fetch(`${API}/api/v1/agent`, {
      credentials: 'same-origin',
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    setText('agent-name', data.name || 'Amosclaud Autonomous Server');
    setText('agent-mission', data.mission || 'Ready to run autonomous Amosclaud operations.');
    status.className = 'badge badge-success';
    status.textContent = data.mode || 'ready';
  } catch (error) {
    status.className = 'badge badge-failed';
    status.textContent = 'offline';
    console.error('[Agent profile]', error);
  }
}

async function fetchHealth() {
  const dot = $('status-indicator');
  const label = $('status-label');
  if (!dot && !label) return;

  try {
    const response = await fetch(`${API}/health`, {
      credentials: 'same-origin',
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    if (dot) dot.className = 'status-dot status-ok';
    if (label) label.textContent = 'Server alive';
    setText('health-icon', '💚');
    setText('stat-health', data.status || 'ok');
    setText('stat-uptime', data.uptime !== undefined ? `${Math.floor(data.uptime)}s` : 'running');
  } catch (error) {
    if (dot) dot.className = 'status-dot status-error';
    if (label) label.textContent = 'Server unreachable';
    setText('health-icon', '🔴');
    setText('stat-health', 'error');
    setText('stat-uptime', '—');
    console.error('[Health]', error);
  }
}

async function fetchPipelines() {
  const tbody = $('pipelines-body');
  if (!tbody) return;
  try {
    const response = await fetch(`${API}/api/v1/pipelines`, {
      credentials: 'same-origin',
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const rows = Array.isArray(data) ? data : (data.pipelines || data.items || []);
    setText('stat-pipelines', rows.length);

    if (rows.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-row">No pipelines yet.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(pipeline => `
      <tr>
        <td>${escapeHtml(pipeline.id || pipeline.pipeline_id || '—')}</td>
        <td>${escapeHtml(pipeline.name || pipeline.trigger || 'Pipeline')}</td>
        <td>${statusBadge(pipeline.status)}</td>
        <td>${escapeHtml(pipeline.branch || pipeline.ref || '—')}</td>
        <td>${fmtDate(pipeline.started_at || pipeline.created_at || pipeline.createdAt)}</td>
      </tr>`).join('');
  } catch (error) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-row">Failed to load pipelines.</td></tr>';
    console.error('[Pipelines]', error);
  }
}

async function fetchDeployments() {
  const tbody = $('deployments-body');
  if (!tbody) return;
  try {
    const response = await fetch(`${API}/api/v1/deployments`, {
      credentials: 'same-origin',
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const rows = Array.isArray(data) ? data : (data.deployments || data.items || []);
    const active = rows.filter(deployment =>
      ['running', 'active', 'in_progress'].includes(String(deployment.status || '').toLowerCase())
    ).length;
    setText('stat-deployments', active || rows.length);

    if (rows.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-row">No deployments yet.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(deployment => `
      <tr>
        <td>${escapeHtml(deployment.id || deployment.deployment_id || '—')}</td>
        <td>${escapeHtml(deployment.name || deployment.version || 'Deployment')}</td>
        <td>${statusBadge(deployment.status)}</td>
        <td>${escapeHtml(deployment.environment || deployment.env || '—')}</td>
        <td>${fmtDate(deployment.started_at || deployment.created_at || deployment.createdAt)}</td>
      </tr>`).join('');
  } catch (error) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-row">Failed to load deployments.</td></tr>';
    console.error('[Deployments]', error);
  }
}

const REFRESH_INTERVAL = 10;
let countdownValue = REFRESH_INTERVAL;

function refreshAll() {
  fetchHealth();
  fetchAgent();
  fetchPipelines();
  fetchDeployments();
}

function startCountdown() {
  const element = $('countdown');
  if (!element) return null;
  countdownValue = REFRESH_INTERVAL;
  element.textContent = countdownValue;
  return setInterval(() => {
    countdownValue -= 1;
    if (countdownValue <= 0) {
      countdownValue = REFRESH_INTERVAL;
      refreshAll();
    }
    element.textContent = countdownValue;
  }, 1000);
}

function openModal(modalId) {
  const backdrop = $('modal-backdrop');
  const modal = $(modalId);
  if (!backdrop || !modal) return;
  backdrop.classList.remove('hidden');
  modal.classList.remove('hidden');
}

function closeModals() {
  $('modal-backdrop')?.classList.add('hidden');
  document.querySelectorAll('.modal').forEach(modal => modal.classList.add('hidden'));
}

bind('modal-backdrop', 'click', closeModals);
bind('btn-trigger-pipeline', 'click', () => openModal('modal-pipeline'));
bind('btn-cancel-pipeline', 'click', closeModals);
bind('btn-confirm-pipeline', 'click', async () => {
  const nameInput = $('pipeline-name-input');
  const branchInput = $('pipeline-branch-input');
  const name = nameInput?.value.trim() || '';
  const branch = branchInput?.value.trim() || 'main';
  if (!name) { showToast('Pipeline name is required', 'error'); return; }
  try {
    const response = await fetch(`${API}/api/v1/pipelines`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trigger: 'manual', branch, payload: { name } }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    showToast(`Pipeline "${name}" triggered!`, 'success');
    closeModals();
    if (nameInput) nameInput.value = '';
    refreshAll();
  } catch (error) {
    showToast('Failed to trigger pipeline', 'error');
    console.error('[Trigger pipeline]', error);
  }
});

bind('btn-start-deployment', 'click', () => openModal('modal-deployment'));
bind('btn-cancel-deployment', 'click', closeModals);
bind('btn-confirm-deployment', 'click', async () => {
  const nameInput = $('deployment-name-input');
  const environmentInput = $('deployment-env-input');
  const name = nameInput?.value.trim() || '';
  const environment = environmentInput?.value || 'production';
  if (!name) { showToast('Deployment name is required', 'error'); return; }
  try {
    const response = await fetch(`${API}/api/v1/deployments`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version: name, environment }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    showToast(`Deployment "${name}" started!`, 'success');
    closeModals();
    if (nameInput) nameInput.value = '';
    refreshAll();
  } catch (error) {
    showToast('Failed to start deployment', 'error');
    console.error('[Start deployment]', error);
  }
});

// The cloud-agent page owns its Send button through conversational-agent.js.
// Keep this legacy handler only for older pages that explicitly opt in.
if (document.body.dataset.legacyAgentRunner === 'true') {
  bind('btn-run-agent', 'click', async () => {
    const runButton = $('btn-run-agent');
    const status = $('agent-status');
    const mode = $('agent-mode-input')?.value || 'autonomous-check';
    const objectiveInput = $('agent-objective-input');
    const objective = objectiveInput?.value.trim() || '';
    if (runButton) runButton.disabled = true;
    if (status) { status.className = 'badge badge-running'; status.textContent = 'running'; }
    try {
      const response = await fetch(`${API}/api/v1/agent/run`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, objective: objective || undefined, branch: 'main', metadata: { branch: 'main' } }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      addAgentReport(data.reply || 'Autonomous run accepted.');
      showToast(`Autonomous run ${data.run_id || ''}`.trim(), 'success');
      if (objectiveInput) objectiveInput.value = '';
      refreshAll();
    } catch (error) {
      if (status) { status.className = 'badge badge-failed'; status.textContent = 'error'; }
      showToast('Failed to start autonomous run', 'error');
      console.error('[Run agent]', error);
    } finally {
      if (runButton) runButton.disabled = false;
      fetchAgent();
    }
  });
}

refreshAll();
startCountdown();
