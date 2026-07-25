(() => {
  const repositoryId = location.pathname.split('/').filter(Boolean).pop();
  const branchSelect = document.getElementById('ws-branch');
  const tree = document.getElementById('ws-tree');
  const editor = document.getElementById('ws-editor');
  const editorShell = document.getElementById('ws-editor-shell');
  const editorEmpty = document.getElementById('ws-editor-empty');
  const currentFile = document.getElementById('ws-current-file');
  const status = document.getElementById('ws-status');
  const output = document.getElementById('ws-output');
  const breadcrumbs = document.getElementById('ws-breadcrumbs');
  const searchInput = document.getElementById('ws-file-search');
  const notFound = document.getElementById('ws-not-found');
  const viewPane = document.getElementById('ws-view');
  const editPane = document.getElementById('ws-edit');
  const historyPane = document.getElementById('ws-history');
  const blamePane = document.getElementById('ws-blame');

  let selectedPath = '';
  let currentPath = '';
  let repository = null;
  let entries = [];
  let openFileData = null;
  const tabLoaded = {};

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      ...options,
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...(options.headers || {}),
      },
    });
    if (response.status === 401) {
      location.assign('/login');
      throw Object.assign(new Error('Your session expired. Sign in again.'), { status: 401 });
    }
    if (response.status === 204) return null;
    const contentType = response.headers.get('content-type') || '';
    const raw = await response.text();
    let data = null;
    if (raw) {
      if (contentType.includes('application/json')) {
        try { data = JSON.parse(raw); } catch { data = { detail: 'The server returned invalid JSON.' }; }
      } else {
        data = { detail: raw.trim() || `Request failed (${response.status})` };
      }
    }
    if (!response.ok) {
      const detail = data?.detail || data?.message || `Request failed (${response.status})`;
      const message = typeof detail === 'string' ? detail : JSON.stringify(detail);
      throw Object.assign(new Error(message), { status: response.status, data });
    }
    return data;
  }

  const branch = () => branchSelect.value || repository?.default_branch || 'main';
  const setStatus = message => { status.textContent = message; };
  const escapeHtml = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  const baseName = path => path.split('/').filter(Boolean).pop() || path;
  const parentPath = path => path.split('/').filter(Boolean).slice(0, -1).join('/');
  const joinPath = (left, right) => [left, right].filter(Boolean).join('/');
  const extOf = path => (path.split('.').pop() || '').toLowerCase();

  function humanSize(size) {
    if (!size) return '—';
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }

  // --- Authoritative "Repository not found" banner ------------------------
  // The banner is driven ONLY by the repository-metadata request. It appears
  // when that request genuinely returns 403/404 and is hidden again whenever
  // metadata loads successfully. It never keys off arbitrary status text.
  function showNotFound() {
    document.getElementById('ws-repo-meta').textContent = 'Unavailable';
    document.querySelectorAll('#ws-branch,#ws-new-branch,#ws-file-search,#ws-new-folder,#ws-new-file')
      .forEach(control => { control.disabled = true; });
    document.querySelectorAll('.ws-panel').forEach(panel => { panel.hidden = true; });
    const tabs = document.querySelector('.ws-tabs');
    if (tabs) tabs.hidden = true;
    if (notFound) notFound.hidden = false;
  }

  function hideNotFound() {
    if (notFound) notFound.hidden = true;
    const tabs = document.querySelector('.ws-tabs');
    if (tabs) tabs.hidden = false;
    document.querySelectorAll('.ws-panel').forEach(panel => { panel.hidden = false; });
    document.querySelectorAll('#ws-file-search,#ws-new-folder,#ws-new-file,#ws-branch,#ws-new-branch')
      .forEach(control => { control.disabled = false; });
  }

  // --- Self-contained syntax highlighter (no external CDN) ----------------
  const KEYWORDS = new Set(('await async function return if else for while do break continue const let var ' +
    'new class extends super import export from default try catch finally throw typeof instanceof in of ' +
    'switch case yield this null true false undefined void delete def elif except with as pass lambda ' +
    'raise global nonlocal print not and or is None True False self int str float bool list dict set ' +
    'public private protected static final void interface enum struct package type namespace').split(' '));
  const HASH_COMMENT = new Set(['py', 'rb', 'sh', 'bash', 'yml', 'yaml', 'toml', 'ini', 'conf', 'env', 'cfg']);

  function highlight(code, ext) {
    const patterns = [];
    if (HASH_COMMENT.has(ext)) patterns.push(['tok-comment', /#[^\n]*/y]);
    else patterns.push(['tok-comment', /\/\/[^\n]*|\/\*[\s\S]*?\*\//y]);
    patterns.push(['tok-string', /"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`/y]);
    patterns.push(['tok-number', /\b\d[\d_.]*(?:e[+-]?\d+)?\b/y]);
    patterns.push(['tok-name', /[A-Za-z_$][A-Za-z0-9_$]*/y]);
    let out = '';
    let i = 0;
    while (i < code.length) {
      let matched = false;
      for (const [cls, re] of patterns) {
        re.lastIndex = i;
        const m = re.exec(code);
        if (m && m.index === i && m[0].length) {
          const text = m[0];
          if (cls === 'tok-name') {
            out += KEYWORDS.has(text) ? `<span class="tok-keyword">${escapeHtml(text)}</span>` : escapeHtml(text);
          } else {
            out += `<span class="${cls}">${escapeHtml(text)}</span>`;
          }
          i += text.length;
          matched = true;
          break;
        }
      }
      if (!matched) { out += escapeHtml(code[i]); i += 1; }
    }
    return out;
  }

  function renderCode(content, ext) {
    const lines = content.split('\n');
    const gutter = lines.map((_, index) => `<span>${index + 1}</span>`).join('');
    const body = lines.map(line => `<span class="ws-code-line">${highlight(line, ext) || '&nbsp;'}</span>`).join('');
    return `<div class="ws-code-view"><div class="ws-gutter">${gutter}</div><pre class="ws-code-body"><code>${body}</code></pre></div>`;
  }

  // --- Minimal, escaped Markdown renderer (no raw HTML passthrough) -------
  function renderMarkdown(source) {
    const inline = text => escapeHtml(text)
      .replace(/`([^`]+)`/g, (_, code) => `<code>${code}</code>`)
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+|\/[^\s)]*)\)/g, (_, label, href) => `<a href="${escapeHtml(href)}" rel="noopener noreferrer nofollow" target="_blank">${label}</a>`);
    const lines = source.split('\n');
    const html = [];
    let inCode = false;
    let list = false;
    const closeList = () => { if (list) { html.push('</ul>'); list = false; } };
    for (const line of lines) {
      if (/^```/.test(line)) {
        if (inCode) { html.push('</code></pre>'); inCode = false; }
        else { closeList(); html.push('<pre class="ws-md-code"><code>'); inCode = true; }
        continue;
      }
      if (inCode) { html.push(escapeHtml(line)); continue; }
      const heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) { closeList(); html.push(`<h${heading[1].length}>${inline(heading[2])}</h${heading[1].length}>`); continue; }
      const item = line.match(/^\s*[-*+]\s+(.*)$/);
      if (item) { if (!list) { html.push('<ul>'); list = true; } html.push(`<li>${inline(item[1])}</li>`); continue; }
      if (!line.trim()) { closeList(); continue; }
      closeList();
      html.push(`<p>${inline(line)}</p>`);
    }
    if (inCode) html.push('</code></pre>');
    closeList();
    return `<div class="ws-markdown">${html.join('')}</div>`;
  }

  async function loadRepository() {
    repository = await api(`/api/v1/repositories/${repositoryId}`);
    document.getElementById('ws-repo-name').textContent = `${repository.owner_name}/${repository.name}`;
    document.getElementById('ws-repo-meta').textContent = `${repository.visibility} · ${repository.role}`;
    hideNotFound();
  }

  async function loadBranches() {
    const branches = await api(`/api/v1/repositories/${repositoryId}/branches`);
    branchSelect.innerHTML = branches.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('');
    if (repository?.default_branch && branches.includes(repository.default_branch)) branchSelect.value = repository.default_branch;
  }

  function directChildren(path) {
    const prefix = path ? `${path}/` : '';
    const map = new Map();
    entries.forEach(entry => {
      if (!entry.path.startsWith(prefix) || entry.path === path) return;
      const remainder = entry.path.slice(prefix.length);
      const [first, ...rest] = remainder.split('/');
      if (!first) return;
      const childPath = joinPath(path, first);
      const isDirectory = rest.length > 0 || entry.type === 'directory';
      const existing = map.get(childPath);
      if (!existing || isDirectory) map.set(childPath, { path: childPath, type: isDirectory ? 'directory' : 'file', size: entry.size || 0 });
    });
    return [...map.values()].sort((a, b) => (a.type === b.type ? a.path.localeCompare(b.path) : a.type === 'directory' ? -1 : 1));
  }

  function renderBreadcrumbs() {
    const parts = currentPath.split('/').filter(Boolean);
    const crumbs = [{ label: repository?.name || 'Repository', path: '' }];
    parts.forEach((part, index) => crumbs.push({ label: part, path: parts.slice(0, index + 1).join('/') }));
    breadcrumbs.innerHTML = crumbs.map((crumb, index) => `${index ? '<span>/</span>' : ''}<button type="button" data-breadcrumb="${escapeHtml(crumb.path)}">${escapeHtml(crumb.label)}</button>`).join('');
  }

  function fileIcon(entry) {
    return entry.type === 'directory' ? '📁' : '📄';
  }

  function renderTree() {
    renderBreadcrumbs();
    const query = searchInput.value.trim().toLowerCase();
    const rows = query
      ? entries.filter(entry => entry.type === 'file' && entry.path.toLowerCase().includes(query))
      : directChildren(currentPath);
    const parentRow = !query && currentPath
      ? `<button class="ws-tree-row ws-parent-row" type="button" data-directory="${escapeHtml(parentPath(currentPath))}"><span class="ws-file-icon">↩</span><span class="ws-file-name">..</span><span class="ws-file-size">—</span></button>`
      : '';
    const body = rows.map(entry => {
      const directory = entry.type === 'directory';
      return `<button class="ws-tree-row${entry.path === selectedPath ? ' active' : ''}" type="button" ${directory ? `data-directory="${escapeHtml(entry.path)}"` : `data-file="${escapeHtml(entry.path)}"`}>
        <span class="ws-file-icon">${fileIcon(entry)}</span>
        <span class="ws-file-name">${escapeHtml(query ? entry.path : baseName(entry.path))}</span>
        <span class="ws-file-size">${directory ? '—' : humanSize(entry.size)}</span>
      </button>`;
    }).join('');
    tree.innerHTML = parentRow + (body || '<div class="ws-empty-row">This folder is empty.</div>');
  }

  async function loadTree() {
    tree.textContent = 'Loading files…';
    entries = await api(`/api/v1/repositories/${repositoryId}/tree?branch=${encodeURIComponent(branch())}`);
    renderTree();
  }

  async function loadCommits() {
    const list = document.getElementById('ws-commits');
    list.textContent = 'Loading commits…';
    try {
      const commits = await api(`/api/v1/repositories/${repositoryId}/commits?branch=${encodeURIComponent(branch())}&limit=50`);
      list.innerHTML = commits.map(commit => `<article class="ws-commit">
        <strong>${escapeHtml(commit.message)}</strong>
        <span>${escapeHtml(commit.sha.slice(0, 7))} committed by ${escapeHtml(commit.author)}</span>
      </article>`).join('') || '<div class="ws-empty-row">No commits yet.</div>';
    } catch (error) {
      list.innerHTML = `<div class="ws-empty-row ws-error-row">Could not load commits: ${escapeHtml(error.message)}</div>`;
    }
  }

  async function loadIssues() {
    const container = document.getElementById('ws-issues');
    container.innerHTML = '<div class="ws-empty-row">Loading issues…</div>';
    try {
      const issues = await api(`/api/v1/repositories/${repositoryId}/issues`);
      container.innerHTML = issues.length ? issues.map(issue => `<div class="ws-tool-item">
        <strong>#${issue.id} ${escapeHtml(issue.title)}</strong>
        <span>${escapeHtml(issue.state)} · updated ${escapeHtml((issue.updated_at || '').slice(0, 10))}</span>
      </div>`).join('') : '<div class="ws-empty-row">No issues yet.</div>';
    } catch (error) {
      container.innerHTML = `<div class="ws-empty-row ws-error-row">Could not load issues: ${escapeHtml(error.message)}</div>`;
    }
  }

  async function loadPullRequests() {
    const container = document.getElementById('ws-pull-requests');
    container.innerHTML = '<div class="ws-empty-row">Loading pull requests…</div>';
    try {
      const prs = await api(`/api/v1/repositories/${repositoryId}/pull-requests`);
      container.innerHTML = prs.length ? prs.map(pr => `<div class="ws-tool-item">
        <strong>#${pr.id} ${escapeHtml(pr.title)}</strong>
        <span>${escapeHtml(pr.state)} · ${escapeHtml(pr.head_branch)} → ${escapeHtml(pr.base_branch)}</span>
      </div>`).join('') : '<div class="ws-empty-row">No pull requests yet.</div>';
    } catch (error) {
      container.innerHTML = `<div class="ws-empty-row ws-error-row">Could not load pull requests: ${escapeHtml(error.message)}</div>`;
    }
  }

  function setMode(mode) {
    document.querySelectorAll('.ws-editor-modes [data-mode]').forEach(button => {
      button.classList.toggle('active', button.dataset.mode === mode);
    });
    viewPane.hidden = mode !== 'view';
    editPane.hidden = mode !== 'edit';
    historyPane.hidden = mode !== 'history';
    blamePane.hidden = mode !== 'blame';
    if (mode === 'history') loadHistory().catch(error => { historyPane.innerHTML = `<div class="ws-empty-row ws-error-row">${escapeHtml(error.message)}</div>`; });
    if (mode === 'blame') loadBlame().catch(error => { blamePane.innerHTML = `<div class="ws-empty-row ws-error-row">${escapeHtml(error.message)}</div>`; });
  }

  function renderViewer() {
    if (!openFileData) return;
    if (!openFileData.viewable) {
      viewPane.innerHTML = `<div class="ws-empty-row">Preview not available — ${escapeHtml(openFileData.reason)}</div>`;
      return;
    }
    const ext = extOf(selectedPath);
    viewPane.innerHTML = ext === 'md' ? renderMarkdown(openFileData.content) : renderCode(openFileData.content, ext);
  }

  const PREVIEW_LIMIT = 512 * 1024;

  async function openFile(path) {
    let file;
    try {
      file = await api(`/api/v1/repositories/${repositoryId}/files?path=${encodeURIComponent(path)}&branch=${encodeURIComponent(branch())}`);
    } catch (error) {
      if (error.status === 415) {
        file = { path, content: '', size: 0, binary: true };
      } else { throw error; }
    }
    selectedPath = path;
    currentPath = parentPath(path);
    currentFile.textContent = path;
    const tooBig = (file.size || 0) > PREVIEW_LIMIT;
    const viewable = !file.binary && !tooBig;
    openFileData = {
      content: file.content || '',
      viewable,
      reason: file.binary ? 'this is a binary file.' : tooBig ? 'this file is too large to display.' : '',
    };
    editor.value = viewable ? file.content : '';
    editor.disabled = !viewable;
    editorShell.hidden = false;
    editorEmpty.hidden = true;
    document.getElementById('ws-rename').disabled = false;
    document.getElementById('ws-delete').disabled = false;
    document.getElementById('ws-save').disabled = !viewable;
    document.getElementById('ws-mode-edit').disabled = !viewable;
    document.getElementById('ws-commit-message').value = `Update ${path}`;
    renderViewer();
    setMode('view');
    setStatus(`Viewing ${path}`);
    renderTree();
  }

  async function loadHistory() {
    historyPane.innerHTML = '<div class="ws-empty-row">Loading history…</div>';
    const data = await api(`/api/v1/repositories/${repositoryId}/history?path=${encodeURIComponent(selectedPath)}&branch=${encodeURIComponent(branch())}`);
    historyPane.innerHTML = data.commits.length ? data.commits.map(commit => `<article class="ws-commit">
      <strong>${escapeHtml(commit.message)}</strong>
      <span>${escapeHtml(commit.short_sha)} · ${escapeHtml(commit.author)} · ${escapeHtml((commit.created_at || '').slice(0, 10))}</span>
    </article>`).join('') : '<div class="ws-empty-row">No commits have touched this file yet.</div>';
  }

  async function loadBlame() {
    blamePane.innerHTML = '<div class="ws-empty-row">Loading blame…</div>';
    const data = await api(`/api/v1/repositories/${repositoryId}/blame?path=${encodeURIComponent(selectedPath)}&branch=${encodeURIComponent(branch())}`);
    if (!data.available) {
      blamePane.innerHTML = `<div class="ws-empty-row">Blame unavailable — ${escapeHtml(data.reason || 'this file cannot be annotated.')}</div>`;
      return;
    }
    const rows = data.lines.map(line => `<div class="ws-blame-row">
      <span class="ws-blame-meta" title="${escapeHtml(line.author)} · ${escapeHtml(line.date)}">${escapeHtml(line.short_sha)} ${escapeHtml(line.author)}</span>
      <span class="ws-blame-no">${line.line}</span>
      <code class="ws-blame-code">${escapeHtml(line.content) || '&nbsp;'}</code>
    </div>`).join('');
    blamePane.innerHTML = `<div class="ws-blame-note">Standard git line attribution from real stored commits.</div>${rows}`;
  }

  function closeEditor() {
    selectedPath = '';
    openFileData = null;
    editor.value = '';
    editor.disabled = true;
    editorShell.hidden = true;
    editorEmpty.hidden = false;
  }

  async function saveFile() {
    if (!selectedPath) return;
    setStatus('Committing…');
    await api(`/api/v1/repositories/${repositoryId}/files`, {
      method: 'PUT',
      body: JSON.stringify({
        path: selectedPath,
        content: editor.value,
        branch: branch(),
        commit_message: document.getElementById('ws-commit-message').value.trim() || `Update ${selectedPath}`,
      }),
    });
    setStatus('Committed');
    if (openFileData) openFileData.content = editor.value;
    renderViewer();
    await Promise.all([loadTree(), loadCommits()]);
  }

  function beginNewFile(path) {
    selectedPath = path;
    currentPath = parentPath(path);
    currentFile.textContent = selectedPath;
    openFileData = { content: '', viewable: true, reason: '' };
    editor.value = '';
    editor.disabled = false;
    editorShell.hidden = false;
    editorEmpty.hidden = true;
    document.getElementById('ws-rename').disabled = false;
    document.getElementById('ws-delete').disabled = false;
    document.getElementById('ws-save').disabled = false;
    document.getElementById('ws-mode-edit').disabled = false;
    document.getElementById('ws-commit-message').value = `Create ${selectedPath}`;
    renderViewer();
    setMode('edit');
    setStatus('New file ready to commit');
  }

  function createFile() {
    const name = prompt('New file name or path', currentPath ? `${currentPath}/new-file.txt` : 'new-file.txt');
    if (name?.trim()) beginNewFile(name.trim().replace(/^\/+/, ''));
  }

  function createFolder() {
    const name = prompt('New folder name or path', currentPath ? `${currentPath}/new-folder` : 'new-folder');
    if (!name?.trim()) return;
    beginNewFile(`${name.trim().replace(/^\/+|\/+$/g, '')}/.gitkeep`);
    document.getElementById('ws-commit-message').value = `Create folder ${name.trim()}`;
  }

  async function renameFile() {
    if (!selectedPath) return;
    const destination = prompt('Rename or move file to', selectedPath);
    if (!destination || destination === selectedPath) return;
    await api(`/api/v1/repositories/${repositoryId}/move`, {
      method: 'POST',
      body: JSON.stringify({ source_path: selectedPath, destination_path: destination, branch: branch(), commit_message: `Move ${selectedPath} to ${destination}` }),
    });
    selectedPath = destination;
    currentPath = parentPath(destination);
    currentFile.textContent = destination;
    await Promise.all([loadTree(), loadCommits()]);
    setStatus('File moved');
  }

  async function deleteFile() {
    if (!selectedPath || !confirm(`Delete ${selectedPath}?`)) return;
    await api(`/api/v1/repositories/${repositoryId}/files`, {
      method: 'DELETE',
      body: JSON.stringify({ path: selectedPath, branch: branch(), commit_message: `Delete ${selectedPath}` }),
    });
    closeEditor();
    await Promise.all([loadTree(), loadCommits()]);
  }

  async function newBranch() {
    const name = prompt('New branch name', 'feature/new-work');
    if (!name) return;
    await api(`/api/v1/repositories/${repositoryId}/branches`, { method: 'POST', body: JSON.stringify({ name, source_branch: branch() }) });
    await loadBranches();
    branchSelect.value = name;
    currentPath = '';
    closeEditor();
    await Promise.all([loadTree(), loadCommits()]);
  }

  async function runTool(mode, label) {
    output.textContent = `${label} started for ${repository.name} on ${branch()}…`;
    try {
      const result = await api('/api/v1/agent/run', {
        method: 'POST',
        body: JSON.stringify({
          mode,
          objective: `${label} repository ${repository.name} on branch ${branch()} using .Amosclaud-workflow/workflow.yml`,
          branch: branch(),
          metadata: { repository_id: Number(repositoryId), repository_name: repository.name, use_agent: false, source: 'repository-optional-autonomous' },
        }),
      });
      output.textContent = result.reply || `${label} completed.`;
    } catch (error) {
      output.textContent = `${label} failed safely: ${error.message}`;
    }
  }

  function activateTab(name) {
    if (name === 'commits') { loadCommits().catch(error => setStatus(error.message)); return; }
    if (name === 'issues' && !tabLoaded.issues) { tabLoaded.issues = true; loadIssues(); }
    if (name === 'pull-requests' && !tabLoaded.prs) { tabLoaded.prs = true; loadPullRequests(); }
  }

  document.querySelectorAll('.ws-tab').forEach(tab => tab.addEventListener('click', () => {
    document.querySelectorAll('.ws-tab').forEach(item => item.classList.toggle('active', item === tab));
    document.querySelectorAll('.ws-panel').forEach(panel => panel.classList.toggle('active', panel.dataset.panel === tab.dataset.tab));
    activateTab(tab.dataset.tab);
  }));

  document.querySelectorAll('.ws-editor-modes [data-mode]').forEach(button => button.addEventListener('click', () => setMode(button.dataset.mode)));

  breadcrumbs.addEventListener('click', event => {
    const button = event.target.closest('[data-breadcrumb]');
    if (!button) return;
    currentPath = button.dataset.breadcrumb;
    searchInput.value = '';
    renderTree();
  });
  tree.addEventListener('click', event => {
    const folder = event.target.closest('[data-directory]');
    if (folder) { currentPath = folder.dataset.directory; searchInput.value = ''; renderTree(); return; }
    const file = event.target.closest('[data-file]');
    if (file) openFile(file.dataset.file).catch(error => setStatus(error.message));
  });
  searchInput.addEventListener('input', renderTree);
  branchSelect.addEventListener('change', () => { currentPath = ''; closeEditor(); Promise.all([loadTree(), loadCommits()]); });
  document.getElementById('ws-save').addEventListener('click', () => saveFile().catch(error => setStatus(error.message)));
  document.getElementById('ws-new-file').addEventListener('click', createFile);
  document.getElementById('ws-new-folder').addEventListener('click', createFolder);
  document.getElementById('ws-rename').addEventListener('click', () => renameFile().catch(error => setStatus(error.message)));
  document.getElementById('ws-delete').addEventListener('click', () => deleteFile().catch(error => setStatus(error.message)));
  document.getElementById('ws-new-branch').addEventListener('click', () => newBranch().catch(error => setStatus(error.message)));
  document.getElementById('ws-refresh-issues')?.addEventListener('click', () => { tabLoaded.issues = true; loadIssues(); });
  document.getElementById('ws-refresh-prs')?.addEventListener('click', () => { tabLoaded.prs = true; loadPullRequests(); });
  document.getElementById('ws-build').addEventListener('click', () => runTool('build', 'Build'));
  document.getElementById('ws-test').addEventListener('click', () => runTool('autonomous-check', 'Tests'));
  document.getElementById('ws-review').addEventListener('click', () => runTool('autonomous-check', 'Review'));
  document.getElementById('ws-deploy').addEventListener('click', () => runTool('deploy', 'Deployment'));

  (async () => {
    try {
      await loadRepository();
    } catch (error) {
      if (error.status === 404 || error.status === 403) { showNotFound(); return; }
      setStatus(error.message);
      return;
    }
    try {
      await loadBranches();
      await Promise.all([loadTree(), loadCommits()]);
      closeEditor();
      setStatus(`${repository.owner_name}/${repository.name} on ${branch()}`);
    } catch (error) {
      setStatus(error.message);
    }
  })();
})();
