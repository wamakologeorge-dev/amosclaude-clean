const form = document.getElementById('auth-form');
const loginTab = document.getElementById('login-tab');
const registerTab = document.getElementById('register-tab');
const nameField = document.getElementById('name-field');
const nameInput = document.getElementById('name');
const emailInput = document.getElementById('email');
const passwordInput = document.getElementById('password');
const passwordHint = document.getElementById('password-hint');
const submitButton = document.getElementById('submit-button');
const title = document.getElementById('auth-title');
const subtitle = document.getElementById('auth-subtitle');
const message = document.getElementById('message');

let mode = 'login';

function setMode(nextMode) {
  mode = nextMode;
  const registering = mode === 'register';
  loginTab.classList.toggle('active', !registering);
  registerTab.classList.toggle('active', registering);
  nameField.classList.toggle('hidden', !registering);
  passwordHint.classList.toggle('hidden', !registering);
  nameInput.required = registering;
  passwordInput.minLength = registering ? 10 : 1;
  passwordInput.autocomplete = registering ? 'new-password' : 'current-password';
  title.textContent = registering ? 'Create your account' : 'Welcome back';
  subtitle.textContent = registering
    ? 'The first account created becomes the administrator.'
    : 'Use your email and password or continue with GitHub.';
  submitButton.textContent = registering ? 'Create account' : 'Sign in';
  message.textContent = '';
  message.className = 'message';
}

loginTab.addEventListener('click', () => setMode('login'));
registerTab.addEventListener('click', () => setMode('register'));

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  message.textContent = '';
  message.className = 'message';

  if (!form.reportValidity()) return;

  const payload = {
    email: emailInput.value.trim(),
    password: passwordInput.value,
  };
  if (mode === 'register') payload.name = nameInput.value.trim();

  submitButton.disabled = true;
  submitButton.textContent = mode === 'register' ? 'Creating account…' : 'Signing in…';

  try {
    const response = await fetch(`/api/v1/auth/${mode}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = response.status === 204 ? {} : await response.json();
    if (!response.ok) throw new Error(data.detail || 'Authentication failed');
    message.textContent = 'Success. Opening your dashboard…';
    message.classList.add('success');
    window.location.assign('/');
  } catch (error) {
    message.textContent = error.message;
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = mode === 'register' ? 'Create account' : 'Sign in';
  }
});

(async () => {
  try {
    const response = await fetch('/api/v1/auth/me', { credentials: 'same-origin' });
    if (response.ok) window.location.assign('/');
  } catch (_) {
    // Login page remains available when the server is temporarily offline.
  }
})();
