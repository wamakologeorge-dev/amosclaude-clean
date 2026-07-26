(() => {
  const modal = document.getElementById('modal-repository');
  const createButton = document.getElementById('btn-create-repository');
  const confirmButton = document.getElementById('btn-confirm-repository');
  if (!modal || !createButton || !confirmButton) return;

  const visibilityLabel = document.getElementById('repository-visibility-input')?.closest('label');
  const ownerLabel = document.createElement('label');
  ownerLabel.id = 'github-owner-label';
  ownerLabel.innerHTML = `GitHub owner
    <select id="repository-github-owner-input" disabled>
      <option value="">Loading GitHub owners…</option>
    </select>
    <small id="repository-github-owner-note">Choose your personal account or an organization that authorized Amosclaud.</small>`;
  visibilityLabel?.before(ownerLabel);

  const ownerInput = ownerLabel.querySelector('select');
  const ownerNote = ownerLabel.querySelector('small');
  let targetsLoaded = false;

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function toast(message, type = 'info') {
    if (typeof window.showToast === 'function') {
      window.showToast(message, type);
      return;
    }
    const node = document.createElement('div');
    node.className = `toast toast--${type}`;
    node.textContent = message;
    (document.getElementById('toast-container') || document.body).appendChild(node);
    setTimeout(() => node.remove(), 5000);
  }

  async function request(path, options = {}) {
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
    try { payload = text ? JSON.parse(text) : null; } catch { payload = { detail: text }; }
    if (!response.ok) throw new Error(payload?.detail || `Request failed (${response.status})`);
    return payload;
  }

  async function loadTargets(force = false) {
    if (targetsLoaded && !force) return;
    ownerInput.disabled = true;
    ownerInput.innerHTML = '<option value="">Loading GitHub owners…</option>';
    ownerNote.textContent = 'Checking the organizations available to your GitHub authorization.';
    try {
      const result = await request('/api/v1/github/organizations');
      const targets = Array.isArray(result.targets) ? result.targets : [];
      ownerInput.innerHTML = targets.map(target => (
        `<option value="${escapeHtml(target.login)}">${escapeHtml(target.login)} · ${target.kind === 'organization' ? 'organization' : 'personal account'}</option>`
      )).join('');
      ownerInput.disabled = targets.length === 0;
      targetsLoaded = targets.length > 0;
      if (result.reconnect_required) {
        ownerNote.innerHTML = 'Organization visibility or workflow publishing is not fully authorized. <a href="/api/v1/github/connect-organizations">Reconnect GitHub for organization publishing</a>.';
      } else {
        ownerNote.textContent = result.permission_note || 'GitHub verifies your permission when the repository is created.';
      }
    } catch (error) {
      ownerInput.innerHTML = '<option value="">GitHub reconnect required</option>';
      ownerNote.innerHTML = `${escapeHtml(error.message)} <a href="/api/v1/github/connect-organizations">Reconnect GitHub</a>.`;
    }
  }

  createButton.addEventListener('click', () => { loadTargets(); });

  confirmButton.addEventListener('click', async event => {
    event.preventDefault();
    event.stopImmediatePropagation();

    const name = document.getElementById('repository-name-input')?.value.trim();
    if (!name) return toast('Repository name is required', 'error');
    if (!ownerInput.value) return toast('Choose an authorized GitHub owner', 'error');

    confirmButton.disabled = true;
    confirmButton.textContent = 'Creating and pushing…';
    try {
      const repository = await request('/api/v1/repositories/create-real', {
        method: 'POST',
        body: JSON.stringify({
          name,
          owner: ownerInput.value,
          description: document.getElementById('repository-description-input')?.value.trim() || '',
          visibility: document.getElementById('repository-visibility-input')?.value || 'private',
          initialize_readme: Boolean(document.getElementById('repository-readme-input')?.checked),
          initialize_gitignore: Boolean(document.getElementById('repository-gitignore-input')?.checked),
          license: document.getElementById('repository-license-input')?.value || 'none',
        }),
      });
      localStorage.setItem('amosclaud-last-repository-id', String(repository.id));
      localStorage.setItem('amosclaud-last-repository-name', repository.github_full_name || repository.name);
      toast(`Created and pushed ${repository.github_full_name} with Amosclaud CI`, 'success');
      window.location.assign(repository.workspace_url || `/workspace/${encodeURIComponent(repository.id)}`);
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      confirmButton.disabled = false;
      confirmButton.textContent = 'Create repository';
    }
  }, true);
})();
