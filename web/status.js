(() => {
  const componentList = document.getElementById('component-list');
  const overallStatus = document.getElementById('overall-status');
  const overallIndicator = document.getElementById('overall-indicator');
  const refreshButton = document.getElementById('refresh-status');
  const lastChecked = document.getElementById('last-checked');
  const statusError = document.getElementById('status-error');

  const labels = {
    operational: 'Operational',
    degraded: 'Degraded',
    not_configured: 'Not configured',
    unreachable: 'Unreachable',
    unknown: 'Unknown',
  };

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;',
  })[character]);

  function renderComponents(components) {
    const safeComponents = Array.isArray(components) ? components : [];
    componentList.innerHTML = safeComponents.length
      ? safeComponents.map((component) => {
        const state = labels[component.state] ? component.state : 'unknown';
        return `<li class="component-card" data-state="${escapeHtml(state)}">
          <div class="component-head">
            <strong>${escapeHtml(component.name)}</strong>
            <span class="state">${escapeHtml(labels[state])}</span>
          </div>
          <p>${escapeHtml(component.summary)}</p>
        </li>`;
      }).join('')
      : '<li class="loading">No public component checks were returned.</li>';
  }

  async function loadStatus() {
    refreshButton.disabled = true;
    statusError.hidden = true;
    try {
      const response = await fetch('/api/v1/public/status', {
        credentials: 'omit',
        cache: 'no-store',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        throw new Error(`Status request failed with HTTP ${response.status}`);
      }
      const data = await response.json();
      const operational = data.status === 'operational';
      overallStatus.textContent = operational
        ? 'All public checks are operational'
        : 'Amosclaud is online with one or more limited components';
      overallIndicator.textContent = operational ? '●' : '◐';
      document.getElementById('version').textContent = data.version || 'Unknown';
      document.getElementById('environment').textContent = data.environment || 'Unknown';
      document.getElementById('source').textContent = data.source_repository || 'wamakologeorge-dev/amosclaude-clean';
      const checkedAt = data.updated_at ? new Date(data.updated_at) : new Date();
      lastChecked.textContent = `Last checked ${checkedAt.toLocaleString()}`;
      renderComponents(data.components);
    } catch (error) {
      overallStatus.textContent = 'Public status could not be loaded';
      overallIndicator.textContent = '▲';
      componentList.innerHTML = '<li class="loading">The public status endpoint did not respond.</li>';
      statusError.hidden = false;
      statusError.textContent = error.message || 'Status request failed.';
      lastChecked.textContent = `Last attempted ${new Date().toLocaleString()}`;
    } finally {
      refreshButton.disabled = false;
    }
  }

  refreshButton.addEventListener('click', loadStatus);
  loadStatus();
  window.setInterval(loadStatus, 30_000);
})();
