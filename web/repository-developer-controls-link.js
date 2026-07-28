(() => {
  const grid = document.getElementById('repository-grid');
  if (!grid) return;

  let imported = new Map();

  async function loadTargets() {
    try {
      const response = await fetch('/api/v1/github/repository-management/imported', {
        credentials: 'same-origin',
      });
      if (!response.ok) return;
      const payload = await response.json();
      imported = new Map(
        (payload.repositories || []).map(item => [String(item.repository_id), item.github_full_name]),
      );
      decorate();
    } catch (error) {
      console.warn('[Repository developer controls]', error);
    }
  }

  function decorate() {
    grid.querySelectorAll('.repository-card[data-repository-id]').forEach(card => {
      const repositoryId = String(card.dataset.repositoryId || '');
      const fullName = imported.get(repositoryId);
      const actions = card.querySelector('.repository-actions');
      if (!fullName || !actions || actions.querySelector('[data-action="developer-settings"]')) return;
      const link = document.createElement('a');
      link.className = 'btn-ghost';
      link.dataset.action = 'developer-settings';
      link.href = `/static/repository-developer-settings.html?repository_id=${encodeURIComponent(repositoryId)}`;
      link.textContent = 'Developer settings';
      link.setAttribute('aria-label', `Manage GitHub settings for ${fullName}`);
      link.addEventListener('click', event => event.stopPropagation());
      actions.appendChild(link);
    });
  }

  new MutationObserver(decorate).observe(grid, { childList: true, subtree: true });
  document.addEventListener('amosclaud:repositories-changed', loadTargets);
  loadTargets();
})();
