(() => {
  const params = new URLSearchParams(location.search);
  const requestedPath = (params.get('path') || 'README.md').replace(/^\/+|\/+$/g, '');
  const requestedMode = params.get('mode') === 'edit' ? 'edit' : 'view';
  const tree = document.getElementById('eow-tree');
  const search = document.getElementById('eow-search');
  const editButton = document.getElementById('eow-edit-mode');
  const shell = document.getElementById('eow-shell');

  if (!tree || !requestedPath) return;

  let opened = false;
  let searchApplied = false;

  const matchingOpenButton = () => [...tree.querySelectorAll('[data-open-path]')]
    .find(button => button.dataset.openPath === requestedPath && button.dataset.openType === 'file');

  const enterRequestedMode = () => {
    if (requestedMode !== 'edit') return;
    const waitForEditor = window.setInterval(() => {
      if (!shell?.hidden && editButton && !editButton.disabled) {
        window.clearInterval(waitForEditor);
        editButton.click();
        document.getElementById('eow-editor')?.focus();
      }
    }, 100);
    window.setTimeout(() => window.clearInterval(waitForEditor), 8000);
  };

  const tryOpen = () => {
    if (opened) return;
    let button = matchingOpenButton();
    if (!button && !searchApplied && search && !search.disabled) {
      searchApplied = true;
      search.value = requestedPath;
      search.dispatchEvent(new Event('input', { bubbles: true }));
      button = matchingOpenButton();
    }
    if (!button) return;
    opened = true;
    observer.disconnect();
    button.click();
    enterRequestedMode();
  };

  const observer = new MutationObserver(tryOpen);
  observer.observe(tree, { childList: true, subtree: true });
  tryOpen();
  window.setTimeout(() => observer.disconnect(), 10000);
})();
