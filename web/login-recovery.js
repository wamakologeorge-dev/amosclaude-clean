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
    if (!address.includes('@')) return `${address}@amosclaud.com`;
    const [local, domain] = address.split('@', 2);
    return domain === 'www.amosclaud.com' ? `${local}@amosclaud.com` : address;
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
      throw new Error('Amosclaud could not reach the authentication server. Check the deployment health and try again.');
    }
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
    window.location.replace('/cloud/agent');
  }

  async function passwordLogin(address) {
    return request('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({email: address, password: password.value}),
    });
  }

  form.addEventListener('submit', async event => {
    if (!registerTab.classList.contains('active')) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    if (!form.reportValidity()) return;

    const selectedUsername = username.value.trim().toLowerCase();
    const address = `${selectedUsername}@amosclaud.com`;
    submitButton.disabled = true;
    submitButton.textContent = 'Checking account…';

    try {
      // Ask the registration endpoint first. A 409 proves the account exists;
      // only then do we attempt password sign-in. A wrong password can never
      // silently create a second account.
      const start = await request('/api/v1/auth/register/passkey/start', {
        method: 'POST',
        body: JSON.stringify({name: name.value.trim(), username: selectedUsername, password: password.value}),
      });

      if (start.response.status === 409) {
        const login = await passwordLogin(address);
        if (!login.response.ok) {
          if (login.response.status === 429) {
            throw new Error('Sign-in is temporarily locked after repeated attempts. Use Forgot password or wait for the displayed retry period.');
          }
          throw new Error('This account already exists, but the password did not match. Use Forgot password. Amosclaud will not create another account.');
        }
        showMessage(`Welcome back, ${address}.`, true);
        openWorkspace();
        return;
      }

      if (!start.response.ok) throw new Error(start.data.detail || 'Amosclaud could not check this account.');
      if (!window.PublicKeyCredential || !navigator.credentials) {
        throw new Error('This is a new account, but this browser cannot create its secure device key.');
      }

      submitButton.textContent = 'Creating account…';
      showMessage('New username confirmed. Creating this account once…', true);
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

  const forgot = document.createElement('button');
  forgot.type = 'button';
  forgot.className = 'tab';
  forgot.style.marginTop = '12px';
  forgot.textContent = 'Forgot password?';
  form.insertAdjacentElement('afterend', forgot);

  forgot.addEventListener('click', async () => {
    const suggested = canonicalAddress(identifier.value || username.value);
    const address = window.prompt('Enter your Amosclaud mail address', suggested || '');
    if (!address) return;
    try {
      const sent = await request('/api/v1/auth/password/forgot', {
        method: 'POST',
        body: JSON.stringify({email: canonicalAddress(address)}),
      });
      if (!sent.response.ok) throw new Error(sent.data.detail || 'Password recovery could not start.');
      const code = window.prompt('Enter the 6-digit reset code sent by Amosclaud');
      if (!code) return;
      const nextPassword = window.prompt('Enter a new password with at least 10 characters');
      if (!nextPassword) return;
      const reset = await request('/api/v1/auth/password/reset', {
        method: 'POST',
        body: JSON.stringify({email: canonicalAddress(address), code: code.trim(), password: nextPassword}),
      });
      if (!reset.response.ok) throw new Error(reset.data.detail || 'Password reset failed.');
      identifier.value = canonicalAddress(address);
      password.value = nextPassword;
      document.getElementById('login-tab')?.click();
      showMessage('Password changed. Sign in with the new password.', true);
    } catch (error) {
      showMessage(error?.message || 'Password recovery failed.');
    }
  });

  const stalePasskeyPattern = /not linked to an Amosclaud account/i;
  const observer = new MutationObserver(() => {
    if (stalePasskeyPattern.test(message.textContent || '')) {
      message.textContent = 'This device key is stale. Sign in with the matching Amosclaud mail and password, or use Forgot password. Do not create another account.';
      message.className = 'message';
    }
  });
  observer.observe(message, {childList: true, characterData: true, subtree: true});
})();