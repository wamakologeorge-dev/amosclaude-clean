(() => {
  const form = document.getElementById('auth-form');
  const identifier = document.getElementById('identifier');
  const message = document.getElementById('message');
  const passkeyButton = document.getElementById('passkey-login-button');
  if (!form || !identifier || !message) return;

  function canonicalAddress(value) {
    let address = String(value || '').trim().toLowerCase();
    if (!address.includes('@')) return address;
    const [local, domain] = address.split('@', 2);
    if (domain === 'www.amosclaud.com') return `${local}@amosclaud.com`;
    return address;
  }

  // Older versions displayed addresses such as user@www.amosclaud.com even
  // though the account database stores user@amosclaud.com. Correct that
  // legacy display form before the existing login handler sends the request.
  form.addEventListener('submit', () => {
    const corrected = canonicalAddress(identifier.value);
    if (corrected !== identifier.value.trim().toLowerCase()) {
      identifier.value = corrected;
      message.textContent = `Using your Amosclaud account: ${corrected}`;
      message.className = 'message success';
    }
  }, true);

  // Explain what a stale Android passkey means. This can happen when an older
  // deployment stored authentication data on an ephemeral filesystem.
  passkeyButton?.addEventListener('click', () => {
    window.setTimeout(() => {
      if (/not linked to an Amosclaud account/i.test(message.textContent || '')) {
        message.textContent = 'This saved device key belongs to an older account record. Sign in with the matching Amosclaud mail and password once, then add a new passkey. Do not create another account.';
      }
    }, 500);
  });
})();
