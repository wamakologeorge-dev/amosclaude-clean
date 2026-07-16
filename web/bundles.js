(() => {
  const form = document.getElementById('bundle-form');
  const list = document.getElementById('bundle-list');
  const count = document.getElementById('bundle-count');
  const status = document.getElementById('bundle-status');
  const refresh = document.getElementById('refresh-bundles');
  const type = document.getElementById('bundle-type');
  const entrypoint = document.getElementById('bundle-entrypoint');

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[char]);

  const formatBytes = (bytes) => {
    const value = Number(bytes || 0);
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  };

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    if (response.status === 401) {
      window.location.assign('/login');
      throw new Error('Authentication required');
    }
    const body = response.status === 204 ? {} : await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
    return body;
  }

  function renderBundle(bundle) {
    const files = Array.isArray(bundle.files) ? bundle.files.length : 0;
    const hash = bundle.archive_sha256 || 'pending';
    return `
      <article class="bundle-card">
        <div class="bundle-card-head">
          <div><h3>${escapeHtml(bundle.name)}</h3><p>${escapeHtml(bundle.description || 'No description')}</p></div>
          <span>${escapeHtml(bundle.bundle_type)}</span>
        </div>
        <dl>
          <div><dt>Version</dt><dd>${escapeHtml(bundle.version)}</dd></div>
          <div><dt>Files</dt><dd>${files}</dd></div>
          <div><dt>Source size</dt><dd>${formatBytes(bundle.source_bytes)}</dd></div>
          <div><dt>Created</dt><dd>${escapeHtml(new Date(bundle.created_at).toLocaleString())}</dd></div>
        </dl>
        <div class="bundle-hash"><strong>SHA-256</strong><code title="${escapeHtml(hash)}">${escapeHtml(hash)}</code></div>
        <div class="bundle-actions">
          <a href="/api/v1/bundles/${encodeURIComponent(bundle.bundle_id)}/download">Download .amosbundle</a>
          <button type="button" data-copy="${escapeHtml(hash)}">Copy hash</button>
        </div>
      </article>`;
  }

  async function loadBundles() {
    list.innerHTML = '<p class="empty-state">Loading bundles…</p>';
    try {
      const data = await api('/api/v1/bundles');
      const bundles = Array.isArray(data.bundles) ? data.bundles : [];
      count.textContent = String(bundles.length);
      list.innerHTML = bundles.length ? bundles.map(renderBundle).join('') : '<p class="empty-state">No bundles yet. Create your first portable package.</p>';
    } catch (error) {
      list.innerHTML = `<p class="empty-state error">${escapeHtml(error.message)}</p>`;
    }
  }

  type.addEventListener('change', () => {
    entrypoint.required = type.value === 'deployment';
    entrypoint.placeholder = entrypoint.required ? 'Required, for example: python -m app' : 'Optional entrypoint';
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = document.getElementById('create-bundle');
    button.disabled = true;
    status.textContent = 'Creating secure bundle…';
    try {
      const payload = {
        name: document.getElementById('bundle-name').value.trim(),
        version: document.getElementById('bundle-version').value.trim(),
        bundle_type: type.value,
        source_path: document.getElementById('bundle-source').value.trim() || null,
        entrypoint: entrypoint.value.trim() || null,
        description: document.getElementById('bundle-description').value.trim(),
        metadata: { source: 'amosclaud-bundles-dashboard' },
      };
      const data = await api('/api/v1/bundles', { method: 'POST', body: JSON.stringify(payload) });
      status.textContent = `Created ${data.bundle.name} ${data.bundle.version}.`;
      form.reset();
      document.getElementById('bundle-version').value = '0.1.0';
      type.dispatchEvent(new Event('change'));
      await loadBundles();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  });

  list.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-copy]');
    if (!button) return;
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      button.textContent = 'Copied';
      setTimeout(() => { button.textContent = 'Copy hash'; }, 1200);
    } catch {
      button.textContent = 'Copy failed';
    }
  });

  refresh.addEventListener('click', loadBundles);
  type.dispatchEvent(new Event('change'));
  loadBundles();
})();
