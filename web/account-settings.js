(() => {
  const message = document.getElementById('message');
  const logoutCurrent = document.getElementById('logout-current');
  const logoutAll = document.getElementById('logout-all');
  const deleteForm = document.getElementById('delete-account-form');
  let currentUser = null;

  function setMessage(text, kind = '') {
    message.textContent = text;
    message.className = `message ${kind}`.trim();
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    if (response.status === 401) {
      window.location.assign('/login');
      throw new Error('Sign in required');
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed with HTTP ${response.status}`);
    }
    return response.status === 204 ? null : response.json();
  }

  function renderTools(settings) {
    const tools = [
      '<li><a href="/status">View public platform status</a></li>',
      '<li><a href="/repositories">Manage repositories</a></li>',
      '<li><a href="/plans">View plans and billing</a></li>',
    ];
    if (settings.github_connection?.available) {
      tools.push('<li><a href="/api/v1/auth/github/link">Connect GitHub account</a></li>');
    } else {
      tools.push('<li>GitHub connection is not configured on this deployment.</li>');
    }
    if (settings.is_admin) {
      tools.push('<li><a href="/admin">Open administrator controls</a></li>');
    }
    document.getElementById('tool-list').innerHTML = tools.join('');
  }

  async function loadAccount() {
    const [user, settings] = await Promise.all([
      request('/api/v1/auth/me'),
      request('/api/v1/account/settings'),
    ]);
    currentUser = user;
    document.getElementById('profile-name').textContent = user.name;
    document.getElementById('profile-email').textContent = user.email;
    document.getElementById('profile-provider').textContent = user.provider;
    document.getElementById('profile-role').textContent = user.is_admin
      ? 'Administrator'
      : 'Member';
    document.getElementById('delete-confirmation').placeholder = user.email;
    renderTools(settings);
    setMessage('Account controls are ready.', 'success');
  }

  async function signOut(path, button) {
    button.disabled = true;
    try {
      await request(path, { method: 'POST' });
      window.location.assign('/login');
    } catch (error) {
      setMessage(error.message || 'Sign out failed.', 'error');
      button.disabled = false;
    }
  }

  logoutCurrent.addEventListener('click', () => {
    signOut('/api/v1/auth/logout', logoutCurrent);
  });

  logoutAll.addEventListener('click', () => {
    signOut('/api/v1/account/logout-all', logoutAll);
  });

  deleteForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!currentUser) return;
    const confirmation = document
      .getElementById('delete-confirmation')
      .value.trim();
    const password = document.getElementById('delete-password').value;
    if (confirmation.toLowerCase() !== currentUser.email.toLowerCase()) {
      setMessage(
        'Type your account email exactly before deleting the account.',
        'error',
      );
      return;
    }
    const submit = deleteForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await request('/api/v1/account', {
        method: 'DELETE',
        body: JSON.stringify({ confirmation, password: password || null }),
      });
      window.location.assign('/login?account=deleted');
    } catch (error) {
      setMessage(error.message || 'Account deletion failed.', 'error');
      submit.disabled = false;
    }
  });

  loadAccount().catch((error) => {
    setMessage(error.message || 'Account could not be loaded.', 'error');
  });
})();
