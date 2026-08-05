(() => {
  const originalFetch = window.fetch.bind(window);
  const sessionCreatingPaths = new Set([
    '/api/v1/auth/login',
    '/api/v1/auth/login/verify-code',
    '/api/v1/auth/login/passkey/finish',
    '/api/v1/auth/register/verify',
  ]);

  window.fetch = async (input, init) => {
    const response = await originalFetch(input, init);
    try {
      const url = new URL(typeof input === 'string' ? input : input.url, window.location.href);
      if (response.ok && sessionCreatingPaths.has(url.pathname)) {
        await originalFetch('/api/v1/account/share-session', {
          method: 'POST',
          credentials: 'same-origin',
          cache: 'no-store',
        });
      }
    } catch (_) {
      // Sharing the session across configured sibling hosts is a convenience.
      // Never hide or replace the result of the actual authentication request.
    }
    return response;
  };
})();
