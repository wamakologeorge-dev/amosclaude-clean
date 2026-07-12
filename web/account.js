(() => {
  const userLabel = document.getElementById('current-user');
  const logoutButton = document.getElementById('btn-logout');

  async function loadUser() {
    try {
      const response = await fetch('/api/v1/auth/me', { credentials: 'same-origin' });
      if (response.status === 401) return window.location.assign('/login');
      const user = await response.json();
      if (userLabel) userLabel.textContent = user.name || user.email;
      document.querySelectorAll('[data-admin-only]').forEach(element => {
        element.hidden = !user.is_admin;
      });
    } catch (_) {}
  }

  logoutButton?.addEventListener('click', async () => {
    try {
      await fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'same-origin' });
    } finally {
      window.location.assign('/login');
    }
  });

  loadUser();
})();
