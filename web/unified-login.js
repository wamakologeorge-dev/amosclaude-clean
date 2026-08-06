(() => {
  const byId = id => document.getElementById(id);
  const organizationPanel = byId('organization-access-panel');
  const emailPanel = byId('email-access-panel');
  const organizationTab = byId('organization-method-tab');
  const emailTab = byId('email-method-tab');
  const form = byId('organization-form');
  const message = byId('organization-message');
  const recoveryResult = byId('organization-recovery-result');
  const recoveryCodes = byId('organization-recovery-codes');
  const continueButton = byId('organization-continue-button');
  const modeTabs = Array.from(document.querySelectorAll('[data-organization-mode]'));

  if (!organizationPanel || !emailPanel || !form || !message) return;

  const fields = {
    organizationName: byId('organization-name-field'),
    accessCode: byId('organization-access-code-field'),
    recoveryCode: byId('organization-recovery-code-field'),
  };
  const inputs = {
    organizationName: byId('organization-name'),
    organizationId: byId('organization-id'),
    identity: byId('organization-identity'),
    accessCode: byId('organization-access-code'),
    recoveryCode: byId('organization-recovery-code'),
    password: byId('organization-password'),
  };
  const title = byId('organization-title');
  const subtitle = byId('organization-subtitle');
  const identityText = byId('organization-identity-text');
  const identityHint = byId('organization-identity-hint');
  const passwordText = byId('organization-password-text');
  const submit = byId('organization-submit');
  const recoverButton = byId('organization-recover-button');

  let organizationMode = 'login';

  function show(text, kind = '') {
    message.textContent = text || '';
    message.className = `message ${kind}`.trim();
  }

  function chooseMethod(method, updateUrl = true) {
    const useOrganization = method !== 'email';
    organizationPanel.hidden = !useOrganization;
    emailPanel.hidden = useOrganization;
    organizationTab.classList.toggle('active', useOrganization);
    emailTab.classList.toggle('active', !useOrganization);
    organizationTab.setAttribute('aria-selected', String(useOrganization));
    emailTab.setAttribute('aria-selected', String(!useOrganization));
    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set('method', useOrganization ? 'organization' : 'email');
      window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
    }
  }

  async function request(path, options = {}) {
    let response;
    try {
      response = await fetch(path, {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: {'Content-Type': 'application/json', ...(options.headers || {})},
        ...options,
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

  async function shareSession() {
    await fetch('/api/v1/account/share-session', {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
    }).catch(() => null);
  }

  function setRequired(input, required) {
    if (input) input.required = required;
  }

  function setOrganizationMode(nextMode) {
    organizationMode = nextMode;
    form.reset();
    recoveryResult.hidden = true;
    fields.organizationName.hidden = nextMode !== 'register';
    fields.accessCode.hidden = nextMode !== 'join';
    fields.recoveryCode.hidden = nextMode !== 'recover';
    setRequired(inputs.organizationName, nextMode === 'register');
    setRequired(inputs.accessCode, nextMode === 'join');
    setRequired(inputs.recoveryCode, nextMode === 'recover');
    modeTabs.forEach(tab => tab.classList.toggle('active', tab.dataset.organizationMode === nextMode));
    recoverButton.classList.toggle('active-link', nextMode === 'recover');

    if (nextMode === 'login') {
      title.textContent = 'Sign in with organization ID';
      subtitle.textContent = 'Enter three things: organization ID, username or member ID, and password.';
      identityText.textContent = 'Username or member ID';
      identityHint.textContent = 'Example: george or 11111-2131';
      inputs.identity.placeholder = 'george or 11111-2131';
      inputs.identity.removeAttribute('pattern');
      passwordText.textContent = 'Password';
      inputs.password.autocomplete = 'current-password';
      submit.textContent = 'Sign in';
    } else if (nextMode === 'register') {
      title.textContent = 'Create an organization account';
      subtitle.textContent = 'Only four fields. No email code is required.';
      identityText.textContent = 'Owner username';
      identityHint.textContent = 'Use a short username, not an email. Example: george';
      inputs.identity.placeholder = 'george';
      inputs.identity.pattern = '[A-Za-z][A-Za-z0-9_.-]{1,31}';
      passwordText.textContent = 'Create password';
      inputs.password.autocomplete = 'new-password';
      submit.textContent = 'Create organization';
    } else if (nextMode === 'join') {
      title.textContent = 'Join an organization';
      subtitle.textContent = 'Use the temporary access code provided by the organization owner.';
      identityText.textContent = 'Create username';
      identityHint.textContent = 'Use a short username, not an email. Example: sam';
      inputs.identity.placeholder = 'sam';
      inputs.identity.pattern = '[A-Za-z][A-Za-z0-9_.-]{1,31}';
      passwordText.textContent = 'Create password';
      inputs.password.autocomplete = 'new-password';
      submit.textContent = 'Join organization';
    } else {
      title.textContent = 'Recover organization account';
      subtitle.textContent = 'Use one unused recovery code and choose a new password.';
      identityText.textContent = 'Username or member ID';
      identityHint.textContent = 'Example: george or 11111-2131';
      inputs.identity.placeholder = 'george or 11111-2131';
      inputs.identity.removeAttribute('pattern');
      passwordText.textContent = 'New password';
      inputs.password.autocomplete = 'new-password';
      submit.textContent = 'Recover account';
    }
    show('');
  }

  organizationTab.addEventListener('click', () => chooseMethod('organization'));
  emailTab.addEventListener('click', () => chooseMethod('email'));
  modeTabs.forEach(tab => tab.addEventListener('click', () => {
    chooseMethod('organization');
    setOrganizationMode(tab.dataset.organizationMode);
  }));
  recoverButton.addEventListener('click', () => setOrganizationMode('recover'));

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    submit.disabled = true;
    show('Working…');

    const organizationId = inputs.organizationId.value.trim();
    const identity = inputs.identity.value.trim();
    const password = inputs.password.value;

    try {
      let data;
      if (organizationMode === 'login') {
        data = await request('/api/v1/organization-access/login', {
          method: 'POST',
          body: JSON.stringify({
            organization_id: organizationId,
            username_or_member_id: identity,
            password,
          }),
        });
        await shareSession();
        show(`Signed in as ${data.member_id}.`, 'success');
        window.location.assign('/cloud/agent');
        return;
      }

      if (organizationMode === 'register') {
        data = await request('/api/v1/organization-access/register', {
          method: 'POST',
          body: JSON.stringify({
            organization_id: organizationId,
            organization_name: inputs.organizationName.value.trim(),
            username: identity,
            password,
          }),
        });
      } else if (organizationMode === 'join') {
        data = await request('/api/v1/organization-access/join', {
          method: 'POST',
          body: JSON.stringify({
            organization_id: organizationId,
            access_code: inputs.accessCode.value.trim(),
            username: identity,
            password,
          }),
        });
      } else {
        data = await request('/api/v1/organization-access/recover', {
          method: 'POST',
          body: JSON.stringify({
            organization_id: organizationId,
            username_or_member_id: identity,
            recovery_code: inputs.recoveryCode.value.trim(),
            new_password: password,
          }),
        });
        recoveryResult.hidden = false;
        recoveryCodes.textContent = data.replacement_recovery_code;
        continueButton.textContent = 'Return to sign in';
        continueButton.dataset.destination = 'login';
        show(`Password reset for ${data.member_id}.`, 'success');
        return;
      }

      await shareSession();
      recoveryResult.hidden = false;
      recoveryCodes.textContent = (data.recovery_codes || []).join('\n');
      continueButton.textContent = 'I saved the codes — open Amosclaud';
      continueButton.dataset.destination = 'platform';
      show(`Account ${data.member_id} is ready.`, 'success');
    } catch (error) {
      show(error.message || 'Organization account request failed.', 'error');
    } finally {
      submit.disabled = false;
    }
  });

  continueButton.addEventListener('click', () => {
    if (continueButton.dataset.destination === 'login') {
      setOrganizationMode('login');
      form.scrollIntoView({behavior: 'smooth', block: 'start'});
      return;
    }
    window.location.assign('/cloud/agent');
  });

  const params = new URLSearchParams(window.location.search);
  const method = params.get('method') === 'email' ? 'email' : 'organization';
  const requestedMode = params.get('mode');
  setOrganizationMode(['login', 'register', 'join', 'recover'].includes(requestedMode) ? requestedMode : 'login');
  chooseMethod(method, false);
})();
