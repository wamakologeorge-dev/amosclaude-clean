(() => {
  const byId = id => document.getElementById(id);
  const form = byId('auth-form');
  const fields = {
    name: byId('name-field'),
    identifier: byId('identifier-field'),
    recovery: byId('recovery-email-field'),
    password: byId('password-field'),
    nextPassword: byId('new-password-field'),
    code: byId('email-code-field'),
    hint: byId('password-hint'),
  };
  const inputs = {
    name: byId('name'),
    identifier: byId('identifier'),
    recovery: byId('recovery-email'),
    password: byId('password'),
    nextPassword: byId('new-password'),
    code: byId('email-code'),
  };
  const loginTab = byId('login-tab');
  const registerTab = byId('register-tab');
  const forgotPassword = byId('forgot-password-button');
  const forgotUsername = byId('forgot-username-button');
  const submit = byId('submit-button');
  const emailCode = byId('email-code-button');
  const passkeyButton = byId('passkey-login-button');
  const title = byId('auth-title');
  const subtitle = byId('auth-subtitle');
  const message = byId('message');

  if (!form || !submit || !message) return;

  let mode = 'login';
  let loginCodeMode = false;
  let signupCodeRequested = false;
  const passkeysAvailable = Boolean(window.isSecureContext && window.PublicKeyCredential && navigator.credentials);

  function show(text, success = false) {
    message.textContent = text || '';
    message.className = success ? 'message success' : 'message';
  }

  function email(value) {
    return String(value || '').trim().toLowerCase();
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
      throw new Error('The Amosclaud server is unavailable. Open this page from the live Amosclaud platform.');
    }
    const text = await response.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (_) { data = {detail: text}; }
    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map(item => item.msg || item.message).join(' ')
        : data.detail;
      throw new Error(detail || `Account request failed (${response.status})`);
    }
    return data;
  }

  function bytes(value) {
    const padding = '='.repeat((4 - value.length % 4) % 4);
    const raw = atob((value + padding).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from(raw, char => char.charCodeAt(0));
  }

  function b64(value) {
    let raw = '';
    new Uint8Array(value).forEach(byte => { raw += String.fromCharCode(byte); });
    return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  }

  function authenticationOptions(options) {
    return {
      ...options,
      challenge: bytes(options.challenge),
      allowCredentials: (options.allowCredentials || []).map(item => ({...item, id: bytes(item.id)})),
    };
  }

  function authenticationCredential(credential) {
    return {
      id: credential.id,
      rawId: b64(credential.rawId),
      type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment,
      clientExtensionResults: credential.getClientExtensionResults(),
      response: {
        clientDataJSON: b64(credential.response.clientDataJSON),
        authenticatorData: b64(credential.response.authenticatorData),
        signature: b64(credential.response.signature),
        userHandle: credential.response.userHandle ? b64(credential.response.userHandle) : null,
      },
    };
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

  function setMode(next) {
    mode = next;
    loginCodeMode = false;
    signupCodeRequested = false;
    form.reset();
    resetRequirements();
    [fields.name, fields.identifier, fields.recovery, fields.password, fields.nextPassword, fields.code, fields.hint]
      .forEach(item => hidden(item, true));

    loginTab.classList.toggle('active', next === 'login');
    registerTab.classList.toggle('active', next === 'register');

    if (next === 'login') {
      title.textContent = 'Welcome back';
      subtitle.textContent = 'Use your email address and password.';
      hidden(fields.identifier, false);
      hidden(fields.password, false);
      required(inputs.identifier, true);
      required(inputs.password, true);
      inputs.password.autocomplete = 'current-password';
      submit.textContent = 'Sign in';
      submit.disabled = false;
      hidden(emailCode, false);
    } else if (next === 'register') {
      title.textContent = 'Create your account';
      subtitle.textContent = 'Start with your name, email, and password. Fingerprint is optional.';
      hidden(fields.name, false);
      hidden(fields.recovery, false);
      hidden(fields.nextPassword, false);
      hidden(fields.hint, false);
      required(inputs.name, true);
      required(inputs.recovery, true);
      required(inputs.nextPassword, true);
      submit.textContent = 'Create account';
      submit.disabled = false;
      hidden(emailCode, true);
    } else if (next === 'forgot-password') {
      title.textContent = 'Reset password';
      subtitle.textContent = 'Enter your email address and choose a new password.';
      hidden(fields.recovery, false);
      hidden(fields.nextPassword, false);
      hidden(fields.code, false);
      required(inputs.recovery, true);
      required(inputs.nextPassword, true);
      submit.textContent = 'Send recovery code';
    } else {
      title.textContent = 'Find your account';
      subtitle.textContent = 'Enter your recovery email and we will send a verification code.';
      hidden(fields.recovery, false);
      hidden(fields.code, false);
      required(inputs.recovery, true);
      submit.textContent = 'Send account code';
    }
    inputs.code.value = '';
    show('');
  }

  loginTab.addEventListener('click', () => setMode('login'));
  registerTab.addEventListener('click', () => setMode('register'));
  forgotPassword.addEventListener('click', () => setMode('forgot-password'));
  forgotUsername.addEventListener('click', () => setMode('forgot-username'));

  emailCode.addEventListener('click', async () => {
    const address = email(inputs.identifier.value);
    if (!address) return show('Enter your email address first.');
    emailCode.disabled = true;
    try {
      const result = await request('/api/v1/auth/login/request-code', {
        method: 'POST',
        body: JSON.stringify({email: address}),
      });
      loginCodeMode = true;
      hidden(fields.password, true);
      hidden(fields.code, false);
      required(inputs.password, false);
      required(inputs.code, true);
      submit.textContent = 'Sign in with code';
      show(result.message || 'A sign-in code was sent.', true);
    } catch (error) {
      show(error.message);
    } finally {
      emailCode.disabled = false;
    }
  });

  if (!passkeysAvailable) {
    passkeyButton.hidden = true;
  } else {
    passkeyButton.addEventListener('click', async () => {
      passkeyButton.disabled = true;
      try {
        const start = await request('/api/v1/auth/login/passkey/start', {method: 'POST', body: '{}'});
        const credential = await navigator.credentials.get({publicKey: authenticationOptions(start.public_key)});
        if (!credential) throw new Error('Device confirmation was cancelled.');
        await request('/api/v1/auth/login/passkey/finish', {
          method: 'POST',
          body: JSON.stringify({attempt: start.attempt, credential: authenticationCredential(credential)}),
        });
        window.location.replace('/cloud/agent');
      } catch (error) {
        show(error.name === 'NotAllowedError' ? 'Device confirmation was cancelled.' : error.message);
      } finally {
        passkeyButton.disabled = false;
      }
    });
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    submit.disabled = true;

    try {
      if (mode === 'login') {
        const address = email(inputs.identifier.value);
        if (loginCodeMode) {
          await request('/api/v1/auth/login/verify-code', {
            method: 'POST',
            body: JSON.stringify({email: address, code: inputs.code.value.trim()}),
          });
        } else {
          await request('/api/v1/auth/login', {
            method: 'POST',
            body: JSON.stringify({email: address, password: inputs.password.value}),
          });
        }
        window.location.replace('/cloud/agent');
        return;
      }

      if (mode === 'register') {
        const address = email(inputs.recovery.value);
        if (!signupCodeRequested) {
          const result = await request('/api/v1/auth/register/request-code', {
            method: 'POST',
            body: JSON.stringify({
              name: inputs.name.value.trim(),
              email: address,
              password: inputs.nextPassword.value,
            }),
          });
          signupCodeRequested = true;
          hidden(fields.name, true);
          hidden(fields.nextPassword, true);
          hidden(fields.code, false);
          required(inputs.name, false);
          required(inputs.nextPassword, false);
          required(inputs.code, true);
          submit.textContent = 'Verify and open Amosclaud';
          show(result.message || 'Enter the code sent to your email.', true);
          inputs.code.focus();
          return;
        }

        await request('/api/v1/auth/register/verify', {
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

      const recoveryEmail = email(inputs.recovery.value);
      if (mode === 'forgot-username') {
        if (!inputs.code.value.trim()) {
          const result = await request('/api/v1/auth/account-recovery/username/request', {
            method: 'POST',
            body: JSON.stringify({recovery_email: recoveryEmail}),
          });
          required(inputs.code, true);
          submit.textContent = 'Show account';
          show(result.message, true);
          inputs.code.focus();
          return;
        }
        const result = await request('/api/v1/auth/account-recovery/username/verify', {
          method: 'POST',
          body: JSON.stringify({recovery_email: recoveryEmail, code: inputs.code.value.trim()}),
        });
        show(`Your account is ${result.address}.`, true);
        return;
      }

      if (!inputs.code.value.trim()) {
        const result = await request('/api/v1/auth/account-recovery/password/request', {
          method: 'POST',
          body: JSON.stringify({recovery_email: recoveryEmail}),
        });
        required(inputs.code, true);
        submit.textContent = 'Reset password';
        show(result.message, true);
        inputs.code.focus();
        return;
      }

      await request('/api/v1/auth/account-recovery/password/reset', {
        method: 'POST',
        body: JSON.stringify({
          recovery_email: recoveryEmail,
          code: inputs.code.value.trim(),
          password: inputs.nextPassword.value,
        }),
      });
      show('Password changed. You can now sign in.', true);
      setTimeout(() => setMode('login'), 1200);
    } catch (error) {
      show(error.message);
    } finally {
      submit.disabled = false;
    }
  });


  // Account settings can use these helpers to add a verified, separate recovery
  // address without duplicating authentication transport or error handling.
  window.AmosclaudAccountAccess = Object.freeze({
    requestRecoveryEmail: recoveryEmail => request('/api/v1/auth/account-recovery/email/request', {
      method: 'POST',
      body: JSON.stringify({email: email(recoveryEmail)}),
    }),
    verifyRecoveryEmail: (recoveryEmail, code) => request('/api/v1/auth/account-recovery/email/verify', {
      method: 'POST',
      body: JSON.stringify({email: email(recoveryEmail), code: String(code || '').trim()}),
    }),
  });

  setMode('login');
})();
