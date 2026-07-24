(() => {
  const userLabel = document.getElementById('current-user');
  const logoutButtons = document.querySelectorAll('#btn-logout,[data-account-logout]');
  const menuButton = document.getElementById('account-menu-button');
  const drawer = document.getElementById('account-drawer');
  const backdrop = document.getElementById('account-drawer-backdrop');

  function initials(value) {
    return String(value || 'A').trim().split(/\s+/).map(part => part[0]).join('').slice(0, 2).toUpperCase() || 'A';
  }

  function setDrawer(open) {
    if (!drawer) return;
    drawer.hidden = !open;
    backdrop?.toggleAttribute('hidden', !open);
    menuButton?.setAttribute('aria-expanded', String(open));
  }

  async function loadUser() {
    try {
      const response = await fetch('/api/v1/auth/me', { credentials: 'same-origin', cache: 'no-store' });
      if (response.status === 401) return window.location.assign('/login');
      if (!response.ok) throw new Error(`Profile unavailable (${response.status})`);
      const user = await response.json();
      const displayName = user.name || user.email || 'Amosclaud user';
      if (userLabel) userLabel.textContent = displayName;
      document.querySelectorAll('[data-profile-name]').forEach(element => { element.textContent = displayName; });
      document.querySelectorAll('[data-profile-email]').forEach(element => { element.textContent = user.email || 'Email unavailable'; });
      document.querySelectorAll('[data-profile-avatar]').forEach(element => { element.textContent = initials(displayName); });
      document.querySelectorAll('[data-profile-role]').forEach(element => { element.textContent = user.is_admin ? 'Administrator' : 'Member'; });
      document.querySelectorAll('[data-admin-only]').forEach(element => { element.hidden = !user.is_admin; });
    } catch (error) {
      document.querySelectorAll('[data-profile-status]').forEach(element => { element.textContent = error.message; });
    }
  }

  async function logout() {
    try {
      await fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'same-origin' });
    } finally {
      window.location.assign('/login');
    }
  }

  menuButton?.addEventListener('click', () => setDrawer(drawer?.hidden !== false));
  backdrop?.addEventListener('click', () => setDrawer(false));
  document.addEventListener('keydown', event => { if (event.key === 'Escape') setDrawer(false); });
  logoutButtons.forEach(button => button.addEventListener('click', logout));
  loadUser();
})();
