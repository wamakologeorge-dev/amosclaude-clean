(() => {
  const originalFetch = window.fetch.bind(window);

  window.fetch = async (input, init) => {
    const response = await originalFetch(input, init);
    const url = typeof input === 'string' ? input : String(input?.url || '');

    if (url.endsWith('/api/v1/auth/register/request-code') && response.ok) {
      response.clone().json().then(data => {
        if (data?.account_created) {
          window.location.replace('/cloud/agent');
        }
      }).catch(() => {});
    }

    return response;
  };
})();
