(() => {
  const message = document.getElementById('message');
  const params = new URLSearchParams(window.location.search);
  const error = params.get('error');

  if (error && message) {
    message.textContent = error;
  }

  (async () => {
    try {
      const response = await fetch('/api/v1/auth/me', { credentials: 'same-origin' });
      if (response.ok) window.location.assign('/');
    } catch (_) {
      // Keep the Google sign-in page available while the server reconnects.
    }
  })();
})();
