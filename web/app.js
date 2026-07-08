/**
 * Amoscloud AI Platform — Dashboard JS
 * Fetches /health, /api/v1/pipelines, /api/v1/deployments
 * Auto-refreshes every 10 seconds
 */

/* ── Helpers ─────────────────────────────────────────────────── */
const API = window.location.origin;

function $(id) { return document.getElementById(id); }

function showToast(msg, type = 'info') {
  const container = $('toast-container');
  const t = document.createElement('div');
  t.className = `toast toast--${type}`;
  t.textContent = msg;
  container.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

function statusBadge(status) {
  if (!status) return '<span class="badge badge-default">unknown</span>';
  const s = String(status).toLowerCase();
  let cls = 'badge-default';
  if (['success', 'completed', 'healthy', 'ok'].includes(s)) cls = 'badge-success';
  else if (['running', 'active', 'in_progress'].includes(s))  cls = 'badge-running';
  else if (['pending', 'queued', 'waiting'].includes(s))      cls = 'badge-pending';
  else if (['failed', 'error', 'cancelled'].includes(s))      cls = 'badge-failed';
  return `<span class="badge ${cls}">${escapeHtml(status)}</span>`;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmtDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch { return iso; }
}

/* ── Health check ────────────────────────────────────────────── */
async function fetchHealth() {
  const dot   = $('status-indicator');
  const label = $('status-label');
  const icon  = $('health-icon');
  const stat  = $('stat-health');

  try {
    const res  = await fetch(`${API}/health`);
    const data = await res.json();

    dot.className   = 'status-dot status-ok';
    label.textContent = 'Server alive';
    icon.textContent  = '💚';
    stat.textContent  = data.status || 'ok';

    // Uptime (not always exposed, graceful fallback)
    if (data.uptime !== undefined) {
      $('stat-uptime').textContent = `${Math.floor(data.uptime)}s`;
    } else {
      $('stat-uptime').textContent = 'running';
    }
  } catch {
    dot.className   = 'status-dot status-error';
    label.textContent = 'Server unreachable';
    icon.textContent  = '🔴';
    stat.textContent  = 'error';
    $('stat-uptime').textContent = '—';
  }
}

/* ── Pipelines ───────────────────────────────────────────────── */
async function fetchPipelines() {
  const tbody = $('pipelines-body');
  try {
    const res  = await fetch(`${API}/api/v1/pipelines`);
    const data = await res.json();
    const rows = Array.isArray(data) ? data : (data.pipelines || data.items || []);

    $('stat-pipelines').textContent = rows.length;

    if (rows.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-row">No pipelines yet.</td></tr>';
      return;
    }

    tbody.innerHTML = rows.map(p => `
      <tr>
        <td>${escapeHtml(p.id || p.pipeline_id || '—')}</td>
        <td>${escapeHtml(p.name || '—')}</td>
        <td>${statusBadge(p.status)}</td>
        <td>${escapeHtml(p.branch || p.ref || '—')}</td>
        <td>${fmtDate(p.created_at || p.createdAt)}</td>
      </tr>`).join('');
  } catch (err) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-row">Failed to load pipelines.</td></tr>';
    console.error('[Pipelines]', err);
  }
}

/* ── Deployments ─────────────────────────────────────────────── */
async function fetchDeployments() {
  const tbody = $('deployments-body');
  try {
    const res  = await fetch(`${API}/api/v1/deployments`);
    const data = await res.json();
    const rows = Array.isArray(data) ? data : (data.deployments || data.items || []);

    const active = rows.filter(d => {
      const s = String(d.status || '').toLowerCase();
      return ['running', 'active', 'in_progress'].includes(s);
    }).length;
    $('stat-deployments').textContent = active || rows.length;

    if (rows.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-row">No deployments yet.</td></tr>';
      return;
    }

    tbody.innerHTML = rows.map(d => `
      <tr>
        <td>${escapeHtml(d.id || d.deployment_id || '—')}</td>
        <td>${escapeHtml(d.name || '—')}</td>
        <td>${statusBadge(d.status)}</td>
        <td>${escapeHtml(d.environment || d.env || '—')}</td>
        <td>${fmtDate(d.created_at || d.createdAt)}</td>
      </tr>`).join('');
  } catch (err) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-row">Failed to load deployments.</td></tr>';
    console.error('[Deployments]', err);
  }
}

/* ── Auto-refresh ────────────────────────────────────────────── */
const REFRESH_INTERVAL = 10;
let countdownValue = REFRESH_INTERVAL;

function refreshAll() {
  fetchHealth();
  fetchPipelines();
  fetchDeployments();
}

function startCountdown() {
  const el = $('countdown');
  countdownValue = REFRESH_INTERVAL;
  el.textContent = countdownValue;

  return setInterval(() => {
    countdownValue--;
    if (countdownValue <= 0) {
      countdownValue = REFRESH_INTERVAL;
      refreshAll();
    }
    el.textContent = countdownValue;
  }, 1000);
}

/* ── Modal helpers ───────────────────────────────────────────── */
function openModal(modalId) {
  $('modal-backdrop').classList.remove('hidden');
  $(modalId).classList.remove('hidden');
}

function closeModals() {
  $('modal-backdrop').classList.add('hidden');
  document.querySelectorAll('.modal').forEach(m => m.classList.add('hidden'));
}

$('modal-backdrop').addEventListener('click', closeModals);

/* ── Trigger Pipeline ────────────────────────────────────────── */
$('btn-trigger-pipeline').addEventListener('click', () => openModal('modal-pipeline'));
$('btn-cancel-pipeline').addEventListener('click', closeModals);

$('btn-confirm-pipeline').addEventListener('click', async () => {
  const name   = $('pipeline-name-input').value.trim();
  const branch = $('pipeline-branch-input').value.trim() || 'main';

  if (!name) {
    showToast('Pipeline name is required', 'error');
    return;
  }

  try {
    const res = await fetch(`${API}/api/v1/pipelines`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, branch }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    showToast(`Pipeline "${name}" triggered!`, 'success');
    closeModals();
    $('pipeline-name-input').value = '';
    refreshAll();
  } catch (err) {
    showToast('Failed to trigger pipeline', 'error');
    console.error('[Trigger pipeline]', err);
  }
});

/* ── Start Deployment ────────────────────────────────────────── */
$('btn-start-deployment').addEventListener('click', () => openModal('modal-deployment'));
$('btn-cancel-deployment').addEventListener('click', closeModals);

$('btn-confirm-deployment').addEventListener('click', async () => {
  const name        = $('deployment-name-input').value.trim();
  const environment = $('deployment-env-input').value;

  if (!name) {
    showToast('Deployment name is required', 'error');
    return;
  }

  try {
    const res = await fetch(`${API}/api/v1/deployments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, environment }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    showToast(`Deployment "${name}" started!`, 'success');
    closeModals();
    $('deployment-name-input').value = '';
    refreshAll();
  } catch (err) {
    showToast('Failed to start deployment', 'error');
    console.error('[Start deployment]', err);
  }
});

/* ── Init ────────────────────────────────────────────────────── */
refreshAll();
startCountdown();
