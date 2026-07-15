(() => {
  const form = document.getElementById('auth-form');
  const identifier = document.getElementById('identifier');
  const message = document.getElementById('message');
  if (!form || !identifier || !message) return;

  function canonicalAddress(value) {
    const address = String(value || '').trim().toLowerCase();
    if (!address.includes('@')) return address;
    const [local, domain] = address.split('@', 2);
    return domain === 'www.amosclaud.com' ? `${local}@amosclaud.com` : address;
  }

  form.addEventListener('submit', () => {
    const corrected = canonicalAddress(identifier.value);
    if (corrected !== identifier.value.trim().toLowerCase()) {
      identifier.value = corrected;
      message.textContent = `Using your Amosclaud account: ${corrected}`;
      message.className = 'message success';
    }
  }, true);

  const stalePasskeyPattern = /not linked to an Amosclaud account/i;
  const observer = new MutationObserver(() => {
    if (stalePasskeyPattern.test(message.textContent || '')) {
      message.textContent = 'This saved device key belongs to an older account record. Sign in with the matching Amosclaud mail and password once, then add a new passkey. Do not create another account.';
      message.className = 'message';
    }
  });
  observer.observe(message, {childList: true, characterData: true, subtree: true});
})();
