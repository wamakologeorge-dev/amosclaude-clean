(() => {
  const root = document.getElementById('amomodel-controls');
  if (!root) return;

  const status = document.getElementById('amomodel-status');
  const turnOn = document.getElementById('btn-amomodel-on');
  const turnOff = document.getElementById('btn-amomodel-off');
  if (!status || !turnOn || !turnOff) return;

  async function readJson(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return data;
  }

  function renderRuntime(data) {
    const services = Object.entries(data.services || {})
      .map(([name, state]) => `${name}: ${state}`)
      .join(' · ');
    turnOn.disabled = ['starting', 'ready', 'busy'].includes(String(data.state || '').toLowerCase());
    turnOff.disabled = String(data.state || '').toLowerCase() === 'off';
    root.dataset.runtimeState = data.state || 'unknown';
    root.dataset.runtimeServices = services;
  }

  function renderModel(data) {
    const model = data.model || 'configured model';
    const provider = data.provider === 'ollama' ? 'Ollama' : data.provider || 'Amosclaud model';
    status.textContent = data.available
      ? `${provider} connected · ${model}`
      : `Ollama unavailable · ${data.required_action || 'configure OLLAMA_URL and OLLAMA_API_KEY on the server'}`;
    status.dataset.state = data.available ? 'ready' : 'blocked';
  }

  async function refreshModel() {
    try {
      const response = await fetch('/api/v1/amomodel/model/status', {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      renderModel(await readJson(response));
    } catch (error) {
      status.textContent = `Ollama check failed: ${error.message}`;
      status.dataset.state = 'error';
    }
  }

  async function request(path, method = 'GET') {
    status.textContent = 'Updating the Amosclaud runtime…';
    try {
      const response = await fetch(path, {
        method,
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
      });
      renderRuntime(await readJson(response));
      await refreshModel();
    } catch (error) {
      status.textContent = `AmoModel unavailable: ${error.message}`;
      status.dataset.state = 'error';
    }
  }

  turnOn.addEventListener('click', () => request('/api/v1/amomodel/power/on', 'POST'));
  turnOff.addEventListener('click', () => request('/api/v1/amomodel/power/off', 'POST'));
  request('/api/v1/amomodel/status');
  refreshModel();
})();
