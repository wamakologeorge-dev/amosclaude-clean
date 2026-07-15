(() => {
  const form = document.getElementById('auth-form');
  const identifier = document.getElementById('identifier');
  const username = document.getElementById('username');
  const name = document.getElementById('name');
  const password = document.getElementById('password');
  const registerTab = document.getElementById('register-tab');
  const submitButton = document.getElementById('submit-button');
  const message = document.getElementById('message');
  if (!form || !identifier || !username || !name || !password || !registerTab || !submitButton || !message) return;

  function showMessage(text, success = false) {
    message.textContent = text;
    message.className = success ? 'message success' : 'message';
  }

  function canonicalAddress(value) {
    const address = String(value || '').trim().toLowerCase();
    if (!address.includes('@')) return address;
    const [local, domain] = address.split('@', 2);
    return domain === 'www.amosclaud.com' ? `${local}@amosclaud.com` : address;
  }

  async function request(url, options = {}) {
    const response = await fetch(url, {
      credentials: 'same-origin',
      cache: 'no-store',
      ...options,
      headers: {'Content-Type': 'application/json', ...(options.headers || {})},
    });
    const text = await response.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (_) { data = {detail: text}; }
    return {response, data};
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
      excludeCredentials: (options.excludeCredentials || []).map(item => ({...item, id: base64urlToBytes(item.id)})),
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

  function openWorkspace() {
    showMessage('Success. Opening Amosclaud…', true);
    window.location.replace('/');
  }

  form.addEventListener('submit', async event => {
    const corrected = canonicalAddress(identifier.value);
    if (corrected !== identifier.value.trim().toLowerCase()) identifier.value = corrected;

    // The normal sign-in handler remains unchanged. The create-account form is
    // upgraded into a unified "create or reconnect" flow.
    if (!registerTab.classList.contains('active')) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    if (!form.reportValidity()) return;

    const selectedUsername = username.value.trim().toLowerCase();
    const address = `${selectedUsername}@amosclaud.com`;
    submitButton.disabled = true;
    submitButton.textContent = 'Checking account…';

    try {
      // First, treat the signup fields as login credentials. This prevents
      // users from creating repeated accounts when the account already exists.
      const login = await request('/api/v1/auth/login', {
        method: 'POST',
        body: JSON.stringify({email: address, password: password.value}),
      });
      if (login.response.ok) {
        showMessage(`Welcome back, ${address}.`, true);
        openWorkspace();
        return;
      }
      if (login.response.status !== 401) {
        throw new Error(login.data.detail || 'Amosclaud could not check this account.');
      }

      if (!window.PublicKeyCredential || !navigator.credentials) {
        throw new Error('No existing account matched, and this browser cannot create a secure device key.');
      }

      submitButton.textContent = 'Creating account…';
      showMessage('No matching account was found. Creating it once now…', true);
      const start = await request('/api/v1/auth/register/passkey/start', {
        method: 'POST',
        body: JSON.stringify({name: name.value.trim(), username: selectedUsername, password: password.value}),
      });
      if (!start.response.ok) throw new Error(start.data.detail || 'Account setup could not start.');

      const credential = await navigator.credentials.create({publicKey: prepareCreationOptions(start.data.public_key)});
      if (!credential) throw new Error('Device confirmation was cancelled.');

      const finish = await request('/api/v1/auth/register/passkey/finish', {
        method: 'POST',
        body: JSON.stringify({username: selectedUsername, credential: serialiseRegistrationCredential(credential)}),
      });
      if (!finish.response.ok) throw new Error(finish.data.detail || 'Account setup could not finish.');
      showMessage(`Account ready: ${finish.data.address}. Opening Amosclaud…`, true);
      openWorkspace();
    } catch (error) {
      showMessage(error?.message || 'Authentication failed.');
      submitButton.disabled = false;
      submitButton.textContent = 'Continue securely';
    }
  }, true);

  const stalePasskeyPattern = /not linked to an Amosclaud account/i;
  const observer = new MutationObserver(() => {
    if (stalePasskeyPattern.test(message.textContent || '')) {
      message.textContent = 'This saved device key belongs to an older account record. Use Continue securely with the same Amosclaud username and password. Amosclaud will sign you in when the account exists, or create it only once when it does not.';
      message.className = 'message';
    }
  });
  observer.observe(message, {childList: true, characterData: true, subtree: true});
})();