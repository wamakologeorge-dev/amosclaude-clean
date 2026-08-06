(() => {
  const form = document.getElementById('organization-form');
  const ownerForm = document.getElementById('owner-form');
  const message = document.getElementById('message');
  const ownerMessage = document.getElementById('owner-message');
  const recoveryResult = document.getElementById('recovery-result');
  const recoveryCodes = document.getElementById('recovery-codes');
  const continueButton = document.getElementById('continue-button');
  const tabs = Array.from(document.querySelectorAll('[data-mode]'));
  let mode = 'login';

  const fields = {
    organizationName: document.getElementById('organization-name-field'),
    accessCode: document.getElementById('access-code-field'),
    recoveryCode: document.getElementById('recovery-code-field'),
  };
  const inputs = {
    organizationName: document.getElementById('organization-name'),
    organizationId: document.getElementById('organization-id'),
    identity: document.getElementById('identity'),
    accessCode: document.getElementById('access-code'),
    recoveryCode: document.getElementById('recovery-code'),
    password: document.getElementById('password'),
  };

  function show(target, text, kind = '') {
    target.textContent = text || '';
    target.className = `message ${kind}`.trim();
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    const text = await response.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch (_) {
      data = { detail: text };
    }
    if (!response.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map(item => item.msg || item.message).join(' ')
        : data.detail;
      throw new Error(detail || `Request failed (${response.status})`);
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
    input.required = required;
  }

  function setMode(nextMode) {
    mode = nextMode;
    recoveryResult.hidden = true;
    form.reset();
    tabs.forEach(tab => tab.classList.toggle('active', tab.dataset.mode === mode));
    fields.organizationName.hidden = mode !== 'register';
    fields.accessCode.hidden = mode !== 'join';
    fields.recoveryCode.hidden = mode !== 'recover';
    setRequired(inputs.organizationName, mode === 'register');
    setRequired(inputs.accessCode, mode === 'join');
    setRequired(inputs.recoveryCode, mode === 'recover');

    const title = document.getElementById('access-title');
    const subtitle = document.getElementById('access-subtitle');
    const identityLabel = document.getElementById('identity-label');
    const passwordLabel = document.getElementById('password-label');
    const submit = document.getElementById('submit');

    if (mode === 'login') {
      title.textContent = 'Sign in to an organization';
      subtitle.textContent = 'Use your five-digit organization ID and username or member ID.';
      identityLabel.firstChild.textContent = 'Username or member ID';
      inputs.identity.placeholder = 'johnM or 11111-2131';
      passwordLabel.firstChild.textContent = 'Password';
      inputs.password.autocomplete = 'current-password';
      submit.textContent = 'Sign in';
    } else if (mode === 'register') {
      title.textContent = 'Create an organization account';
      subtitle.textContent = 'Choose an available five-digit organization ID and become its owner.';
      identityLabel.firstChild.textContent = 'Owner username';
      inputs.identity.placeholder = 'johnM';
      passwordLabel.firstChild.textContent = 'Create password';
      inputs.password.autocomplete = 'new-password';
      submit.textContent = 'Create organization';
    } else if (mode === 'join') {
      title.textContent = 'Join an existing organization';
      subtitle.textContent = 'Use the temporary access code provided by an organization owner or admin.';
      identityLabel.firstChild.textContent = 'Create username';
      inputs.identity.placeholder = 'sameG';
      passwordLabel.firstChild.textContent = 'Create password';
      inputs.password.autocomplete = 'new-password';
      submit.textContent = 'Join organization';
    } else {
      title.textContent = 'Recover an organization account';
      subtitle.textContent = 'Use one unused recovery code and create a new password.';
      identityLabel.firstChild.textContent = 'Username or member ID';
      inputs.identity.placeholder = 'johnM or 11111-2131';
      passwordLabel.firstChild.textContent = 'New password';
      inputs.password.autocomplete = 'new-password';
      submit.textContent = 'Recover account';
    }
    show(message, '');
  }

  tabs.forEach(tab => tab.addEventListener('click', () => setMode(tab.dataset.mode)));

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const submit = document.getElementById('submit');
    submit.disabled = true;
    show(message, 'Working…');
    const organizationId = inputs.organizationId.value.trim();
    const identity = inputs.identity.value.trim();
    const password = inputs.password.value;

    try {
      let data;
      if (mode === 'login') {
        data = await request('/api/v1/organization-access/login', {
          method: 'POST',
          body: JSON.stringify({
            organization_id: organizationId,
            username_or_member_id: identity,
            password,
          }),
        });
        await shareSession();
        show(message, `Signed in as ${data.member_id}.`, 'success');
        window.location.assign('/cloud/agent');
        return;
      }
      if (mode === 'register') {
        data = await request('/api/v1/organization-access/register', {
          method: 'POST',
          body: JSON.stringify({
            organization_id: organizationId,
            organization_name: inputs.organizationName.value.trim(),
            username: identity,
            password,
          }),
        });
      } else if (mode === 'join') {
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
        show(message, `Password reset for ${data.member_id}.`, 'success');
        return;
      }

      await shareSession();
      recoveryResult.hidden = false;
      recoveryCodes.textContent = (data.recovery_codes || []).join('\n');
      continueButton.textContent = 'I saved the codes — open Amosclaud';
      continueButton.dataset.destination = 'platform';
      show(message, `Account ${data.member_id} is ready.`, 'success');
    } catch (error) {
      show(message, error.message || 'Organization account request failed.', 'error');
    } finally {
      submit.disabled = false;
    }
  });

  continueButton.addEventListener('click', () => {
    if (continueButton.dataset.destination === 'login') {
      setMode('login');
      window.scrollTo({ top: 0, behavior: 'smooth' });
      return;
    }
    window.location.assign('/cloud/agent');
  });

  const ownerAction = document.getElementById('owner-action');
  const memberNumberField = document.getElementById('member-number-field');
  const memberNumberInput = document.getElementById('member-number');
  const newOrganizationIdField = document.getElementById('new-organization-id-field');
  const newOrganizationIdInput = document.getElementById('new-organization-id');
  const joinCodeOptions = document.getElementById('join-code-options');
  const ownerSubmit = document.getElementById('owner-submit');

  function updateOwnerAction() {
    const action = ownerAction.value;
    const usesMemberNumber = action === 'remove-member' || action === 'transfer-ownership';
    memberNumberField.hidden = !usesMemberNumber;
    newOrganizationIdField.hidden = action !== 'change-id';
    joinCodeOptions.hidden = action !== 'join-code';
    memberNumberInput.required = usesMemberNumber;
    newOrganizationIdInput.required = action === 'change-id';
    ownerSubmit.textContent = action === 'join-code'
      ? 'Create access code'
      : action === 'remove-member'
        ? 'Remove member'
        : action === 'transfer-ownership'
          ? 'Transfer ownership'
          : 'Change organization ID';
  }

  ownerAction.addEventListener('change', updateOwnerAction);
  updateOwnerAction();

  ownerForm.addEventListener('submit', async event => {
    event.preventDefault();
    if (!ownerForm.reportValidity()) return;
    ownerSubmit.disabled = true;
    document.getElementById('owner-result').hidden = true;
    show(ownerMessage, 'Working…');
    const organizationId = document.getElementById('owner-organization-id').value.trim();
    try {
      let data = null;
      if (ownerAction.value === 'join-code') {
        data = await request(`/api/v1/organization-access/${organizationId}/join-code`, {
          method: 'POST',
          body: JSON.stringify({
            expires_minutes: Number(document.getElementById('expires-minutes').value),
            uses: Number(document.getElementById('join-code-uses').value),
          }),
        });
      } else if (ownerAction.value === 'remove-member') {
        const memberNumber = memberNumberInput.value.trim();
        await request(`/api/v1/organization-access/${organizationId}/members/${memberNumber}`, {
          method: 'DELETE',
        });
        data = { result: `Membership ${organizationId}-${memberNumber} was revoked.` };
      } else if (ownerAction.value === 'transfer-ownership') {
        const memberNumber = memberNumberInput.value.trim();
        data = await request(`/api/v1/organization-access/${organizationId}/transfer-ownership`, {
          method: 'POST',
          body: JSON.stringify({ member_number: memberNumber }),
        });
      } else {
        const newId = newOrganizationIdInput.value.trim();
        data = await request(`/api/v1/organization-access/${organizationId}/identifier`, {
          method: 'PATCH',
          body: JSON.stringify({ organization_id: newId }),
        });
      }
      const result = document.getElementById('owner-result');
      result.textContent = JSON.stringify(data, null, 2);
      result.hidden = false;
      show(ownerMessage, 'Organization control completed.', 'success');
    } catch (error) {
      show(ownerMessage, error.message || 'Organization control failed.', 'error');
    } finally {
      ownerSubmit.disabled = false;
    }
  });

  setMode('login');
})();
