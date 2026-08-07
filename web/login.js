(() => {
  const byId = id => document.getElementById(id);
  const loginTab = byId('login-tab');
  const registerTab = byId('register-tab');
  const loginPanel = byId('login-panel');
  const registerPanel = byId('register-panel');
  const passwordForm = byId('password-login-form');
  const passwordButton = byId('password-login-button');
  const loginUsername = byId('login-username');
  const loginPassword = byId('login-password');
  const qrButton = byId('qr-login-button');
  const qrPanel = byId('qr-login-panel');
  const qrImage = byId('qr-image');
  const qrExpiry = byId('qr-expiry');
  const qrForm = byId('qr-code-form');
  const qrCode = byId('qr-code');
  const qrVerifyButton = byId('qr-verify-button');
  const qrRefreshButton = byId('qr-refresh-button');
  const registerForm = byId('register-form');
  const registerButton = byId('register-button');
  const registerName = byId('register-name');
  const registerUsername = byId('register-username');
  const registerPassword = byId('register-password');
  const message = byId('message');

  if (!loginTab || !registerTab || !passwordForm || !registerForm || !message) return;

  const passkeysAvailable = Boolean(
    window.isSecureContext && window.PublicKeyCredential && navigator.credentials
  );
  let qrChallenge = '';
  let qrBrowserToken = '';
  let qrTimer = null;
  let navigating = false;

  function show(text, kind = '') {
    message.textContent = text || '';
    message.className = `message ${kind}`.trim();
  }

  function username(value) {
    return String(value || '').trim().toLowerCase();
  }

  function address(value) {
    return `${username(value)}@amosclaud.com`;
  }

  async function request(url, options = {}) {
    let response;
    try {
      response = await fetch(url, {
        credentials: 'same-origin',
        cache: 'no-store',
        ...options,
        headers: {'Content-Type': 'application/json', ...(options.headers || {})},
      });
    } catch (_) {
      throw new Error('The Amosclaud server is unavailable. Try again in a moment.');
    }
    const text = await response.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (_) { data = {detail: text}; }
    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map(item => item.msg || item.message).join(' ')
        : data.detail;
      const error = new Error(detail || `Account request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async function verifySession() {
    const response = await fetch('/api/v1/auth/me', {
      credentials: 'same-origin',
      cache: 'no-store',
    });
    if (!response.ok) throw new Error('The session could not be verified. Sign in again.');
  }

  function openWorkspace() {
    if (navigating) return;
    navigating = true;
    show('Success. Opening Amosclaud…', 'success');
    window.location.replace('/cloud/agent');
  }

  function setMode(mode) {
    const registering = mode === 'register';
    loginTab.classList.toggle('active', !registering);
    registerTab.classList.toggle('active', registering);
    loginTab.setAttribute('aria-selected', String(!registering));
    registerTab.setAttribute('aria-selected', String(registering));
    loginPanel.classList.toggle('hidden', registering);
    registerPanel.classList.toggle('hidden', !registering);
    show('');
  }

  function base64urlToBytes(value) {
    const padding = '='.repeat((4 - value.length % 4) % 4);
    const base64 = (value + padding).replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(base64);
    return Uint8Array.from(raw, char => char.charCodeAt(0));
  }

  function bytesToBase64url(value) {
    const bytes = new Uint8Array(value);
    let raw = '';
    bytes.forEach(byte => { raw += String.fromCharCode(byte); });
    return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  }

  function prepareCreationOptions(options) {
    return {
      ...options,
      challenge: base64urlToBytes(options.challenge),
      user: {...options.user, id: base64urlToBytes(options.user.id)},
      excludeCredentials: (options.excludeCredentials || []).map(item => ({
        ...item,
        id: base64urlToBytes(item.id),
      })),
    };
  }

  function serialiseRegistrationCredential(credential) {
    return {
      id: credential.id,
      rawId: bytesToBase64url(credential.rawId),
      type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment,
      clientExtensionResults: credential.getClientExtensionResults(),
      response: {
        clientDataJSON: bytesToBase64url(credential.response.clientDataJSON),
        attestationObject: bytesToBase64url(credential.response.attestationObject),
        transports: credential.response.getTransports ? credential.response.getTransports() : [],
      },
    };
  }

  function stopQrTimer() {
    if (qrTimer) clearInterval(qrTimer);
    qrTimer = null;
  }

  function startQrTimer(seconds) {
    stopQrTimer();
    let remaining = Number(seconds) || 120;
    const render = () => {
      const minutes = Math.floor(remaining / 60);
      const secs = String(Math.max(remaining % 60, 0)).padStart(2, '0');
      qrExpiry.textContent = remaining > 0
        ? `This QR code expires in ${minutes}:${secs}.`
        : 'This QR code expired. Generate a new one.';
      if (remaining <= 0) {
        stopQrTimer();
        qrVerifyButton.disabled = true;
      }
      remaining -= 1;
    };
    render();
    qrTimer = setInterval(render, 1000);
  }

  async function createQrLogin() {
    const requestedUsername = username(loginUsername.value);
    if (!requestedUsername || !loginUsername.reportValidity()) {
      show('Enter your Amosclaud username first.', 'error');
      loginUsername.focus();
      return;
    }
    qrButton.disabled = true;
    qrRefreshButton.disabled = true;
    show('Creating a protected one-time QR code…');
    try {
      const result = await request('/api/v1/auth/login/qr/start', {
        method: 'POST',
        body: JSON.stringify({username: requestedUsername}),
      });
      qrChallenge = result.challenge;
      qrBrowserToken = result.browser_token;
      qrImage.src = `${result.qr_image_url}&v=${Date.now()}`;
      qrPanel.classList.remove('hidden');
      qrCode.value = '';
      qrVerifyButton.disabled = false;
      startQrTimer(result.expires_in_seconds);
      show(result.message || 'Scan the QR code with a trusted Amosclaud device.', 'success');
    } catch (error) {
      show(error.message, 'error');
    } finally {
      qrButton.disabled = false;
      qrRefreshButton.disabled = false;
    }
  }

  loginTab.addEventListener('click', () => setMode('login'));
  registerTab.addEventListener('click', () => setMode('register'));
  qrButton.addEventListener('click', createQrLogin);
  qrRefreshButton.addEventListener('click', createQrLogin);

  passwordForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (!passwordForm.reportValidity()) return;
    passwordButton.disabled = true;
    show('Checking your username and password…');
    try {
      await request('/api/v1/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          email: address(loginUsername.value),
          password: loginPassword.value,
        }),
      });
      await verifySession();
      openWorkspace();
    } catch (error) {
      show(error.status === 401 ? 'Invalid username or password' : error.message, 'error');
    } finally {
      if (!navigating) passwordButton.disabled = false;
    }
  });

  qrForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (!qrForm.reportValidity() || !qrChallenge || !qrBrowserToken) return;
    qrVerifyButton.disabled = true;
    show('Verifying the one-time code…');
    try {
      await request('/api/v1/auth/login/qr/verify', {
        method: 'POST',
        body: JSON.stringify({
          username: username(loginUsername.value),
          challenge: qrChallenge,
          browser_token: qrBrowserToken,
          code: qrCode.value.trim(),
        }),
      });
      stopQrTimer();
      await verifySession();
      openWorkspace();
    } catch (error) {
      show(error.message, 'error');
    } finally {
      if (!navigating) qrVerifyButton.disabled = false;
    }
  });

  registerForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (!registerForm.reportValidity()) return;
    if (!passkeysAvailable) {
      show('Secure account creation requires HTTPS and device confirmation.', 'error');
      return;
    }
    registerButton.disabled = true;
    show('Checking that the username is available…');
    try {
      const selectedUsername = username(registerUsername.value);
      const start = await request('/api/v1/auth/register/passkey/start', {
        method: 'POST',
        body: JSON.stringify({
          name: registerName.value.trim(),
          username: selectedUsername,
          password: registerPassword.value,
        }),
      });
      const credential = await navigator.credentials.create({
        publicKey: prepareCreationOptions(start.public_key),
      });
      if (!credential) throw new Error('Device confirmation was cancelled.');
      await request('/api/v1/auth/register/passkey/finish', {
        method: 'POST',
        body: JSON.stringify({
          username: selectedUsername,
          credential: serialiseRegistrationCredential(credential),
        }),
      });
      await verifySession();
      openWorkspace();
    } catch (error) {
      const cancelled = error?.name === 'NotAllowedError';
      show(cancelled ? 'Device confirmation was cancelled or timed out.' : error.message, 'error');
    } finally {
      if (!navigating) registerButton.disabled = false;
    }
  });

  setMode(new URLSearchParams(window.location.search).get('mode') === 'register' ? 'register' : 'login');

  (async () => {
    try {
      const response = await fetch('/api/v1/auth/me', {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (response.ok) openWorkspace();
    } catch (_) {
      // Stay on the login page when the session probe is unavailable.
    }
  })();
})();
