(() => {
  const root = document.getElementById('amomodel-controls');
  if (!root) return;

  const status = document.getElementById('amomodel-status');
  const turnOn = document.getElementById('btn-amomodel-on');
  const turnOff = document.getElementById('btn-amomodel-off');

  async function readJson(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return data;
  }

  function render(data) {
    const services = Object.entries(data.services || {})
      .map(([name, state]) => `${name}: ${state}`)
      .join(' · ');
    status.textContent = `State: ${data.state || 'unknown'}${services ? ` · ${services}` : ''}`;
    turnOn.disabled = ['starting', 'ready', 'busy'].includes(String(data.state || '').toLowerCase());
    turnOff.disabled = String(data.state || '').toLowerCase() === 'off';
  }

  async function request(path, method = 'GET') {
    status.textContent = 'Updating AmoModel…';
    try {
      const response = await fetch(path, {
        method,
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
      });
      render(await readJson(response));
    } catch (error) {
      status.textContent = `AmoModel unavailable: ${error.message}`;
    }
  }

  turnOn.addEventListener('click', () => request('/api/v1/amomodel/power/on', 'POST'));
  turnOff.addEventListener('click', () => request('/api/v1/amomodel/power/off', 'POST'));
  request('/api/v1/amomodel/status');
})();
