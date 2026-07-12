const form = document.getElementById('auth-form');
const loginTab = document.getElementById('login-tab');
const registerTab = document.getElementById('register-tab');
const nameField = document.getElementById('name-field');
const passwordField = document.getElementById('password-field');
const codeField = document.getElementById('code-field');
const secureSetup = document.getElementById('secure-setup');
const secureKey = document.getElementById('secure-key');
const copySecureKey = document.getElementById('copy-secure-key');
const openAuthenticator = document.getElementById('open-authenticator');
const recoveryPanel = document.getElementById('recovery-panel');
const recoveryCodes = document.getElementById('recovery-codes');
const continueAfterRecovery = document.getElementById('continue-after-recovery');
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
let pendingSetup = null;

function showMessage(text, success = false) {
  message.textContent = text;
  message.className = success ? 'message success' : 'message';
}

function errorText(detail, fallback = 'Authentication failed') {
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map(item => item?.msg || item?.message || JSON.stringify(item)).join(' ');
  }
  return detail.msg || detail.message || fallback;
}

async function readResponse(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch (_) {
    return {detail: text};
  }
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
  secureSetup.classList.toggle('hidden', !verifying);
  passwordField.classList.toggle('hidden', false);
  passwordHint.classList.toggle('hidden', !registering);
  forgotButton.classList.toggle('hidden', mode !== 'login');
  recoveryPanel.classList.add('hidden');
  form.classList.remove('hidden');

  nameInput.required = registering;
  codeInput.required = verifying || resetting;
  passwordInput.required = true;
  passwordInput.minLength = registering || verifying || resetting ? 10 : 1;
  passwordInput.autocomplete = registering || verifying || resetting ? 'new-password' : 'current-password';
  codeInput.value = '';
  codeInput.inputMode = verifying ? 'numeric' : 'text';
  codeInput.maxLength = verifying ? 6 : 32;
  codeInput.pattern = verifying ? '[0-9]{6}' : '';
  codeInput.placeholder = verifying ? '6-digit code from your authenticator app' : 'Authenticator code or recovery code';

  if (mode === 'login') {
    title.textContent = 'Welcome back';
    subtitle.textContent = 'Sign in directly to Amosclaud.';
    submitButton.textContent = 'Sign in';
  } else if (mode === 'register') {
    title.textContent = 'Create your Amosclaud account';
    subtitle.textContent = 'Set up a rotating Amos Secure Code. No email provider is required.';
    submitButton.textContent = 'Create secure code setup';
  } else if (mode === 'verify') {
    title.textContent = 'Enter your Amos Secure Code';
    subtitle.textContent = 'Add the setup key to your authenticator app, then enter the six-digit number shown by the app — not the setup key.';
    submitButton.textContent = 'Verify and create account';
  } else {
    title.textContent = 'Reset your password';
    subtitle.textContent = 'Enter a current Amos Secure Code or one saved recovery code.';
    submitButton.textContent = 'Reset password';
  }
  showMessage('');
}

loginTab.addEventListener('click', () => setMode('login'));
registerTab.addEventListener('click', () => setMode('register'));

forgotButton.addEventListener('click', () => {
  const email = emailInput.value.trim();
  if (!email) {
    showMessage('Enter your email address first.');
    emailInput.focus();
    return;
  }
  setMode('reset');
  showMessage('Use your authenticator code or one recovery code. No email will be sent.', true);
});

copySecureKey.addEventListener('click', async () => {
  if (!pendingSetup?.secret) return;
  await navigator.clipboard.writeText(pendingSetup.secret);
  showMessage('Setup key copied. Add it to your authenticator app; do not paste it into the code box.', true);
});

continueAfterRecovery.addEventListener('click', () => window.location.assign('/'));

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  showMessage('');
  if (!form.reportValidity()) return;

  let endpoint = '/api/v1/auth/login';
  const payload = {email: emailInput.value.trim(), password: passwordInput.value};

  if (mode === 'register') {
    endpoint = '/api/v1/auth/register/secure-code/start';
    payload.name = nameInput.value.trim();
  } else if (mode === 'verify') {
    const code = codeInput.value.trim();
    if (!/^\d{6}$/.test(code)) {
      showMessage('Enter the six-digit number generated by your authenticator app, not the setup key.');
      codeInput.focus();
      return;
    }
    endpoint = '/api/v1/auth/register/secure-code/verify';
    payload.code = code;
  } else if (mode === 'reset') {
    endpoint = '/api/v1/auth/password/secure-reset';
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
    const data = await readResponse(response);
    if (!response.ok) throw new Error(errorText(data.detail));

    if (mode === 'register') {
      pendingSetup = data;
      secureKey.textContent = data.secret;
      openAuthenticator.href = data.otpauth_uri;
      setMode('verify');
      secureSetup.classList.remove('hidden');
      showMessage('Setup created. Add the key to your authenticator app, then type the six-digit number shown there.', true);
      return;
    }

    if (mode === 'verify') {
      recoveryCodes.textContent = (data.recovery_codes || []).join('\n');
      form.classList.add('hidden');
      recoveryPanel.classList.remove('hidden');
      title.textContent = 'Account created';
      subtitle.textContent = 'Save these one-time recovery codes before continuing.';
      showMessage('Your Amosclaud account is protected without Google, email, or SMS.', true);
      return;
    }

    if (mode === 'reset') {
      setMode('login');
      showMessage('Password reset. You can sign in now.', true);
      return;
    }

    showMessage('Success. Opening Amosclaud…', true);
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