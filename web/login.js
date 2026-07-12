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

function serialiseCredential(credential) {
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

  nameInput.required = registering;
  usernameInput.required = registering;
  identifierInput.required = !registering;
  passwordInput.minLength = registering ? 10 : 1;
  passwordInput.autocomplete = registering ? 'new-password' : 'current-password';

  if (registering) {
    title.textContent = 'Create your Amosclaud account';
    subtitle.textContent = 'Choose your @amosclaud.com address and confirm on this device.';
    submitButton.textContent = 'Create account securely';
  } else {
    title.textContent = 'Welcome back';
    subtitle.textContent = 'Sign in with your Amosclaud address.';
    submitButton.textContent = 'Sign in';
  }
  showMessage('');
}

loginTab.addEventListener('click', () => setMode('login'));
registerTab.addEventListener('click', () => setMode('register'));

form.addEventListener('submit', async event => {
  event.preventDefault();
  showMessage('');
  if (!form.reportValidity()) return;

  submitButton.disabled = true;
  try {
    if (mode === 'login') {
      let email = identifierInput.value.trim().toLowerCase();
      if (!email.includes('@')) email += '@amosclaud.com';
      await requestJson('/api/v1/auth/login', {
        method: 'POST',
        body: JSON.stringify({email, password: passwordInput.value}),
      });
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
      body: JSON.stringify({
        name: nameInput.value.trim(),
        username,
        password: passwordInput.value,
      }),
    });

    const credential = await navigator.credentials.create({
      publicKey: prepareCreationOptions(start.public_key),
    });
    if (!credential) throw new Error('Device confirmation was cancelled.');

    const finished = await requestJson('/api/v1/auth/register/passkey/finish', {
      method: 'POST',
      body: JSON.stringify({username, credential: serialiseCredential(credential)}),
    });

    showMessage(`Account created: ${finished.address}. Opening Amosclaud…`, true);
    setTimeout(() => window.location.assign('/'), 250);
  } catch (error) {
    const cancelled = error?.name === 'NotAllowedError';
    showMessage(cancelled ? 'Device confirmation was cancelled or timed out. Tap Create account securely and try again.' : error.message);
  } finally {
    submitButton.disabled = false;
  }
});

(async () => {
  try {
    const response = await fetch('/api/v1/auth/me', {credentials: 'same-origin'});
    if (response.ok) window.location.assign('/');
  } catch (_) {
    // Keep the page available while the server reconnects.
  }
})();
