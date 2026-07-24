(() => {
  let installPrompt = null;

  async function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    try {
      await navigator.serviceWorker.register('/service-worker.js', {scope: '/'});
    } catch (error) {
      console.warn('Amosclaud app service worker registration failed', error);
    }
  }

  function activateRepositoryShortcuts() {
    const repositoryId = localStorage.getItem('amosclaud-last-repository-id');
    const repositoryName = localStorage.getItem('amosclaud-last-repository-name');
    if (!repositoryId) return;
    document.querySelectorAll('a[href="/repositories"]').forEach(link => {
      link.href = `/workspace/${encodeURIComponent(repositoryId)}`;
      if (link.classList.contains('notebook-action')) link.textContent = 'My repository';
      const strong = link.querySelector('strong');
      const description = link.querySelector('span');
      if (strong) strong.textContent = 'Open repository';
      if (description) description.textContent = repositoryName || 'Continue your last repository';
    });
  }

  function isStandalone() {
    return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  }

  function createInstallButton() {
    if (isStandalone() || document.getElementById('install-amosclaud-app')) return;
    const button = document.createElement('button');
    button.id = 'install-amosclaud-app';
    button.type = 'button';
    button.textContent = 'Install Amosclaud app';
    button.setAttribute('aria-label', 'Install Amosclaud on this device');
    Object.assign(button.style, {
      position: 'fixed', right: '14px', bottom: '14px', zIndex: '9999',
      border: '0', borderRadius: '12px', padding: '12px 16px',
      background: '#2563eb', color: '#fff', fontWeight: '700',
      boxShadow: '0 12px 32px rgba(15,23,42,.28)', cursor: 'pointer'
    });
    button.hidden = !installPrompt;
    button.addEventListener('click', async () => {
      if (!installPrompt) return;
      installPrompt.prompt();
      await installPrompt.userChoice;
      installPrompt = null;
      button.remove();
    });
    document.body.appendChild(button);
  }

  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    installPrompt = event;
    createInstallButton();
    const button = document.getElementById('install-amosclaud-app');
    if (button) button.hidden = false;
  });

  window.addEventListener('appinstalled', () => {
    installPrompt = null;
    document.getElementById('install-amosclaud-app')?.remove();
  });

  activateRepositoryShortcuts();
  registerServiceWorker();
  createInstallButton();
})();
