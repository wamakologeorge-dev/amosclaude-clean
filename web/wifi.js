const keyInput = document.getElementById('admin-key');
const message = document.getElementById('message');
const badge = document.getElementById('status-badge');
const devices = document.getElementById('devices');
const diagnostics = document.getElementById('diagnostics');
const diagnosticButton = document.getElementById('run-diagnostics');

keyInput.value = sessionStorage.getItem('amosAdminKey') || '';

function show(text, ok = false) {
  message.textContent = text;
  message.className = ok ? 'message ok' : 'message';
}

function headers() {
  const key = keyInput.value.trim();
  if (!key) throw new Error('Enter the administrator key first.');
  return {'Content-Type': 'application/json', 'X-Admin-Key': key};
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers: {...headers(), ...(options.headers || {})},
  });
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (_) {
    data = {detail: text};
  }
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

function setBadge(text, state) {
  badge.textContent = text;
  badge.className = `badge ${state || ''}`.trim();
}

function readRecord(value) {
  if (Array.isArray(value)) return value[0] || {};
  return value || {};
}

async function loadStatus() {
  show('Checking access point…', true);
  try {
    const data = await api('/api/v1/admin/wifi/status');
    sessionStorage.setItem('amosAdminKey', keyInput.value.trim());
    setBadge('Online', 'online');
    const identity = readRecord(data.identity);
    const resources = readRecord(data.resources);
    document.getElementById('identity').textContent = identity.name || identity.identity || 'MikroTik';
    document.getElementById('platform').textContent = resources.platform || resources['board-name'] || 'RouterOS';
    document.getElementById('uptime').textContent = resources.uptime || '—';
    show('Access point connected.', true);
    return true;
  } catch (error) {
    setBadge('Offline', 'offline');
    show(error.message);
    return false;
  }
}

function appendDevice(item) {
  const row = document.createElement('div');
  row.className = 'device';
  const title = document.createElement('strong');
  title.textContent = item['host-name'] || item.comment || item.mac_address || item['mac-address'] || 'Unknown device';
  const detail = document.createElement('div');
  detail.className = 'muted';
  detail.textContent = [
    item['mac-address'] || item.mac_address || '',
    item.signal || item['signal-strength'] || '',
  ].filter(Boolean).join(' ');
  row.append(title, detail);
  devices.appendChild(row);
}

async function loadDevices() {
  devices.textContent = 'Loading…';
  try {
    const data = await api('/api/v1/admin/wifi/devices');
    const rows = data.devices || [];
    devices.textContent = '';
    if (!rows.length) {
      devices.textContent = 'No connected devices found.';
      return;
    }
    rows.forEach(appendDevice);
  } catch (error) {
    devices.textContent = error.message;
  }
}

function renderDiagnostics(data) {
  diagnostics.textContent = '';
  for (const check of data.checks || []) {
    const row = document.createElement('div');
    row.className = 'diagnostic';

    const state = document.createElement('span');
    state.className = `diagnostic-state ${check.state}`;
    state.textContent = check.state;

    const label = document.createElement('strong');
    label.textContent = check.label;

    const detail = document.createElement('span');
    detail.className = 'diagnostic-detail';
    detail.textContent = check.detail;

    const latency = document.createElement('span');
    latency.className = 'latency';
    latency.textContent = Number.isFinite(check.latency_ms) ? `${check.latency_ms} ms` : '—';

    row.append(state, label, detail, latency);
    diagnostics.appendChild(row);
  }

  const facts = document.getElementById('network-facts');
  const accessPoint = data.access_point || {};
  const networkService = data.network_service || {};
  const localService = networkService.local || {};
  document.getElementById('diagnostic-ssid').textContent = accessPoint.ssid || '—';
  document.getElementById('diagnostic-channel').textContent = accessPoint.channel || '—';
  document.getElementById('diagnostic-devices').textContent = accessPoint.connected_devices ?? '—';
  document.getElementById('diagnostic-stations').textContent = localService.ready_stations ?? '—';
  facts.hidden = false;

  const state = data.status || 'degraded';
  setBadge(state.charAt(0).toUpperCase() + state.slice(1), state);
}

async function runDiagnostics() {
  diagnosticButton.disabled = true;
  diagnostics.innerHTML = '<div class="muted">Running bounded network checks…</div>';
  show('Running network diagnostics…', true);
  try {
    const data = await api('/api/v1/admin/wifi/diagnostics');
    sessionStorage.setItem('amosAdminKey', keyInput.value.trim());
    renderDiagnostics(data);
    const failed = data.summary?.failed || 0;
    show(failed ? `${failed} network check(s) failed.` : 'All configured network checks passed.', failed === 0);
  } catch (error) {
    diagnostics.textContent = error.message;
    setBadge('Failed', 'failed');
    show(error.message);
  } finally {
    diagnosticButton.disabled = false;
  }
}

document.getElementById('connect').addEventListener('click', async () => {
  const online = await loadStatus();
  if (online) {
    await Promise.all([loadDevices(), runDiagnostics()]);
  }
});
document.getElementById('refresh').addEventListener('click', loadStatus);
document.getElementById('refresh-devices').addEventListener('click', loadDevices);
diagnosticButton.addEventListener('click', runDiagnostics);
document.getElementById('forget').addEventListener('click', () => {
  sessionStorage.removeItem('amosAdminKey');
  keyInput.value = '';
  show('Administrator key removed.', true);
});
document.getElementById('save-network').addEventListener('click', async () => {
  const ssid = document.getElementById('ssid').value.trim();
  const password = document.getElementById('wifi-password').value;
  const disabled = document.getElementById('disabled').checked;
  if (!ssid) {
    show('Enter a Wi-Fi network name.');
    return;
  }
  if (password.length < 8) {
    show('Wi-Fi password must contain at least 8 characters.');
    return;
  }
  show('Saving Wi-Fi settings…', true);
  try {
    await api('/api/v1/admin/wifi/network', {
      method: 'PUT',
      body: JSON.stringify({ssid, password, disabled}),
    });
    show('Wi-Fi settings saved. Connected devices may briefly disconnect.', true);
    await runDiagnostics();
  } catch (error) {
    show(error.message);
  }
});
