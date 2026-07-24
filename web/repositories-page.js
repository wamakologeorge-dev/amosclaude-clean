(() => {
  const search = document.getElementById('repository-search');
  const visibility = document.getElementById('repository-visibility-filter');
  const grid = document.getElementById('repository-grid');
  const userLabel = document.getElementById('current-user');
  const ownerLabel = document.getElementById('repo-owner-name');
  const avatar = document.getElementById('repo-avatar');

  function applyFilters() {
    const query = (search?.value || '').trim().toLowerCase();
    const selected = visibility?.value || 'all';
    grid?.querySelectorAll('.repository-card').forEach(card => {
      const text = card.textContent.toLowerCase();
      const isPublic = card.querySelector('.visibility-public');
      const matchesVisibility = selected === 'all' || (selected === 'public' ? isPublic : !isPublic);
      card.hidden = !(text.includes(query) && matchesVisibility);
    });
  }

  search?.addEventListener('input', applyFilters);
  visibility?.addEventListener('change', applyFilters);
  if (grid) new MutationObserver(applyFilters).observe(grid, { childList: true, subtree: true });

  async function loadProfile() {
    try {
      const response = await fetch('/api/v1/auth/me', { credentials: 'same-origin' });
      if (!response.ok) return;
      const user = await response.json();
      const name = user.name || user.email || 'Amosclaud developer';
      if (userLabel) userLabel.textContent = name;
      if (ownerLabel) ownerLabel.textContent = name;
      if (avatar) avatar.textContent = name.split(/\s+/).map(part => part[0]).join('').slice(0, 2).toUpperCase();
    } catch (_) {}
  }

  loadProfile();
})();
