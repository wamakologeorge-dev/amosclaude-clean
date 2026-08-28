(() => {
  const byId = (id) => document.getElementById(id);
  const message = byId('settings-message');
  let currentOrganizationId = null;
  let scopeCatalog = [];

  function showMessage(text) {
    if (!message) return;
    message.hidden = !text;
    message.textContent = text || '';
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[char]);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    if (response.status === 401) {
      window.location.assign('/login');
      throw new Error('Authentication required');
    }
    if (response.status === 204) return null;
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload.detail === 'string'
        ? payload.detail
        : JSON.stringify(payload.detail || payload.message || payload);
      throw new Error(detail || `Request failed (${response.status})`);
    }
    return payload;
  }

  async function loadDomains() {
    const target = byId('domain-status');
    if (!target) return;
    try {
      const payload = await api('/api/v1/account/domains');
      const domains = payload.domains || [];
      target.textContent = domains.length
        ? domains.map((domain) => `${domain.domain}: ${domain.https ? 'HTTPS verified' : 'HTTP only'}${domain.active ? ' · active' : ''}`).join(' | ')
        : 'No production domains are configured.';
    } catch (error) {
      target.textContent = error.message;
    }
  }

  function renderScopeCatalog() {
    const target = byId('scopeGrid');
    if (!target) return;
    target.innerHTML = scopeCatalog.map((item) => `
      <label>
        <input type="checkbox" value="${escapeHtml(item.scope)}">
        <span><strong>${escapeHtml(item.scope)}</strong><br><small class="muted">${escapeHtml(item.description)}</small></span>
      </label>`).join('');
  }

  async function refreshApplications() {
    if (!currentOrganizationId) return;
    const [applications, installations] = await Promise.all([
      api(`/api/v1/organizations/${currentOrganizationId}/applications`),
      api(`/api/v1/organizations/${currentOrganizationId}/application-installations`),
    ]);

    const appList = byId('appList');
    appList.className = applications.length ? 'cards' : 'empty';
    if (!applications.length) {
      appList.textContent = 'No developer applications in this organization yet.';
    } else {
      appList.innerHTML = applications.map((application) => `
        <article class="card">
          <div class="row"><h3>${escapeHtml(application.name)}</h3><span class="status active">${escapeHtml(application.visibility)}</span></div>
          <div class="muted">${escapeHtml(application.description || 'No description')}</div>
          <div class="chips">${application.requested_scopes.length
            ? application.requested_scopes.map((scope) => `<span class="chip">${escapeHtml(scope)}</span>`).join('')
            : '<span class="muted">No permissions requested</span>'}</div>
          <div style="margin-top:12px"><button class="btn install-app" data-app-id="${application.id}">Install in this organization</button></div>
        </article>`).join('');
      appList.querySelectorAll('.install-app').forEach((button) => {
        button.addEventListener('click', () => {
          const application = applications.find((item) => item.id === Number(button.dataset.appId));
          installApplication(application);
        });
      });
    }

    const installationList = byId('installationList');
    installationList.className = installations.length ? 'cards' : 'empty';
    if (!installations.length) {
      installationList.textContent = 'No applications installed in this organization.';
    } else {
      installationList.innerHTML = installations.map((installation) => `
        <article class="card">
          <div class="row"><h3>${escapeHtml(installation.name)}</h3><span class="status active">installed</span></div>
          <div class="chips">${installation.granted_scopes.map((scope) => `<span class="chip">${escapeHtml(scope)}</span>`).join('')}</div>
          <div style="margin-top:12px"><button class="btn create-token" data-installation-id="${installation.id}" data-name="${escapeHtml(installation.name)}">Create token</button></div>
        </article>`).join('');
      installationList.querySelectorAll('.create-token').forEach((button) => {
        button.addEventListener('click', () => createToken(Number(button.dataset.installationId), button.dataset.name));
      });
    }
  }

  async function installApplication(application) {
    if (!application || !currentOrganizationId) return;
    try {
      await api(`/api/v1/applications/${application.id}/installations`, {
        method: 'POST',
        body: JSON.stringify({
          organization_id: Number(currentOrganizationId),
          granted_scopes: application.requested_scopes,
        }),
      });
      showMessage(`${application.name} installed with the requested scopes. You can reduce scopes through the API before production use.`);
      await refreshApplications();
    } catch (error) {
      showMessage(error.message);
    }
  }

  async function createToken(installationId, applicationName) {
    const tokenName = window.prompt('Token name', `${applicationName} integration`);
    if (!tokenName) return;
    try {
      const created = await api(`/api/v1/installations/${installationId}/tokens`, {
        method: 'POST',
        body: JSON.stringify({ name: tokenName }),
      });
      const notice = byId('tokenNotice');
      notice.innerHTML = `<strong>Copy this token now — Amosclaud will not show the raw value again.</strong><div class="token">${escapeHtml(created.token)}</div>`;
      notice.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (error) {
      showMessage(error.message);
    }
  }

  async function createDeveloperApplication() {
    if (!currentOrganizationId) {
      showMessage('Create or select an organization first.');
      return;
    }
    const requestedScopes = [...byId('scopeGrid').querySelectorAll('input:checked')].map((input) => input.value);
    try {
      await api(`/api/v1/organizations/${currentOrganizationId}/applications`, {
        method: 'POST',
        body: JSON.stringify({
          name: byId('appName').value,
          description: byId('appDescription').value,
          visibility: byId('appVisibility').value,
          requested_scopes: requestedScopes,
        }),
      });
      byId('appForm').classList.remove('open');
      byId('appName').value = '';
      byId('appDescription').value = '';
      byId('scopeGrid').querySelectorAll('input').forEach((input) => { input.checked = false; });
      showMessage('Amosclaud Application created.');
      await refreshApplications();
    } catch (error) {
      showMessage(error.message);
    }
  }

  async function load() {
    try {
      const [user, settings, organizations, scopes] = await Promise.all([
        api('/api/v1/auth/me'),
        api('/api/v1/account/settings'),
        api('/api/v1/organizations'),
        api('/api/v1/integrations/scopes'),
      ]);
      const displayName = user.name || user.email || 'Amosclaud user';
      byId('settings-user').textContent = `${displayName}${user.is_admin ? ' · Administrator' : ''}`;
      byId('profile-summary').textContent = `${displayName}${user.email ? ` · ${user.email}` : ''}`;

      const github = settings.github_connection || {};
      byId('github-status').textContent = github.available
        ? 'GitHub is available as one Amosclaud connector.'
        : 'GitHub OAuth is not configured. Amosclaud Applications remain first-party.';
      byId('github-action').hidden = !github.available;

      const keys = settings.api_keys || {};
      const keysAllowed = keys.available && (!keys.admin_only || settings.is_admin);
      byId('keys-status').textContent = keysAllowed
        ? 'Platform service-key management is available. Application tokens stay installation-scoped.'
        : 'Platform service keys are administrator-restricted; application tokens use organization authorization.';
      byId('keys-action').hidden = !keysAllowed;

      const billing = settings.billing || {};
      byId('billing-status').textContent = billing.available
        ? 'Billing is configured and ready.'
        : 'Billing is not configured on this deployment.';
      byId('billing-action').hidden = !billing.available;
      byId('admin').hidden = !settings.is_admin;

      scopeCatalog = scopes;
      renderScopeCatalog();
      const select = byId('orgSelect');
      if (!organizations.length) {
        select.innerHTML = '<option value="">No organizations</option>';
        byId('appList').textContent = 'Create an organization before creating an Amosclaud Application.';
      } else {
        select.innerHTML = organizations.map((organization) => `<option value="${organization.id}">${escapeHtml(organization.name)} · ${escapeHtml(organization.role)}</option>`).join('');
        currentOrganizationId = organizations[0].id;
        await refreshApplications();
      }
      await loadDomains();
    } catch (error) {
      showMessage(error.message);
    }
  }

  byId('refresh-domains')?.addEventListener('click', loadDomains);
  byId('orgSelect')?.addEventListener('change', async (event) => {
    currentOrganizationId = event.target.value || null;
    await refreshApplications();
  });
  byId('newApp')?.addEventListener('click', () => byId('appForm').classList.toggle('open'));
  byId('createApp')?.addEventListener('click', createDeveloperApplication);
  byId('navToggle')?.addEventListener('click', () => {
    const side = byId('sidebar');
    side.classList.toggle('collapsed');
    byId('navToggle').textContent = side.classList.contains('collapsed') ? 'Show' : 'Hide';
  });

  load();
})();
