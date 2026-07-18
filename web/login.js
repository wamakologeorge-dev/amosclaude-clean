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
const passwordHint = document.getElementById('password-hint');
const deviceNote = document.getElementById('device-note');
const submitButton = document.getElementById('submit-button');
const passkeyLoginButton = document.getElementById('passkey-login-button');
const passwordLoginDivider = document.getElementById('password-login-divider');
const title = document.getElementById('auth-title');
const subtitle = document.getElementById('auth-subtitle');
const message = document.getElementById('message');

let mode = 'login';

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

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'same-origin',
    ...options,
    headers: {'Content-Type': 'application/json', ...(options.headers || {})},
  });
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch (_) { data = {detail: text}; }
  if (!response.ok) throw new Error(errorText(data.detail));
  return data;
}

async function verifySession() {
  const response = await fetch('/api/v1/auth/me', {
    credentials: 'same-origin',
    cache: 'no-store',
  });
  if (!response.ok) {
    throw new Error('Your account was accepted, but Amosclaud could not keep the login session. Use only www.amosclaud.com and check the persistent /data volume.');
  }
  return response.json();
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
  deviceNote.classList.toggle('hidden', !registering);
  passkeyLoginButton.classList.toggle('hidden', registering);
  passwordLoginDivider.classList.toggle('hidden', registering);

  nameInput.required = registering;
  usernameInput.required = registering;
  identifierInput.required = !registering;
  passwordInput.minLength = registering ? 10 : 1;
  passwordInput.autocomplete = registering ? 'new-password' : 'current-password';

  if (registering) {
    title.textContent = 'Create your Amosclaud account';
    subtitle.textContent = 'Choose your @amosclaud.com mail address and confirm on this device.';
    submitButton.textContent = 'Create account securely';
  } else {
    title.textContent = 'Welcome back';
    subtitle.textContent = 'Use your fingerprint, device security, or Amosclaud mail and password.';
    submitButton.textContent = 'Sign in with password';
  }
  showMessage('');
}

loginTab.addEventListener('click', () => setMode('login'));
registerTab.addEventListener('click', () => setMode('register'));

passkeyLoginButton.addEventListener('click', async () => {
  showMessage('Waiting for fingerprint or device confirmation…', true);
  passkeyLoginButton.disabled = true;
  try {
    if (!window.PublicKeyCredential || !navigator.credentials) {
      throw new Error('This browser does not support fingerprint sign-in.');
    }
    const start = await requestJson('/api/v1/auth/login/passkey/start', {method: 'POST', body: '{}'});
    const credential = await navigator.credentials.get({
      publicKey: prepareAuthenticationOptions(start.public_key),
    });
    if (!credential) throw new Error('Fingerprint sign-in was cancelled.');
    await requestJson('/api/v1/auth/login/passkey/finish', {
      method: 'POST',
      body: JSON.stringify({attempt: start.attempt, credential: serialiseAuthenticationCredential(credential)}),
    });
    await verifySession();
    showMessage('Verified. Opening Amosclaud…', true);
    setTimeout(() => window.location.assign('/'), 120);
  } catch (error) {
    const cancelled = error?.name === 'NotAllowedError';
    showMessage(cancelled ? 'Fingerprint or device confirmation was cancelled.' : error.message);
  } finally {
    passkeyLoginButton.disabled = false;
  }
});

form.addEventListener('submit', async event => {
  event.preventDefault();
  showMessage('');
  if (!form.reportValidity()) return;

  submitButton.disabled = true;
  try {
    if (mode === 'login') {
      let mail = identifierInput.value.trim().toLowerCase();
      if (!mail.includes('@')) mail += '@amosclaud.com';
      await requestJson('/api/v1/auth/login', {
        method: 'POST',
        body: JSON.stringify({email: mail, password: passwordInput.value}),
      });
      await verifySession();
      showMessage('Success. Opening Amosclaud…', true);
      setTimeout(() => window.location.assign('/'), 120);
      return;
    }

    if (!window.PublicKeyCredential || !navigator.credentials) {
      throw new Error('This browser does not support secure device confirmation. Update the browser or use another device.');
    }

    const username = usernameInput.value.trim().toLowerCase();
    showMessage('Preparing secure device confirmation…', true);
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
    showMessage(`Account created: ${finished.address}. Opening Amosclaud…`, true);
    setTimeout(() => window.location.assign('/'), 250);
  } catch (error) {
    const cancelled = error?.name === 'NotAllowedError';
    showMessage(cancelled ? 'Device confirmation was cancelled or timed out. Try again.' : error.message);
  } finally {
    submitButton.disabled = false;
  }
});

(async () => {
  try {
    const response = await fetch('/api/v1/auth/me', {credentials: 'same-origin', cache: 'no-store'});
    if (response.ok) window.location.assign('/');
  } catch (_) {}
})();
