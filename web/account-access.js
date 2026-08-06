(() => {
  const byId = id => document.getElementById(id);
  const form = byId('auth-form');
  const fields = {
    name: byId('name-field'),
    identifier: byId('identifier-field'),
    password: byId('password-field'),
    nextPassword: byId('new-password-field'),
    code: byId('email-code-field'),
    hint: byId('password-hint'),
  };
  const inputs = {
    name: byId('name'),
    identifier: byId('identifier'),
    password: byId('password'),
    nextPassword: byId('new-password'),
    code: byId('email-code'),
  };
  const loginTab = byId('login-tab');
  const registerTab = byId('register-tab');
  const forgotPassword = byId('forgot-password-button');
  const emailCode = byId('email-code-button');
  const submit = byId('submit-button');
  const title = byId('auth-title');
  const subtitle = byId('auth-subtitle');
  const message = byId('message');

  if (!form || !submit || !message || !loginTab || !registerTab) return;

  let mode = 'login';
  let loginCodeRequested = false;
  let signupCodeRequested = false;
  let resetCodeRequested = false;

  function show(text, kind = '') {
    message.textContent = text || '';
    message.className = `message ${kind}`.trim();
  }

  function email(value) {
    return String(value || '').trim().toLowerCase();
  }

  function hidden(element, value) {
    element?.classList.toggle('hidden', value);
  }

  function required(input, value) {
    if (input) input.required = value;
  }

  function resetRequirements() {
    Object.values(inputs).forEach(input => required(input, false));
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
    try {
      data = text ? JSON.parse(text) : {};
    } catch (_) {
      data = {detail: text};
    }

    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map(item => item.msg || item.message).join(' ')
        : data.detail;
      throw new Error(detail || `Account request failed (${response.status})`);
    }
    return data;
  }

  function setMode(next) {
    mode = next;
    loginCodeRequested = false;
    signupCodeRequested = false;
    resetCodeRequested = false;
    form.reset();
    resetRequirements();

    [fields.name, fields.identifier, fields.password, fields.nextPassword, fields.code, fields.hint]
      .forEach(item => hidden(item, true));

    loginTab.classList.toggle('active', next === 'login');
    registerTab.classList.toggle('active', next === 'register');
    loginTab.setAttribute('aria-selected', String(next === 'login'));
    registerTab.setAttribute('aria-selected', String(next === 'register'));

    hidden(fields.identifier, false);
    required(inputs.identifier, true);
    inputs.identifier.autocomplete = 'email';

    if (next === 'login') {
      title.textContent = 'Welcome back';
      subtitle.textContent = 'Use your email address and password.';
      hidden(fields.password, false);
      required(inputs.password, true);
      inputs.password.autocomplete = 'current-password';
      submit.textContent = 'Sign in';
      emailCode.hidden = false;
      forgotPassword.hidden = false;
    } else if (next === 'register') {
      title.textContent = 'Create your account';
      subtitle.textContent = 'Enter your name, email address, and a secure password.';
      hidden(fields.name, false);
      hidden(fields.nextPassword, false);
      hidden(fields.hint, false);
      required(inputs.name, true);
      required(inputs.nextPassword, true);
      inputs.nextPassword.autocomplete = 'new-password';
      submit.textContent = 'Create account';
      emailCode.hidden = true;
      forgotPassword.hidden = false;
    } else {
      title.textContent = 'Reset your password';
      subtitle.textContent = 'We will send a security code to your account email.';
      hidden(fields.nextPassword, false);
      hidden(fields.hint, false);
      required(inputs.nextPassword, true);
      inputs.nextPassword.autocomplete = 'new-password';
      submit.textContent = 'Send reset code';
      emailCode.hidden = true;
      forgotPassword.hidden = true;
    }

    show('');
  }

  loginTab.addEventListener('click', () => setMode('login'));
  registerTab.addEventListener('click', () => setMode('register'));
  forgotPassword?.addEventListener('click', () => setMode('forgot-password'));

  emailCode?.addEventListener('click', async () => {
    const address = email(inputs.identifier.value);
    if (!address) {
      show('Enter your email address first.', 'error');
      inputs.identifier.focus();
      return;
    }

    emailCode.disabled = true;
    show('Sending your security code…');
    try {
      const result = await request('/auth/login/request-code', {
        method: 'POST',
        body: JSON.stringify({email: address}),
      });
      loginCodeRequested = true;
      hidden(fields.password, true);
      hidden(fields.code, false);
      required(inputs.password, false);
      required(inputs.code, true);
      submit.textContent = 'Sign in with code';
      show(result.message || 'A sign-in code was sent.', 'success');
      inputs.code.focus();
    } catch (error) {
      show(error.message, 'error');
    } finally {
      emailCode.disabled = false;
    }
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    submit.disabled = true;

    const address = email(inputs.identifier.value);
    try {
      if (mode === 'login') {
        if (loginCodeRequested) {
          await request('/auth/login/verify-code', {
            method: 'POST',
            body: JSON.stringify({email: address, code: inputs.code.value.trim()}),
          });
        } else {
          await request('/auth/login', {
            method: 'POST',
            body: JSON.stringify({email: address, password: inputs.password.value}),
          });
        }
        window.location.replace('/cloud/agent');
        return;
      }

      if (mode === 'register') {
        if (!signupCodeRequested) {
          const result = await request('/auth/register/request-code', {
            method: 'POST',
            body: JSON.stringify({
              name: inputs.name.value.trim(),
              email: address,
              password: inputs.nextPassword.value,
            }),
          });
          if (result.account_created) {
            show(result.message || 'Owner account created. Opening Amosclaud…', 'success');
            window.location.replace('/admin');
            return;
          }
          signupCodeRequested = true;
          hidden(fields.name, true);
          hidden(fields.nextPassword, true);
          hidden(fields.hint, true);
          hidden(fields.code, false);
          required(inputs.name, false);
          required(inputs.nextPassword, false);
          required(inputs.code, true);
          submit.textContent = 'Verify and open Amosclaud';
          show(result.message || 'Enter the code sent to your email.', 'success');
          inputs.code.focus();
          return;
        }

        await request('/auth/register/verify', {
          method: 'POST',
          body: JSON.stringify({
            email: address,
            password: inputs.nextPassword.value,
            code: inputs.code.value.trim(),
          }),
        });
        window.location.replace('/cloud/agent');
        return;
      }

      if (!resetCodeRequested) {
        const result = await request('/auth/password/forgot', {
          method: 'POST',
          body: JSON.stringify({email: address}),
        });
        resetCodeRequested = true;
        hidden(fields.code, false);
        required(inputs.code, true);
        submit.textContent = 'Reset password';
        show(result.message || 'A reset code was sent.', 'success');
        inputs.code.focus();
        return;
      }

      await request('/auth/password/reset', {
        method: 'POST',
        body: JSON.stringify({
          email: address,
          code: inputs.code.value.trim(),
          password: inputs.nextPassword.value,
        }),
      });
      setMode('login');
      inputs.identifier.value = address;
      show('Password changed. Sign in with your new password.', 'success');
    } catch (error) {
      show(error.message, 'error');
    } finally {
      submit.disabled = false;
    }
  });

  const params = new URLSearchParams(window.location.search);
  const requestedMode = params.get('mode');
  setMode(requestedMode === 'register' ? 'register' : 'login');
})();
