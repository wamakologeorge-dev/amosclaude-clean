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

  let selectedPath = '';
  let currentPath = '';
  let repository = null;
  let entries = [];

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
      throw new Error('Your session expired. Sign in again.');
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
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return data;
  }

  const branch = () => branchSelect.value || repository?.default_branch || 'main';
  const setStatus = message => { status.textContent = message; };
  const escapeHtml = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const baseName = path => path.split('/').filter(Boolean).pop() || path;
  const parentPath = path => path.split('/').filter(Boolean).slice(0, -1).join('/');
  const joinPath = (left, right) => [left, right].filter(Boolean).join('/');

  function humanSize(size) {
    if (!size) return '—';
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }

  async function loadRepository() {
    repository = await api(`/api/v1/repositories/${repositoryId}`);
    document.getElementById('ws-repo-name').textContent = `${repository.owner_name}/${repository.name}`;
    document.getElementById('ws-repo-meta').textContent = `${repository.visibility} · ${repository.role}`;
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

  function renderTree() {
    renderBreadcrumbs();
    const query = searchInput.value.trim().toLowerCase();
    const rows = query
      ? entries.filter(entry => entry.type === 'file' && entry.path.toLowerCase().includes(query))
      : directChildren(currentPath);
    const parentRow = !query && currentPath
      ? `<button class="ws-tree-row ws-parent-row" type="button" data-directory="${escapeHtml(parentPath(currentPath))}"><span class="ws-file-icon">↩</span><span class="ws-file-name">..</span><span>—</span></button>`
      : '';
    const body = rows.map(entry => {
      const directory = entry.type === 'directory';
      return `<button class="ws-tree-row${entry.path === selectedPath ? ' active' : ''}" type="button" ${directory ? `data-directory="${escapeHtml(entry.path)}"` : `data-file="${escapeHtml(entry.path)}"`}>
        <span class="ws-file-icon">${directory ? '📁' : '📄'}</span>
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
    const commits = await api(`/api/v1/repositories/${repositoryId}/commits?branch=${encodeURIComponent(branch())}&limit=50`);
    document.getElementById('ws-commits').innerHTML = commits.map(commit => `<article class="ws-commit">
      <strong>${escapeHtml(commit.message)}</strong>
      <span>${escapeHtml(commit.sha.slice(0, 7))} committed by ${escapeHtml(commit.author)}</span>
    </article>`).join('') || '<div class="ws-empty-row">No commits yet.</div>';
  }

  async function openFile(path) {
    const file = await api(`/api/v1/repositories/${repositoryId}/files?path=${encodeURIComponent(path)}&branch=${encodeURIComponent(branch())}`);
    selectedPath = path;
    currentPath = parentPath(path);
    currentFile.textContent = path;
    editor.value = file.content;
    editor.disabled = false;
    editorShell.hidden = false;
    editorEmpty.hidden = true;
    ['ws-save', 'ws-rename', 'ws-delete'].forEach(id => { document.getElementById(id).disabled = false; });
    document.getElementById('ws-commit-message').value = `Update ${path}`;
    setStatus(`Editing ${path}`);
    renderTree();
  }

  function closeEditor() {
    selectedPath = '';
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
    await Promise.all([loadTree(), loadCommits()]);
  }

  function beginNewFile(path) {
    selectedPath = path;
    currentPath = parentPath(path);
    currentFile.textContent = selectedPath;
    editor.value = '';
    editor.disabled = false;
    editorShell.hidden = false;
    editorEmpty.hidden = true;
    ['ws-save', 'ws-rename', 'ws-delete'].forEach(id => { document.getElementById(id).disabled = false; });
    document.getElementById('ws-commit-message').value = `Create ${selectedPath}`;
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

  document.querySelectorAll('.ws-tab').forEach(tab => tab.addEventListener('click', () => {
    document.querySelectorAll('.ws-tab').forEach(item => item.classList.toggle('active', item === tab));
    document.querySelectorAll('.ws-panel').forEach(panel => panel.classList.toggle('active', panel.dataset.panel === tab.dataset.tab));
    if (tab.dataset.tab === 'commits') loadCommits().catch(error => setStatus(error.message));
  }));

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
  document.getElementById('ws-build').addEventListener('click', () => runTool('build', 'Build'));
  document.getElementById('ws-test').addEventListener('click', () => runTool('autonomous-check', 'Tests'));
  document.getElementById('ws-review').addEventListener('click', () => runTool('autonomous-check', 'Review'));
  document.getElementById('ws-deploy').addEventListener('click', () => runTool('deploy', 'Deployment'));

  (async () => {
    try {
      await loadRepository();
      await loadBranches();
      await Promise.all([loadTree(), loadCommits()]);
      closeEditor();
    } catch (error) {
      setStatus(error.message);
    }
  })();
})();