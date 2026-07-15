(() => {
  const sidebar = document.querySelector('.auto-sidebar');
  if (!sidebar) return;

  const panel = document.createElement('section');
  panel.className = 'auto-card auto-summary';
  panel.innerHTML = `
    <h3>Backend model services</h3>
    <p id="model-services-summary">Checking the Autonomous backend…</p>
    <div id="model-services-list" class="auto-summary-list"></div>
    <h3 style="margin-top:24px">Autonomous keys</h3>
    <p>Create a key for tools and integrations. Keys are shown only once.</p>
    <label>Key name<input id="autonomous-key-name" value="My Autonomous key" maxlength="80"></label>
    <button id="create-autonomous-key" class="btn-primary" type="button">Generate secure key</button>
    <pre id="new-autonomous-key" hidden style="white-space:pre-wrap;overflow-wrap:anywhere"></pre>
    <div id="autonomous-key-list" class="auto-summary-list"></div>`;
  sidebar.prepend(panel);

  const summary = panel.querySelector('#model-services-summary');
  const servicesList = panel.querySelector('#model-services-list');
  const keyList = panel.querySelector('#autonomous-key-list');
  const keyName = panel.querySelector('#autonomous-key-name');
  const keyOutput = panel.querySelector('#new-autonomous-key');
  const createButton = panel.querySelector('#create-autonomous-key');

  async function json(url, options = {}) {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options, headers: {'Content-Type': 'application/json', ...(options.headers || {})}});
    const text = await response.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch { data = {detail: text}; }
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return data;
  }

  async function loadServices() {
    try {
      const data = await json('/api/v1/agent/readiness');
      summary.textContent = `${data.ready_count}/${data.total_count} services ready · model: ${data.active_model}`;
      servicesList.replaceChildren();
      (data.services || []).forEach(service => {
        const row = document.createElement('div');
        row.className = 'auto-summary-item';
        row.innerHTML = '<span></span><strong></strong>';
        row.querySelector('span').textContent = service.ready ? 'Ready' : 'Setup';
        row.querySelector('strong').textContent = `${service.name} — ${service.detail}`;
        servicesList.appendChild(row);
      });
    } catch (error) { summary.textContent = `Backend services unavailable: ${error.message}`; }
  }

  async function loadKeys() {
    try {
      const data = await json('/api/v1/agent/keys');
      keyList.replaceChildren();
      (data.keys || []).forEach(key => {
        const row = document.createElement('div');
        row.className = 'auto-summary-item';
        const state = key.revoked_at ? 'Revoked' : 'Active';
        row.innerHTML = `<span>${state}</span><strong></strong>`;
        row.querySelector('strong').textContent = `${key.name} · ${key.prefix}…`;
        if (!key.revoked_at) {
          const rotate = document.createElement('button');
          rotate.type = 'button'; rotate.textContent = 'Rotate'; rotate.className = 'btn-ghost compact-button';
          rotate.addEventListener('click', async () => {
            const replacement = await json(`/api/v1/agent/keys/${key.id}/rotate`, {method: 'POST', body: '{}'});
            keyOutput.hidden = false;
            keyOutput.textContent = `${replacement.warning}\n\n${replacement.key}`;
            await loadKeys();
          });
          row.appendChild(rotate);
        }
        keyList.appendChild(row);
      });
    } catch (error) { keyList.textContent = `Keys unavailable: ${error.message}`; }
  }

  createButton.addEventListener('click', async () => {
    createButton.disabled = true;
    try {
      const created = await json('/api/v1/agent/keys', {method: 'POST', body: JSON.stringify({name: keyName.value.trim() || 'Autonomous key'})});
      keyOutput.hidden = false;
      keyOutput.textContent = `${created.warning}\n\n${created.key}`;
      await loadKeys();
    } catch (error) { keyOutput.hidden = false; keyOutput.textContent = error.message; }
    finally { createButton.disabled = false; }
  });

  loadServices();
  loadKeys();
})();
