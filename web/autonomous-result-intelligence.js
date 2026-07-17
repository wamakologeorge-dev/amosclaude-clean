(() => {
  const root = document.getElementById('live-autonomous-workbench');
  if (!root) return;
  const results = root.querySelector('[data-workbench-results]');

  function organizeResultLinks() {
    results?.querySelectorAll('a.workbench-result-link').forEach(link => {
      const value = link.getAttribute('href') || '';
      const row = link.closest('.workbench-item');
      if (!row || row.dataset.organized === 'true') return;
      row.dataset.organized = 'true';

      const title = document.createElement('strong');
      const summary = document.createElement('span');
      if (/fastapi\.tiangolo\.com\/advanced\/events/i.test(value)) {
        title.textContent = 'FastAPI lifespan migration reference';
        summary.textContent = 'Amosclaud found a deprecated startup event. Replace it with the application lifespan handler. The external documentation is optional.';
        link.textContent = 'Open official documentation';
        link.target = '_blank';
      } else if (/^https?:\/\//i.test(value)) {
        title.textContent = 'External verified result';
        summary.textContent = 'This evidence is hosted outside Amosclaud and opens in a new tab.';
        link.textContent = 'Open external result';
        link.target = '_blank';
      } else {
        title.textContent = value.startsWith('/pipelines/') ? 'Amosclaud pipeline evidence' : 'Amosclaud result';
        summary.textContent = value;
        link.textContent = 'Open inside Amosclaud';
      }
      row.prepend(summary);
      row.prepend(title);
    });
  }

  window.addEventListener('amosclaud:agent-result', () => setTimeout(organizeResultLinks, 0));
})();
