(() => {
  const challenge = new URLSearchParams(window.location.search).get('challenge') || '';
  const approveButton = document.getElementById('approve-button');
  const requestedUsername = document.getElementById('requested-username');
  const result = document.getElementById('code-result');
  const trustedCode = document.getElementById('trusted-code');
  const message = document.getElementById('message');

  function show(text, kind = '') {
    message.textContent = text || '';
    message.className = `message ${kind}`.trim();
  }

  async function request(url, options = {}) {
    const response = await fetch(url, {
      credentials: 'same-origin',
      cache: 'no-store',
      ...options,
      headers: {'Content-Type': 'application/json', ...(options.headers || {})},
    });
    const text = await response.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (_) { data = {detail: text}; }
    if (!response.ok) throw new Error(data.detail || `Approval failed (${response.status})`);
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
    bytes.forEach(byte => { raw += String.fromCharCode(byte); });
    return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  }

  function prepareAuthenticationOptions(options) {
    return {
      ...options,
      challenge: base64urlToBytes(options.challenge),
      allowCredentials: (options.allowCredentials || []).map(item => ({
        ...item,
        id: base64urlToBytes(item.id),
      })),
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
        userHandle: credential.response.userHandle
          ? bytesToBase64url(credential.response.userHandle)
          : null,
      },
    };
  }

  approveButton.addEventListener('click', async () => {
    if (!challenge) {
      show('This QR login link is incomplete.', 'error');
      return;
    }
    if (!window.isSecureContext || !window.PublicKeyCredential || !navigator.credentials) {
      show('Trusted-device approval requires HTTPS and a passkey-capable browser.', 'error');
      return;
    }
    approveButton.disabled = true;
    show('Waiting for fingerprint, face, PIN, or security-key confirmation…');
    try {
      const start = await request('/api/v1/auth/login/qr/device/start', {
        method: 'POST',
        body: JSON.stringify({challenge}),
      });
      requestedUsername.textContent = start.username;
      const credential = await navigator.credentials.get({
        publicKey: prepareAuthenticationOptions(start.public_key),
      });
      if (!credential) throw new Error('Device confirmation was cancelled.');
      const finished = await request('/api/v1/auth/login/qr/device/finish', {
        method: 'POST',
        body: JSON.stringify({
          challenge,
          attempt: start.attempt,
          credential: serialiseAuthenticationCredential(credential),
        }),
      });
      trustedCode.textContent = finished.code;
      result.classList.remove('hidden');
      approveButton.classList.add('hidden');
      show('Trusted device confirmed. Use the code on your original browser.', 'success');
    } catch (error) {
      const cancelled = error?.name === 'NotAllowedError';
      show(cancelled ? 'Device confirmation was cancelled or timed out.' : error.message, 'error');
      approveButton.disabled = false;
    }
  });

  if (!challenge) {
    approveButton.disabled = true;
    show('This QR login link is incomplete.', 'error');
  }
})();
