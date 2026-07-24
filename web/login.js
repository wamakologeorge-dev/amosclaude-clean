const form = document.getElementById('auth-form');
const loginTab = document.getElementById('login-tab');
const registerTab = document.getElementById('register-tab');
const nameField = document.getElementById('name-field');
const identifierField = document.getElementById('identifier-field');
const usernameField = document.getElementById('username-field');
const nameInput = document.getElementById('name');
const identifierInput = document.getElementById('identifier');
const usernameInput = document.getElementById('username');
const passwordInput = document.getElementById('password');
const emailCodeField = document.getElementById('email-code-field');
const emailCodeInput = document.getElementById('email-code');
const emailCodeButton = document.getElementById('email-code-button');
const passwordHint = document.getElementById('password-hint');
const deviceNote = document.getElementById('device-note');
const submitButton = document.getElementById('submit-button');
const passkeyLoginButton = document.getElementById('passkey-login-button');
const passwordLoginDivider = document.getElementById('password-login-divider');
const title = document.getElementById('auth-title');
const subtitle = document.getElementById('auth-subtitle');
const message = document.getElementById('message');

let mode = 'login';
let emailCodeMode = false;
let navigating = false;
const passkeysAvailable = Boolean(window.isSecureContext && window.PublicKeyCredential && navigator.credentials);

function showMessage(text, success = false) {
  message.textContent = text;
  message.className = success ? 'message success' : 'message';
}

function errorText(detail, fallback = 'Authentication failed') {
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(item => item?.msg || item?.message || JSON.stringify(item)).join(' ');
  return detail.msg || detail.message || fallback;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 15000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {...options, signal: controller.signal});
  } catch (error) {
    if (error?.name === 'AbortError') throw new Error('The server took too long to respond. Please try again.');
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function requestJson(url, options = {}) {
  const response = await fetchWithTimeout(url, {
    credentials: 'same-origin',
    cache: 'no-store',
    ...options,
    headers: {'Content-Type': 'application/json', ...(options.headers || {})},
  });
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch (_) { data = {detail: text}; }
  if (!response.ok) {
    const error = new Error(errorText(data.detail, `Authentication failed (${response.status})`));
    error.status = response.status;
    throw error;
  }
  return data;
}

async function verifySession() {
  const response = await fetchWithTimeout('/api/v1/auth/me', {
    credentials: 'same-origin',
    cache: 'no-store',
  }, 10000);
  if (!response.ok) {
    throw new Error('Your credentials were accepted, but the login session could not be verified. Refresh once and sign in again.');
  }
  return response.json();
}

function openWorkspace() {
  if (navigating) return;
  navigating = true;
  submitButton.disabled = true;
  passkeyLoginButton.disabled = true;
  showMessage('Success. Opening Amosclaud…', true);
  window.location.replace('/cloud/agent');
  setTimeout(() => {
    if (window.location.pathname === '/login') window.location.href = '/cloud/agent';
  }, 1200);
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
  bytes.forEach(byte => raw += String.fromCharCode(byte));
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

function prepareAuthenticationOptions(options) {
  return {
    ...options,
    challenge: base64urlToBytes(options.challenge),
    allowCredentials: (options.allowCredentials || []).map(item => ({...item, id: base64urlToBytes(item.id)})),
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

function serialiseAuthenticationCredential(credential) {
  return {
    id: credential.id,
    rawId: bytesToBase64url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      clientDataJSON: bytesToBase64url(credential.response.clientDataJSON),
      authenticatorData: bytesToBase64url(credential.response.authenticatorData),
      signature: bytesToBase64url(credential.response.signature),
      userHandle: credential.response.userHandle ? bytesToBase64url(credential.response.userHandle) : null,
    },
  };
}

function setMode(nextMode) {
  mode = nextMode;
  const registering = mode === 'register';
  loginTab.classList.toggle('active', !registering);
  registerTab.classList.toggle('active', registering);
  nameField.classList.toggle('hidden', !registering);
  identifierField.classList.toggle('hidden', registering);
  usernameField.classList.toggle('hidden', !registering);
  passwordHint.classList.toggle('hidden', !registering);
  deviceNote.classList.toggle('hidden', !registering || !passkeysAvailable);
  passkeyLoginButton.classList.toggle('hidden', registering || !passkeysAvailable);
  passwordLoginDivider.classList.toggle('hidden', registering || !passkeysAvailable);
  emailCodeButton.classList.toggle('hidden', registering);
  emailCodeMode = false;
  emailCodeField.classList.add('hidden');
  emailCodeInput.required = false;
  passwordInput.closest('label').classList.remove('hidden');

  nameInput.required = registering;
  usernameInput.required = registering;
  identifierInput.required = !registering;
  passwordInput.required = true;
  passwordInput.minLength = registering ? 10 : 1;
  passwordInput.autocomplete = registering ? 'new-password' : 'current-password';

  if (registering) {
    title.textContent = 'Create your Amosclaud account';
    subtitle.textContent = passkeysAvailable
      ? 'Choose your Amosclaud username, password, and secure device confirmation.'
      : 'Account creation with device confirmation requires HTTPS. Password sign-in remains available on this server.';
    submitButton.textContent = passkeysAvailable ? 'Create account securely' : 'HTTPS required for account creation';
    submitButton.disabled = !passkeysAvailable;
  } else {
    title.textContent = 'Welcome back';
    subtitle.textContent = passkeysAvailable
      ? 'Use your passkey, email code, or Amosclaud password.'
      : 'Use your Amosclaud email or username and password.';
    submitButton.textContent = 'Sign in with password';
    submitButton.disabled = false;
  }
  showMessage('');
}

loginTab.addEventListener('click', () => setMode('login'));
registerTab.addEventListener('click', () => setMode('register'));

emailCodeButton.addEventListener('click', async () => {
  let mail = identifierInput.value.trim().toLowerCase();
  if (!mail) {
    showMessage('Enter your email address first.');
    identifierInput.focus();
    return;
  }
  if (!mail.includes('@')) mail += '@amosclaud.com';
  emailCodeButton.disabled = true;
  try {
    const result = await requestJson('/api/v1/auth/login/request-code', {
      method: 'POST',
      body: JSON.stringify({email: mail}),
    });
    emailCodeMode = true;
    passwordInput.required = false;
    passwordInput.closest('label').classList.add('hidden');
    emailCodeField.classList.remove('hidden');
    emailCodeInput.required = true;
    submitButton.textContent = 'Verify code and sign in';
    showMessage(result.message, true);
    emailCodeInput.focus();
  } catch (error) {
    showMessage(error.message);
  } finally {
    emailCodeButton.disabled = false;
  }
});

passkeyLoginButton.addEventListener('click', async () => {
  showMessage('Waiting for fingerprint or device confirmation…', true);
  passkeyLoginButton.disabled = true;
  try {
    if (!passkeysAvailable) throw new Error('Passkey sign-in requires HTTPS. Use your password instead.');
    const start = await requestJson('/api/v1/auth/login/passkey/start', {method: 'POST', body: '{}'});
    const credential = await navigator.credentials.get({publicKey: prepareAuthenticationOptions(start.public_key)});
    if (!credential) throw new Error('Fingerprint sign-in was cancelled.');
    await requestJson('/api/v1/auth/login/passkey/finish', {
      method: 'POST',
      body: JSON.stringify({attempt: start.attempt, credential: serialiseAuthenticationCredential(credential)}),
    });
    await verifySession();
    openWorkspace();
  } catch (error) {
    const cancelled = error?.name === 'NotAllowedError';
    showMessage(cancelled ? 'Fingerprint or device confirmation was cancelled.' : error.message);
  } finally {
    if (!navigating) passkeyLoginButton.disabled = false;
  }
});

form.addEventListener('submit', async event => {
  event.preventDefault();
  showMessage('');
  if (!form.reportValidity()) return;

  if (mode === 'register' && !passkeysAvailable) {
    showMessage('Account creation with a passkey requires HTTPS. Sign in with an existing password account or enable HTTPS.');
    return;
  }

  submitButton.disabled = true;
  submitButton.textContent = mode === 'login' ? 'Signing in…' : 'Checking account…';
  try {
    if (mode === 'login') {
      let mail = identifierInput.value.trim().toLowerCase();
      if (!mail.includes('@')) mail += '@amosclaud.com';
      if (emailCodeMode) {
        await requestJson('/api/v1/auth/login/verify-code', {
          method: 'POST',
          body: JSON.stringify({email: mail, code: emailCodeInput.value.trim()}),
        });
      } else {
        await requestJson('/api/v1/auth/login', {
          method: 'POST',
          body: JSON.stringify({email: mail, password: passwordInput.value}),
        });
      }
      await verifySession();
      openWorkspace();
      return;
    }

    const username = usernameInput.value.trim().toLowerCase();
    const address = `${username}@amosclaud.com`;
    try {
      await requestJson('/api/v1/auth/login', {
        method: 'POST',
        body: JSON.stringify({email: address, password: passwordInput.value}),
      });
      await verifySession();
      showMessage(`Welcome back, ${address}. Opening Amosclaud…`, true);
      openWorkspace();
      return;
    } catch (loginError) {
      if (loginError.status !== 401) throw loginError;
    }

    showMessage('No existing account matched. Creating your account…', true);
    const start = await requestJson('/api/v1/auth/register/passkey/start', {
      method: 'POST',
      body: JSON.stringify({name: nameInput.value.trim(), username, password: passwordInput.value}),
    });
    const credential = await navigator.credentials.create({publicKey: prepareCreationOptions(start.public_key)});
    if (!credential) throw new Error('Device confirmation was cancelled.');
    const finished = await requestJson('/api/v1/auth/register/passkey/finish', {
      method: 'POST',
      body: JSON.stringify({username, credential: serialiseRegistrationCredential(credential)}),
    });
    await verifySession();
    showMessage(`Account ready: ${finished.address}. Opening Amosclaud…`, true);
    openWorkspace();
  } catch (error) {
    const cancelled = error?.name === 'NotAllowedError';
    showMessage(cancelled ? 'Device confirmation was cancelled or timed out. Try again.' : error.message);
  } finally {
    if (!navigating) {
      submitButton.disabled = mode === 'register' && !passkeysAvailable;
      submitButton.textContent = mode === 'login'
        ? (emailCodeMode ? 'Verify code and sign in' : 'Sign in with password')
        : (passkeysAvailable ? 'Create account securely' : 'HTTPS required for account creation');
    }
  }
});

(async () => {
  try {
    const response = await fetchWithTimeout('/api/v1/auth/me', {credentials: 'same-origin', cache: 'no-store'}, 5000);
    if (response.ok) openWorkspace();
  } catch (_) {
    // Stay on the login page when the session probe is unavailable.
  }
})();
