const form = document.getElementById('auth-form');
const loginTab = document.getElementById('login-tab');
const registerTab = document.getElementById('register-tab');
const nameField = document.getElementById('name-field');
const passwordField = document.getElementById('password-field');
const codeField = document.getElementById('code-field');
const nameInput = document.getElementById('name');
const emailInput = document.getElementById('email');
const passwordInput = document.getElementById('password');
const codeInput = document.getElementById('code');
const passwordHint = document.getElementById('password-hint');
const submitButton = document.getElementById('submit-button');
const forgotButton = document.getElementById('forgot-password');
const title = document.getElementById('auth-title');
const subtitle = document.getElementById('auth-subtitle');
const message = document.getElementById('message');

let mode = 'login';

function showMessage(text, success = false) {
  message.textContent = text;
  message.className = success ? 'message success' : 'message';
}

function setMode(nextMode) {
  mode = nextMode;
  const registering = mode === 'register';
  const verifying = mode === 'verify';
  const resetting = mode === 'reset';

  loginTab.classList.toggle('active', mode === 'login');
  registerTab.classList.toggle('active', registering || verifying);
  nameField.classList.toggle('hidden', !registering);
  codeField.classList.toggle('hidden', !(verifying || resetting));
  passwordField.classList.toggle('hidden', false);
  passwordHint.classList.toggle('hidden', !registering);
  forgotButton.classList.toggle('hidden', mode !== 'login');

  nameInput.required = registering;
  codeInput.required = verifying || resetting;
  passwordInput.required = true;
  passwordInput.minLength = registering || resetting ? 10 : 1;
  passwordInput.autocomplete = registering || resetting ? 'new-password' : 'current-password';

  if (mode === 'login') {
    title.textContent = 'Welcome back';
    subtitle.textContent = 'Sign in directly to Amosclaud.';
    submitButton.textContent = 'Sign in';
  } else if (mode === 'register') {
    title.textContent = 'Create your Amosclaud account';
    subtitle.textContent = 'We will send a six-digit verification code to your email.';
    submitButton.textContent = 'Send verification code';
  } else if (mode === 'verify') {
    title.textContent = 'Verify your email';
    subtitle.textContent = 'Enter the code Amosclaud sent to your email.';
    submitButton.textContent = 'Verify and create account';
  } else {
    title.textContent = 'Reset your password';
    subtitle.textContent = 'Enter the reset code and choose a new password.';
    submitButton.textContent = 'Reset password';
  }
  showMessage('');
}

loginTab.addEventListener('click', () => setMode('login'));
registerTab.addEventListener('click', () => setMode('register'));

forgotButton.addEventListener('click', async () => {
  const email = emailInput.value.trim();
  if (!email) {
    showMessage('Enter your email address first.');
    emailInput.focus();
    return;
  }
  forgotButton.disabled = true;
  try {
    const response = await fetch('/api/v1/auth/password/forgot', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Could not send reset code');
    setMode('reset');
    showMessage('A password reset code was sent by Amosclaud.', true);
  } catch (error) {
    showMessage(error.message);
  } finally {
    forgotButton.disabled = false;
  }
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  showMessage('');
  if (!form.reportValidity()) return;

  let endpoint = '/api/v1/auth/login';
  let payload = {email: emailInput.value.trim(), password: passwordInput.value};

  if (mode === 'register') {
    endpoint = '/api/v1/auth/register/request-code';
    payload.name = nameInput.value.trim();
  } else if (mode === 'verify') {
    endpoint = '/api/v1/auth/register/verify';
    payload.code = codeInput.value.trim();
  } else if (mode === 'reset') {
    endpoint = '/api/v1/auth/password/reset';
    payload.code = codeInput.value.trim();
  }

  submitButton.disabled = true;
  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const data = response.status === 204 ? {} : await response.json();
    if (!response.ok) throw new Error(data.detail || 'Authentication failed');

    if (mode === 'register') {
      setMode('verify');
      showMessage('Verification code sent. Check your email.', true);
      return;
    }
    if (mode === 'reset') {
      setMode('login');
      showMessage('Password reset. You can sign in now.', true);
      return;
    }

    showMessage(mode === 'verify' ? 'Account created. Opening Amosclaud…' : 'Success. Opening Amosclaud…', true);
    setTimeout(() => window.location.assign('/'), 150);
  } catch (error) {
    showMessage(error.message);
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
