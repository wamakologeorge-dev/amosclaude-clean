(() => {
  const parts = location.pathname.split('/').filter(Boolean);
  const repositoryId = parts.length === 2 && parts[0] === 'workspace' ? parts[1] : '';
  if (!/^\d+$/.test(repositoryId)) return;

  const branchSelect = document.getElementById('ws-branch');
  const currentFile = document.getElementById('ws-current-file');
  const viewPane = document.getElementById('ws-view');
  const searchInput = document.getElementById('ws-file-search');
  const codeGrid = document.querySelector('.ws-code-grid');

  let repository = null;
  let overviewRequest = 0;
  let fileRenderRequest = 0;

  async function api(path) {
    const response = await fetch(path, { credentials: 'same-origin' });
    if (response.status === 401) {
      location.assign('/login');
      throw new Error('Your session expired. Sign in again.');
    }
    const contentType = response.headers.get('content-type') || '';
    const raw = await response.text();
    let data = null;
    if (raw) {
      data = contentType.includes('application/json') ? JSON.parse(raw) : { detail: raw };
    }
    if (!response.ok) throw new Error(data?.detail || `Request failed (${response.status})`);
    return data;
  }

  const escapeHtml = value => String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

  const branch = () => branchSelect?.value || repository?.default_branch || 'main';
  const markdownPath = path => /(?:^|\/)(?:readme(?:\.[^/]*)?|[^/]+\.(?:md|markdown|mdown|mkd))$/i.test(path || '');
  const formatNumber = value => new Intl.NumberFormat().format(Number(value || 0));

  function humanSize(value) {
    const size = Number(value || 0);
    if (size < 1024) return `${size} B`;
    if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`;
    if (size < 1024 ** 3) return `${(size / 1024 ** 2).toFixed(1)} MB`;
    return `${(size / 1024 ** 3).toFixed(1)} GB`;
  }

  function cssEscape(value) {
    if (window.CSS?.escape) return window.CSS.escape(value);
    return String(value).replace(/(["\\])/g, '\\$1');
  }

  function ensureOverview() {
    let overview = document.getElementById('amos-repository-overview');
    if (overview || !codeGrid) return overview;
    overview = document.createElement('section');
    overview.id = 'amos-repository-overview';
    overview.className = 'amos-repository-overview';
    overview.innerHTML = `
      <article class="amos-readme-card" aria-labelledby="amos-readme-title">
        <header class="amos-readme-header">
          <div><strong id="amos-readme-title">README</strong><span id="amos-readme-path"></span></div>
          <button id="amos-edit-readme" type="button" hidden>Edit</button>
        </header>
        <div id="amos-readme-content" class="amos-markdown-body amos-markdown-loading">Loading README…</div>
      </article>
      <aside class="amos-repository-sidebar" aria-label="Repository details">
        <section class="amos-about-card">
          <h2>About</h2>
          <p id="amos-about-description">Loading repository details…</p>
          <div id="amos-policy-links" class="amos-policy-links"></div>
        </section>
        <section class="amos-stat-card" id="amos-stat-card"></section>
        <section class="amos-language-card" id="amos-language-card"></section>
      </aside>`;
    codeGrid.insertAdjacentElement('afterend', overview);
    overview.addEventListener('click', event => {
      const target = event.target.closest('[data-repository-path]');
      if (!target) return;
      event.preventDefault();
      openRepositoryPath(target.dataset.repositoryPath);
    });
    document.getElementById('amos-edit-readme')?.addEventListener('click', () => {
      const path = document.getElementById('amos-edit-readme')?.dataset.repositoryPath;
      if (path) openRepositoryPath(path);
    });
    return overview;
  }

  function policyLink(label, path) {
    if (!path) return '';
    return `<a href="#" data-repository-path="${escapeHtml(path)}">${escapeHtml(label)}</a>`;
  }

  function renderSidebar(details, issues, pullRequests) {
    const description = repository?.description?.trim() || 'No repository description has been added yet.';
    document.getElementById('amos-about-description').textContent = description;

    const features = details.features || {};
    const policies = [
      policyLink(details.license_label || 'License', features.license),
      policyLink('Code of conduct', features.code_of_conduct),
      policyLink('Contributing', features.contributing),
      policyLink('Security policy', features.security_policy),
    ].filter(Boolean).join('');
    document.getElementById('amos-policy-links').innerHTML = policies || '<span>No policy files detected.</span>';

    const stats = [
      ['Commits', details.commit_count],
      ['Branches', details.branch_count],
      ['Tags', details.tag_count],
      ['Files', details.file_count],
      ['Open issues', issues.filter(item => item.state === 'open').length],
      ['Open pull requests', pullRequests.filter(item => item.state === 'open').length],
    ];
    document.getElementById('amos-stat-card').innerHTML = `
      <h2>Repository activity</h2>
      <dl>${stats.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${formatNumber(value)}</dd></div>`).join('')}</dl>
      <p>${humanSize(details.repository_size)} stored · ${escapeHtml(repository?.visibility || 'private')} repository</p>`;

    const languages = details.languages || [];
    document.getElementById('amos-language-card').innerHTML = languages.length ? `
      <h2>Languages</h2>
      <div class="amos-language-bar" aria-label="Repository language distribution">
        ${languages.map(item => `<span style="width:${Number(item.percentage).toFixed(2)}%" title="${escapeHtml(item.name)} ${Number(item.percentage).toFixed(1)}%"></span>`).join('')}
      </div>
      <ul>${languages.slice(0, 6).map(item => `<li><span></span><strong>${escapeHtml(item.name)}</strong><em>${Number(item.percentage).toFixed(1)}%</em></li>`).join('')}</ul>` : `
      <h2>Languages</h2><p>No source-language files detected.</p>`;
  }

  async function renderReadme(readmePath) {
    const content = document.getElementById('amos-readme-content');
    const label = document.getElementById('amos-readme-path');
    const edit = document.getElementById('amos-edit-readme');
    if (!content || !label || !edit) return;

    if (!readmePath) {
      label.textContent = '';
      edit.hidden = true;
      content.className = 'amos-markdown-body amos-markdown-empty';
      content.innerHTML = '<h2>Add a README</h2><p>A README explains what this repository does, how to run it, and how other developers should use it.</p>';
      return;
    }

    label.textContent = readmePath;
    edit.hidden = !['owner', 'developer'].includes(repository?.role);
    edit.dataset.repositoryPath = readmePath;
    content.className = 'amos-markdown-body amos-markdown-loading';
    content.textContent = 'Rendering README…';
    const payload = await api(`/api/v1/repositories/${repositoryId}/markdown?path=${encodeURIComponent(readmePath)}&branch=${encodeURIComponent(branch())}`);
    content.className = 'amos-markdown-body';
    content.innerHTML = payload.html;
  }

  async function loadOverview() {
    ensureOverview();
    const request = ++overviewRequest;
    try {
      repository = repository || await api(`/api/v1/repositories/${repositoryId}`);
      const selectedBranch = branch();
      const [tree, details, issues, pullRequests] = await Promise.all([
        api(`/api/v1/repositories/${repositoryId}/tree?branch=${encodeURIComponent(selectedBranch)}`),
        api(`/api/v1/repositories/${repositoryId}/overview?branch=${encodeURIComponent(selectedBranch)}`),
        api(`/api/v1/repositories/${repositoryId}/issues`),
        api(`/api/v1/repositories/${repositoryId}/pull-requests`),
      ]);
      if (request !== overviewRequest) return;
      const rootReadmes = tree
        .filter(item => item.type === 'file' && !item.path.includes('/') && /^readme(?:\.|$)/i.test(item.path))
        .sort((left, right) => left.path.localeCompare(right.path));
      renderSidebar(details, issues, pullRequests);
      await renderReadme(rootReadmes[0]?.path || '');
    } catch (error) {
      const content = document.getElementById('amos-readme-content');
      if (content && request === overviewRequest) {
        content.className = 'amos-markdown-body amos-markdown-error';
        content.textContent = `README could not be rendered: ${error.message}`;
      }
    }
  }

  function openRepositoryPath(path) {
    if (!path || !searchInput) return;
    searchInput.value = path;
    searchInput.dispatchEvent(new Event('input', { bubbles: true }));
    requestAnimationFrame(() => {
      const row = document.querySelector(`[data-file="${cssEscape(path)}"]`);
      row?.click();
      row?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
  }

  async function renderSelectedMarkdown() {
    const path = currentFile?.textContent?.trim() || '';
    if (!viewPane || !markdownPath(path) || path === 'Select a file') return;
    const selectedBranch = branch();
    const identity = `${selectedBranch}:${path}`;
    if (viewPane.dataset.amosMarkdownIdentity === identity) return;
    const request = ++fileRenderRequest;
    try {
      const payload = await api(`/api/v1/repositories/${repositoryId}/markdown?path=${encodeURIComponent(path)}&branch=${encodeURIComponent(selectedBranch)}`);
      if (request !== fileRenderRequest || currentFile?.textContent?.trim() !== path) return;
      viewPane.dataset.amosMarkdownIdentity = identity;
      viewPane.innerHTML = `<article class="amos-markdown-body amos-file-markdown">${payload.html}</article>`;
    } catch (error) {
      if (request !== fileRenderRequest) return;
      viewPane.innerHTML = `<div class="ws-empty-row ws-error-row">Markdown rendering failed: ${escapeHtml(error.message)}</div>`;
    }
  }

  function installMarkdownViewer() {
    if (!viewPane || !currentFile) return;
    const observer = new MutationObserver(() => {
      const path = currentFile.textContent?.trim() || '';
      if (!markdownPath(path)) {
        delete viewPane.dataset.amosMarkdownIdentity;
        return;
      }
      if (!viewPane.querySelector('.amos-file-markdown')) {
        queueMicrotask(renderSelectedMarkdown);
      }
    });
    observer.observe(viewPane, { childList: true, subtree: true });
    observer.observe(currentFile, { childList: true, characterData: true, subtree: true });
  }

  function openRequestedPath() {
    const requested = new URLSearchParams(location.search).get('path');
    if (!requested) return;
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (!searchInput?.disabled) {
        clearInterval(timer);
        openRepositoryPath(requested);
      } else if (attempts > 80) {
        clearInterval(timer);
      }
    }, 100);
  }

  branchSelect?.addEventListener('change', () => {
    delete viewPane?.dataset.amosMarkdownIdentity;
    loadOverview();
  });

  document.addEventListener('click', event => {
    const link = event.target.closest('.amos-markdown-body a[data-repository-path]');
    if (!link) return;
    event.preventDefault();
    openRepositoryPath(link.dataset.repositoryPath);
  });

  ensureOverview();
  installMarkdownViewer();
  loadOverview();
  openRequestedPath();
})();
