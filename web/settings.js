(() => {
  const message = document.getElementById('settings-message');

  function showMessage(text) {
    if (!message) return;
    message.hidden = !text;
    message.textContent = text || '';
  }

  async function api(path) {
    const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store' });
    if (response.status === 401) {
      window.location.assign('/login');
      throw new Error('Authentication required');
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || payload.message || `Request failed (${response.status})`);
    return payload;
  }

  async function loadDomains() {
    const target = document.getElementById('domain-status');
    try {
      const payload = await api('/api/v1/account/domains');
      const domains = payload.domains || [];
      target.textContent = domains.length
        ? domains.map(domain => `${domain.domain}: ${domain.https ? 'HTTPS verified' : 'HTTP only'}${domain.active ? ' · active' : ''}`).join(' | ')
        : 'No production domains are configured.';
    } catch (error) {
      target.textContent = error.message;
    }
  }

  async function load() {
    try {
      const [user, settings] = await Promise.all([
        api('/api/v1/auth/me'),
        api('/api/v1/account/settings'),
      ]);
      const displayName = user.name || user.email || 'Amosclaud user';
      document.getElementById('settings-user').textContent = `${displayName}${user.is_admin ? ' · Administrator' : ''}`;
      document.getElementById('profile-summary').textContent = `${displayName}${user.email ? ` · ${user.email}` : ''}`;

      const github = settings.github_connection || {};
      document.getElementById('github-status').textContent = github.available
        ? 'GitHub OAuth is configured and ready.'
        : 'GitHub OAuth is not configured on this deployment.';
      document.getElementById('github-action').hidden = !github.available;

      const keys = settings.api_keys || {};
      const keysAllowed = keys.available && (!keys.admin_only || settings.is_admin);
      document.getElementById('keys-status').textContent = keysAllowed
        ? 'Service-key management is available for this account.'
        : 'Service-key management is restricted to administrators.';
      document.getElementById('keys-action').hidden = !keysAllowed;

      const billing = settings.billing || {};
      document.getElementById('billing-status').textContent = billing.available
        ? 'Billing is configured and ready.'
        : 'Billing is not configured yet. Stripe credentials are required on Railway.';
      document.getElementById('billing-action').hidden = !billing.available;

      document.getElementById('admin').hidden = !settings.is_admin;
      await loadDomains();
    } catch (error) {
      showMessage(error.message);
    }
  }

  document.getElementById('refresh-domains')?.addEventListener('click', loadDomains);
  load();
})();
