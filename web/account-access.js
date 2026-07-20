(() => {
  const byId = id => document.getElementById(id);
  const form = byId('auth-form');
  const fields = {
    name: byId('name-field'), identifier: byId('identifier-field'), username: byId('username-field'),
    recovery: byId('recovery-email-field'), password: byId('password-field'), nextPassword: byId('new-password-field'),
    code: byId('email-code-field'), hint: byId('password-hint'), device: byId('device-note'),
  };
  const inputs = {
    name: byId('name'), identifier: byId('identifier'), username: byId('username'),
    recovery: byId('recovery-email'), password: byId('password'), nextPassword: byId('new-password'), code: byId('email-code'),
  };
  const loginTab = byId('login-tab');
  const registerTab = byId('register-tab');
  const forgotPassword = byId('forgot-password-button');
  const forgotUsername = byId('forgot-username-button');
  const submit = byId('submit-button');
  const emailCode = byId('email-code-button');
  const passkeyButton = byId('passkey-login-button');
  const divider = byId('password-login-divider');
  const title = byId('auth-title');
  const subtitle = byId('auth-subtitle');
  const message = byId('message');

  if (!form || !submit || !message) return;

  let mode = 'login';
  let loginCodeMode = false;
  let accountCreated = false;
  const passkeysAvailable = Boolean(window.isSecureContext && window.PublicKeyCredential && navigator.credentials);

  function show(text, success = false) {
    message.textContent = text || '';
    message.className = success ? 'message success' : 'message';
  }

  function canonicalAddress(value) {
    const clean = String(value || '').trim().toLowerCase();
    return clean.includes('@') ? clean : `${clean}@amosclaud.com`;
  }

  async function request(url, options = {}) {
    let response;
    try {
      response = await fetch(url, {
        credentials: 'same-origin', cache: 'no-store', ...options,
        headers: {'Content-Type': 'application/json', ...(options.headers || {})},
      });
    } catch (_) {
      throw new Error('Amosclaud could not reach the account service. Check the deployment and try again.');
    }
    const text = await response.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (_) { data = {detail: text}; }
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map(item => item.msg || item.message).join(' ') : data.detail;
      const error = new Error(detail || `Account request failed (${response.status})`);
      error.status = response.status;
      throw error;
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

  function creationOptions(options) {
    return {...options, challenge: bytes(options.challenge), user: {...options.user, id: bytes(options.user.id)},
      excludeCredentials: (options.excludeCredentials || []).map(item => ({...item, id: bytes(item.id)}))};
  }

  function authenticationOptions(options) {
    return {...options, challenge: bytes(options.challenge),
      allowCredentials: (options.allowCredentials || []).map(item => ({...item, id: bytes(item.id)}))};
  }

  function registrationCredential(credential) {
    return {id: credential.id, rawId: b64(credential.rawId), type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment,
      clientExtensionResults: credential.getClientExtensionResults(), response: {
        clientDataJSON: b64(credential.response.clientDataJSON),
        attestationObject: b64(credential.response.attestationObject),
        transports: credential.response.getTransports ? credential.response.getTransports() : [],
      }};
  }

  function authenticationCredential(credential) {
    return {id: credential.id, rawId: b64(credential.rawId), type: credential.type,
      authenticatorAttachment: credential.authenticatorAttachment,
      clientExtensionResults: credential.getClientExtensionResults(), response: {
        clientDataJSON: b64(credential.response.clientDataJSON), authenticatorData: b64(credential.response.authenticatorData),
        signature: b64(credential.response.signature),
        userHandle: credential.response.userHandle ? b64(credential.response.userHandle) : null,
      }};
  }

  function hidden(element, value) { element?.classList.toggle('hidden', value); }
  function required(input, value) { if (input) input.required = value; }

  function setMode(next) {
    mode = next;
    accountCreated = false;
    loginCodeMode = false;
    form.reset();
    [fields.name, fields.identifier, fields.username, fields.recovery, fields.password, fields.nextPassword, fields.code,
      fields.hint, fields.device, passkeyButton, divider, emailCode].forEach(item => hidden(item, true));
    Object.values(inputs).forEach(input => required(input, false));
    loginTab.classList.toggle('active', next === 'login');
    registerTab.classList.toggle('active', next === 'register');

    if (next === 'login') {
      title.textContent = 'Welcome back';
      subtitle.textContent = 'Sign in with your Amosclaud username, password, code, or passkey.';
      hidden(fields.identifier, false); hidden(fields.password, false); hidden(emailCode, false);
      hidden(passkeyButton, !passkeysAvailable); hidden(divider, !passkeysAvailable);
      required(inputs.identifier, true); required(inputs.password, true);
      inputs.password.autocomplete = 'current-password';
      submit.textContent = 'Sign in';
    } else if (next === 'register') {
      title.textContent = 'Create your Amosclaud account';
      subtitle.textContent = 'Choose your @amosclaud.com username and verify a separate recovery email.';
      hidden(fields.name, false); hidden(fields.username, false); hidden(fields.recovery, false); hidden(fields.password, false);
      hidden(fields.hint, false); hidden(fields.device, !passkeysAvailable);
      required(inputs.name, true); required(inputs.username, true); required(inputs.recovery, true); required(inputs.password, true);
      inputs.password.minLength = 10; inputs.password.autocomplete = 'new-password';
      submit.textContent = passkeysAvailable ? 'Create account securely' : 'HTTPS required for account creation';
      submit.disabled = !passkeysAvailable;
    } else if (next === 'forgot-password') {
      title.textContent = 'Reset your password';
      subtitle.textContent = 'Amosclaud will send a six-digit code to your verified recovery email.';
      hidden(fields.recovery, false); hidden(fields.code, false); hidden(fields.nextPassword, false);
      required(inputs.recovery, true); required(inputs.nextPassword, true);
      submit.textContent = 'Send recovery code';
    } else {
      title.textContent = 'Recover your username';
      subtitle.textContent = 'Verify your recovery email before Amosclaud reveals your account address.';
      hidden(fields.recovery, false); hidden(fields.code, false);
      required(inputs.recovery, true);
      submit.textContent = 'Send username code';
    }
    inputs.code.value = '';
    show('');
  }

  loginTab.addEventListener('click', () => setMode('login'));
  registerTab.addEventListener('click', () => setMode('register'));
  forgotPassword.addEventListener('click', () => setMode('forgot-password'));
  forgotUsername.addEventListener('click', () => setMode('forgot-username'));

  emailCode.addEventListener('click', async () => {
    const address = canonicalAddress(inputs.identifier.value);
    if (!inputs.identifier.value.trim()) return show('Enter your Amosclaud username first.');
    emailCode.disabled = true;
    try {
      const result = await request('/api/v1/auth/login/request-code', {method: 'POST', body: JSON.stringify({email: address})});
      loginCodeMode = true;
      hidden(fields.password, true); hidden(fields.code, false);
      required(inputs.password, false); required(inputs.code, true);
      submit.textContent = 'Verify code and sign in';
      show(result.message, true);
    } catch (error) { show(error.message); }
    finally { emailCode.disabled = false; }
  });

  passkeyButton.addEventListener('click', async () => {
    if (!passkeysAvailable) return show('Passkey sign-in requires HTTPS.');
    passkeyButton.disabled = true;
    try {
      const start = await request('/api/v1/auth/login/passkey/start', {method: 'POST', body: '{}'});
      const credential = await navigator.credentials.get({publicKey: authenticationOptions(start.public_key)});
      if (!credential) throw new Error('Device confirmation was cancelled.');
      await request('/api/v1/auth/login/passkey/finish', {method: 'POST', body: JSON.stringify({attempt: start.attempt, credential: authenticationCredential(credential)})});
      window.location.replace('/cloud/agent');
    } catch (error) { show(error.name === 'NotAllowedError' ? 'Device confirmation was cancelled.' : error.message); }
    finally { passkeyButton.disabled = false; }
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    submit.disabled = true;
    try {
      if (mode === 'login') {
        const address = canonicalAddress(inputs.identifier.value);
        if (loginCodeMode) {
          await request('/api/v1/auth/login/verify-code', {method: 'POST', body: JSON.stringify({email: address, code: inputs.code.value.trim()})});
        } else {
          await request('/api/v1/auth/login', {method: 'POST', body: JSON.stringify({email: address, password: inputs.password.value})});
        }
        window.location.replace('/cloud/agent');
        return;
      }

      if (mode === 'register') {
        if (!accountCreated) {
          const username = inputs.username.value.trim().toLowerCase();
          const start = await request('/api/v1/auth/register/passkey/start', {method: 'POST', body: JSON.stringify({name: inputs.name.value.trim(), username, password: inputs.password.value})});
          const credential = await navigator.credentials.create({publicKey: creationOptions(start.public_key)});
          if (!credential) throw new Error('Device confirmation was cancelled.');
          await request('/api/v1/auth/register/passkey/finish', {method: 'POST', body: JSON.stringify({username, credential: registrationCredential(credential)})});
          await request('/api/v1/auth/account-recovery/email/request', {method: 'POST', body: JSON.stringify({email: inputs.recovery.value.trim()})});
          accountCreated = true;
          hidden(fields.name, true); hidden(fields.username, true); hidden(fields.password, true); hidden(fields.code, false);
          required(inputs.code, true);
          submit.textContent = 'Verify recovery email';
          show('Account created. Enter the code sent from no-reply@amosclaud.com to finish recovery setup.', true);
          return;
        }
        await request('/api/v1/auth/account-recovery/email/verify', {method: 'POST', body: JSON.stringify({email: inputs.recovery.value.trim(), code: inputs.code.value.trim()})});
        show('Account and recovery email verified. Opening Amosclaud…', true);
        window.location.replace('/cloud/agent');
        return;
      }

      const recoveryEmail = inputs.recovery.value.trim();
      if (mode === 'forgot-username') {
        if (!inputs.code.value.trim()) {
          const result = await request('/api/v1/auth/account-recovery/username/request', {method: 'POST', body: JSON.stringify({recovery_email: recoveryEmail})});
          required(inputs.code, true); submit.textContent = 'Verify and show username'; show(result.message, true); inputs.code.focus(); return;
        }
        const result = await request('/api/v1/auth/account-recovery/username/verify', {method: 'POST', body: JSON.stringify({recovery_email: recoveryEmail, code: inputs.code.value.trim()})});
        show(`Your Amosclaud account is ${result.address}.`, true);
        inputs.identifier.value = result.address;
        return;
      }

      if (!inputs.code.value.trim()) {
        const result = await request('/api/v1/auth/account-recovery/password/request', {method: 'POST', body: JSON.stringify({recovery_email: recoveryEmail})});
        required(inputs.code, true); submit.textContent = 'Reset password'; show(result.message, true); inputs.code.focus(); return;
      }
      await request('/api/v1/auth/account-recovery/password/reset', {method: 'POST', body: JSON.stringify({recovery_email: recoveryEmail, code: inputs.code.value.trim(), password: inputs.nextPassword.value})});
      show('Password changed. All older sessions were signed out. You can now sign in.', true);
      setTimeout(() => setMode('login'), 1200);
    } catch (error) {
      show(error.name === 'NotAllowedError' ? 'Device confirmation was cancelled or timed out.' : error.message);
    } finally {
      submit.disabled = mode === 'register' && !passkeysAvailable;
    }
  });

  setMode('login');
})();
