(() => {
  const query = new URLSearchParams(location.search);
  const repositoryId = query.get('repository');
  if (!/^\d+$/.test(repositoryId || '') || Number(repositoryId) < 1) {
    location.replace('/repositories');
    return;
  }

  const elements = {
    back: document.getElementById('eow-back'),
    repositoryName: document.getElementById('eow-repository-name'),
    branch: document.getElementById('eow-branch'),
    newBranch: document.getElementById('eow-new-branch'),
    search: document.getElementById('eow-search'),
    newFile: document.getElementById('eow-new-file'),
    newFolder: document.getElementById('eow-new-folder'),
    pull: document.getElementById('eow-pull'),
    push: document.getElementById('eow-push'),
    autoSyncBox: document.getElementById('eow-auto-sync-box'),
    autoSync: document.getElementById('eow-auto-sync'),
    readonly: document.getElementById('eow-readonly'),
    status: document.getElementById('eow-status'),
    treeSummary: document.getElementById('eow-tree-summary'),
    breadcrumbs: document.getElementById('eow-breadcrumbs'),
    tree: document.getElementById('eow-tree'),
    empty: document.getElementById('eow-empty'),
    shell: document.getElementById('eow-shell'),
    selectedKind: document.getElementById('eow-selected-kind'),
    selectedPath: document.getElementById('eow-selected-path'),
    viewMode: document.getElementById('eow-view-mode'),
    editMode: document.getElementById('eow-edit-mode'),
    focus: document.getElementById('eow-focus'),
    rename: document.getElementById('eow-rename'),
    delete: document.getElementById('eow-delete'),
    folderView: document.getElementById('eow-folder-view'),
    folderTitle: document.getElementById('eow-folder-title'),
    folderDescription: document.getElementById('eow-folder-description'),
    folderNewFile: document.getElementById('eow-folder-new-file'),
    folderNewFolder: document.getElementById('eow-folder-new-folder'),
    view: document.getElementById('eow-view'),
    edit: document.getElementById('eow-edit'),
    editor: document.getElementById('eow-editor'),
    commitMessage: document.getElementById('eow-commit-message'),
    save: document.getElementById('eow-save'),
    detailPath: document.getElementById('eow-detail-path'),
    detailType: document.getElementById('eow-detail-type'),
    detailSize: document.getElementById('eow-detail-size'),
    detailBranch: document.getElementById('eow-detail-branch'),
    mirrorCard: document.getElementById('eow-mirror-card'),
    mirrorName: document.getElementById('eow-mirror-name'),
    mirrorLink: document.getElementById('eow-mirror-link'),
    mirrorState: document.getElementById('eow-mirror-state'),
    dialog: document.getElementById('eow-dialog'),
    dialogTitle: document.getElementById('eow-dialog-title'),
    dialogDescription: document.getElementById('eow-dialog-description'),
    dialogLabel: document.getElementById('eow-dialog-label'),
    dialogInput: document.getElementById('eow-dialog-input'),
    dialogConfirm: document.getElementById('eow-dialog-confirm'),
  };

  const state = {
    repository: null,
    mirror: null,
    entries: [],
    currentDirectory: '',
    selected: null,
    originalContent: '',
    dirty: false,
    mode: 'view',
  };

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
    const raw = await response.text();
    const type = response.headers.get('content-type') || '';
    let data = null;
    if (raw) {
      if (type.includes('application/json')) {
        try { data = JSON.parse(raw); } catch { data = { detail: 'The server returned invalid JSON.' }; }
      } else {
        data = { detail: raw.trim() || `Request failed (${response.status})` };
      }
    }
    if (!response.ok) {
      const detail = data?.detail || data?.message || `Request failed (${response.status})`;
      throw Object.assign(new Error(typeof detail === 'string' ? detail : JSON.stringify(detail)), {
        status: response.status,
        data,
      });
    }
    return data;
  }

  const branch = () => elements.branch.value || state.repository?.default_branch || 'main';
  const canWrite = () => ['owner', 'developer'].includes(state.repository?.role);
  const canSync = () => state.repository?.role === 'owner' && Boolean(state.mirror?.can_push);
  const escapeHtml = value => String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  const normalizePath = value => String(value || '').trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
  const joinPath = (left, right) => [normalizePath(left), normalizePath(right)].filter(Boolean).join('/');
  const parentPath = path => normalizePath(path).split('/').filter(Boolean).slice(0, -1).join('/');
  const baseName = path => normalizePath(path).split('/').filter(Boolean).pop() || '';
  const isFolderMarker = path => baseName(path) === '.gitkeep';
  const setStatus = message => { elements.status.textContent = message; };

  function humanSize(size) {
    if (!Number.isFinite(Number(size)) || Number(size) <= 0) return '—';
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }

  function validPath(value) {
    const path = normalizePath(value);
    if (!path || path.startsWith('.git/') || path === '.git') return false;
    const parts = path.split('/');
    return !parts.includes('..') && !parts.includes('.');
  }

  function ask({ title, description = '', label = 'Value', value = '', confirm = 'Continue' }) {
    if (!elements.dialog?.showModal) {
      const result = prompt(title, value);
      return Promise.resolve(result === null ? null : result);
    }
    elements.dialogTitle.textContent = title;
    elements.dialogDescription.textContent = description;
    elements.dialogDescription.hidden = !description;
    elements.dialogLabel.textContent = label;
    elements.dialogInput.value = value;
    elements.dialogConfirm.textContent = confirm;
    elements.dialog.showModal();
    queueMicrotask(() => {
      elements.dialogInput.focus();
      elements.dialogInput.select();
    });
    return new Promise(resolve => {
      const onClose = () => {
        elements.dialog.removeEventListener('close', onClose);
        resolve(elements.dialog.returnValue === 'confirm' ? elements.dialogInput.value : null);
      };
      elements.dialog.addEventListener('close', onClose);
    });
  }

  function guardUnsaved() {
    if (!state.dirty) return true;
    return confirm('The open file has uncommitted changes. Continue and discard them?');
  }

  function setDirty(value) {
    state.dirty = Boolean(value);
    document.title = `${state.dirty ? '● ' : ''}The Editor of the Web · Amosclaud`;
    if (state.selected?.type === 'file' && canWrite()) {
      elements.save.disabled = !state.dirty && !state.selected.isNew;
    }
  }

  function updatePermissions() {
    const writable = canWrite();
    elements.readonly.hidden = writable;
    [elements.newFile, elements.newFolder, elements.newBranch].forEach(control => {
      control.disabled = !writable;
    });
    if (state.selected) {
      const mutableSelection = Boolean(state.selected.path);
      elements.rename.disabled = !writable || !mutableSelection;
      elements.delete.disabled = !writable || !mutableSelection;
      elements.save.disabled = !writable || state.selected.type !== 'file'
        || (!state.dirty && !state.selected.isNew);
      elements.editMode.disabled = !writable || state.selected.type !== 'file' || state.selected.binary;
    }
    const syncable = canSync();
    elements.pull.hidden = !state.mirror;
    elements.push.hidden = !state.mirror;
    elements.autoSyncBox.hidden = !state.mirror;
    elements.pull.disabled = !syncable;
    elements.push.disabled = !syncable;
    elements.autoSync.disabled = !syncable;
  }

  function visibleEntries() {
    return state.entries.filter(entry => !isFolderMarker(entry.path));
  }

  function directChildren(path) {
    const prefix = path ? `${path}/` : '';
    const children = new Map();
    state.entries.forEach(entry => {
      if (!entry.path.startsWith(prefix) || entry.path === path) return;
      const remainder = entry.path.slice(prefix.length);
      const [first, ...rest] = remainder.split('/');
      if (!first) return;
      const childPath = joinPath(path, first);
      const directory = rest.length > 0 || entry.type === 'directory';
      const existing = children.get(childPath);
      if (!existing || directory) {
        children.set(childPath, {
          path: childPath,
          type: directory ? 'directory' : 'file',
          size: directory ? 0 : entry.size || 0,
        });
      }
    });
    return [...children.values()].sort((a, b) => (
      a.type === b.type ? a.path.localeCompare(b.path) : a.type === 'directory' ? -1 : 1
    ));
  }

  function renderBreadcrumbs() {
    const parts = state.currentDirectory.split('/').filter(Boolean);
    const crumbs = [{ label: state.repository?.name || 'Repository', path: '' }];
    parts.forEach((part, index) => {
      crumbs.push({ label: part, path: parts.slice(0, index + 1).join('/') });
    });
    elements.breadcrumbs.innerHTML = crumbs.map((crumb, index) => (
      `${index ? '<span>/</span>' : ''}<button type="button" data-path="${escapeHtml(crumb.path)}">${escapeHtml(crumb.label)}</button>`
    )).join('');
  }

  function renderTree() {
    renderBreadcrumbs();
    const queryText = elements.search.value.trim().toLowerCase();
    const rows = queryText
      ? visibleEntries().filter(entry => entry.path.toLowerCase().includes(queryText))
      : directChildren(state.currentDirectory);
    elements.treeSummary.textContent = `${visibleEntries().length} paths on ${branch()}`;
    const parent = !queryText && state.currentDirectory
      ? `<div class="eow-tree-row"><button class="eow-tree-open" type="button" data-open-path="${escapeHtml(parentPath(state.currentDirectory))}" data-open-type="directory"><span>↩</span><span class="eow-tree-name">..</span><span class="eow-tree-size">—</span></button><button class="eow-tree-select" type="button" aria-label="Select parent folder" data-select-path="${escapeHtml(parentPath(state.currentDirectory))}" data-select-type="directory">⋯</button></div>`
      : '';
    const body = rows.map(entry => {
      const selected = state.selected?.path === entry.path;
      const icon = entry.type === 'directory' ? '📁' : '📄';
      return `<div class="eow-tree-row${selected ? ' active' : ''}">
        <button class="eow-tree-open" type="button" data-open-path="${escapeHtml(entry.path)}" data-open-type="${entry.type}">
          <span>${icon}</span><span class="eow-tree-name">${escapeHtml(queryText ? entry.path : baseName(entry.path))}</span>
          <span class="eow-tree-size">${entry.type === 'directory' ? '—' : humanSize(entry.size)}</span>
        </button>
        <button class="eow-tree-select" type="button" aria-label="Select ${escapeHtml(entry.path)}" data-select-path="${escapeHtml(entry.path)}" data-select-type="${entry.type}">⋯</button>
      </div>`;
    }).join('');
    elements.tree.innerHTML = parent + (body || '<div class="eow-empty-row">This folder is empty.</div>');
  }

  function updateInspector() {
    const selected = state.selected;
    elements.detailPath.textContent = selected?.path || 'None';
    elements.detailType.textContent = selected?.type || '—';
    elements.detailSize.textContent = selected?.type === 'file' ? humanSize(selected.size || 0) : '—';
    elements.detailBranch.textContent = branch();
  }

  function highlightedLines(content, path) {
    const highlighter = window.AmosclaudHighlight;
    if (!highlighter) return content.split('\n').map(escapeHtml);
    return highlighter.highlightLines(content, highlighter.languageForPath(path));
  }

  function renderFileView() {
    if (!state.selected || state.selected.type !== 'file') return;
    if (state.selected.binary) {
      elements.view.innerHTML = '<div class="eow-empty-row">This binary file can be mirrored, moved, or deleted, but it cannot be edited as text.</div>';
      return;
    }
    const lines = highlightedLines(elements.editor.value, state.selected.path);
    const gutter = lines.map((_, index) => `<span>${index + 1}</span>`).join('');
    const body = lines.map(line => `<span class="eow-code-line">${line || '&nbsp;'}</span>`).join('');
    const language = window.AmosclaudHighlight
      ? window.AmosclaudHighlight.languageForPath(state.selected.path)
      : 'plain';
    elements.view.innerHTML = `<div class="eow-code-meta">${escapeHtml(language)} · ${lines.length} lines</div>
      <div class="eow-code"><div class="eow-gutter">${gutter}</div><pre class="eow-code-body"><code>${body}</code></pre></div>`;
  }

  function setMode(mode) {
    if (mode === 'edit' && (state.selected?.type !== 'file' || state.selected.binary || !canWrite())) return;
    state.mode = mode;
    elements.viewMode.classList.toggle('active', mode === 'view');
    elements.editMode.classList.toggle('active', mode === 'edit');
    elements.view.hidden = mode !== 'view' || state.selected?.type !== 'file';
    elements.edit.hidden = mode !== 'edit' || state.selected?.type !== 'file';
    elements.folderView.hidden = state.selected?.type !== 'directory';
    if (mode === 'view') renderFileView();
  }

  function showSelection() {
    const selected = state.selected;
    if (!selected) {
      elements.empty.hidden = false;
      elements.shell.hidden = true;
      updateInspector();
      renderTree();
      return;
    }
    elements.empty.hidden = true;
    elements.shell.hidden = false;
    elements.selectedKind.textContent = selected.type.toUpperCase();
    elements.selectedPath.textContent = selected.path || '/';
    const mutableSelection = Boolean(selected.path);
    elements.rename.disabled = !canWrite() || !mutableSelection;
    elements.delete.disabled = !canWrite() || !mutableSelection;
    elements.editMode.disabled = !canWrite() || selected.type !== 'file' || selected.binary;
    elements.viewMode.disabled = selected.type !== 'file';
    if (selected.type === 'directory') {
      const count = directChildren(selected.path).length;
      elements.folderTitle.textContent = selected.path ? baseName(selected.path) : state.repository.name;
      elements.folderDescription.textContent = `${count} direct item${count === 1 ? '' : 's'} in this folder on ${branch()}.`;
      elements.commitMessage.value = '';
      setMode('view');
    } else {
      elements.commitMessage.value = selected.isNew ? `Create ${selected.path}` : `Update ${selected.path}`;
      setMode(selected.binary ? 'view' : state.mode);
    }
    updatePermissions();
    updateInspector();
    renderTree();
  }

  async function loadRepository() {
    state.repository = await api(`/api/v1/repositories/${repositoryId}`);
    elements.repositoryName.textContent = `${state.repository.owner_name}/${state.repository.name} · ${state.repository.visibility} · ${state.repository.role}`;
    elements.back.href = `/workspace/${repositoryId}`;
    updatePermissions();
  }

  async function loadBranches(preferred = '') {
    const branches = await api(`/api/v1/repositories/${repositoryId}/branches`);
    elements.branch.innerHTML = branches.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('');
    const desired = preferred || state.repository?.default_branch || branches[0] || 'main';
    if (branches.includes(desired)) elements.branch.value = desired;
    elements.branch.disabled = false;
  }

  async function loadMirror() {
    try {
      const repositories = await api('/api/v1/github/repositories');
      state.mirror = repositories.find(item => Number(item.imported_repository_id) === Number(repositoryId)) || null;
    } catch (error) {
      if (![401, 409, 503].includes(error.status)) throw error;
      state.mirror = null;
    }
    if (state.mirror) {
      elements.mirrorCard.hidden = false;
      elements.mirrorName.textContent = state.mirror.full_name;
      elements.mirrorLink.href = state.mirror.html_url;
      elements.mirrorState.textContent = state.mirror.can_push
        ? 'The selected branch can be pulled from and pushed to GitHub.'
        : 'This connected GitHub repository is read-only.';
    } else {
      elements.mirrorCard.hidden = true;
    }
    updatePermissions();
  }

  async function loadTree() {
    elements.tree.textContent = 'Loading files and folders…';
    state.entries = await api(`/api/v1/repositories/${repositoryId}/tree?branch=${encodeURIComponent(branch())}`);
    renderTree();
    updateInspector();
  }

  async function openFile(path) {
    if (!guardUnsaved()) return;
    let file;
    let binary = false;
    try {
      file = await api(`/api/v1/repositories/${repositoryId}/files?path=${encodeURIComponent(path)}&branch=${encodeURIComponent(branch())}`);
    } catch (error) {
      if (error.status !== 415) throw error;
      file = { path, content: '', size: 0 };
      binary = true;
    }
    state.selected = {
      path,
      type: 'file',
      size: file.size || 0,
      binary,
      isNew: false,
    };
    state.currentDirectory = parentPath(path);
    elements.editor.value = file.content || '';
    state.originalContent = elements.editor.value;
    setDirty(false);
    state.mode = 'view';
    showSelection();
    setStatus(`Opened ${path}`);
  }

  function selectDirectory(path, navigate = false) {
    if (!guardUnsaved()) return;
    const normalized = normalizePath(path);
    state.selected = { path: normalized, type: 'directory', size: 0, binary: false, isNew: false };
    if (navigate) {
      state.currentDirectory = normalized;
      elements.search.value = '';
    }
    elements.editor.value = '';
    state.originalContent = '';
    setDirty(false);
    state.mode = 'view';
    showSelection();
    setStatus(`Selected folder ${normalized || '/'}`);
  }

  function beginNewFile(path) {
    if (!guardUnsaved()) return;
    const normalized = normalizePath(path);
    state.selected = { path: normalized, type: 'file', size: 0, binary: false, isNew: true };
    state.currentDirectory = parentPath(normalized);
    elements.editor.value = '';
    state.originalContent = '';
    state.mode = 'edit';
    setDirty(true);
    showSelection();
    setStatus(`New file ${normalized} is ready to commit`);
    elements.editor.focus();
  }

  async function createFile(base = state.currentDirectory) {
    if (!canWrite()) return;
    const initial = joinPath(base, 'new-file.txt');
    const value = await ask({
      title: 'Create a file',
      description: 'Enter a path inside this repository mirror.',
      label: 'File path',
      value: initial,
      confirm: 'Create',
    });
    if (value === null) return;
    const path = normalizePath(value);
    if (!validPath(path) || path.endsWith('/')) {
      setStatus('Enter a valid file path.');
      return;
    }
    if (state.entries.some(entry => entry.path === path)) {
      setStatus('A file or folder already exists at that path.');
      return;
    }
    beginNewFile(path);
  }

  async function createFolder(base = state.currentDirectory) {
    if (!canWrite()) return;
    const initial = joinPath(base, 'new-folder');
    const value = await ask({
      title: 'Create a folder',
      description: 'Git stores files rather than empty directories, so Amosclaud commits a hidden .gitkeep marker.',
      label: 'Folder path',
      value: initial,
      confirm: 'Create folder',
    });
    if (value === null) return;
    const path = normalizePath(value);
    if (!validPath(path)) {
      setStatus('Enter a valid folder path.');
      return;
    }
    if (state.entries.some(entry => entry.path === path || entry.path.startsWith(`${path}/`))) {
      setStatus('A file or folder already exists at that path.');
      return;
    }
    setStatus(`Creating ${path}…`);
    await api(`/api/v1/repositories/${repositoryId}/files`, {
      method: 'PUT',
      body: JSON.stringify({
        path: `${path}/.gitkeep`,
        content: '',
        branch: branch(),
        commit_message: `Create folder ${path}`,
      }),
    });
    await syncAfterCommit(`Created folder ${path}`);
    await loadTree();
    selectDirectory(path, true);
  }

  async function saveFile() {
    const selected = state.selected;
    if (!selected || selected.type !== 'file' || selected.binary || !canWrite()) return;
    if (!validPath(selected.path)) {
      setStatus('The selected file path is invalid.');
      return;
    }
    setStatus(`Committing ${selected.path}…`);
    const result = await api(`/api/v1/repositories/${repositoryId}/files`, {
      method: 'PUT',
      body: JSON.stringify({
        path: selected.path,
        content: elements.editor.value,
        branch: branch(),
        commit_message: elements.commitMessage.value.trim()
          || `${selected.isNew ? 'Create' : 'Update'} ${selected.path}`,
      }),
    });
    selected.isNew = false;
    selected.size = new Blob([elements.editor.value]).size;
    state.originalContent = elements.editor.value;
    setDirty(false);
    await syncAfterCommit(`Committed ${result.commit.slice(0, 7)}`);
    await loadTree();
    setMode('view');
  }

  async function renameSelection() {
    const selected = state.selected;
    if (!selected || !canWrite()) return;
    const value = await ask({
      title: `Rename or move ${selected.type}`,
      description: 'Enter the complete destination path in the selected branch.',
      label: 'Destination path',
      value: selected.path,
      confirm: 'Move',
    });
    if (value === null) return;
    const destination = normalizePath(value);
    if (!validPath(destination) || destination === selected.path) return;
    if (state.entries.some(entry => entry.path === destination)) {
      setStatus('A file or folder already exists at the destination.');
      return;
    }
    setStatus(`Moving ${selected.path}…`);
    await api(`/api/v1/repositories/${repositoryId}/move`, {
      method: 'POST',
      body: JSON.stringify({
        source_path: selected.path,
        destination_path: destination,
        branch: branch(),
        commit_message: `Move ${selected.path} to ${destination}`,
      }),
    });
    const previous = selected.path;
    selected.path = destination;
    state.currentDirectory = selected.type === 'directory' ? destination : parentPath(destination);
    await syncAfterCommit(`Moved ${previous} to ${destination}`);
    await loadTree();
    showSelection();
  }

  async function deleteSelection() {
    const selected = state.selected;
    if (!selected || !canWrite()) return;
    const label = selected.path || state.repository.name;
    if (!confirm(`Delete ${selected.type} "${label}" from ${branch()}? This creates a real commit.`)) return;
    setStatus(`Deleting ${label}…`);
    await api(`/api/v1/repositories/${repositoryId}/files`, {
      method: 'DELETE',
      body: JSON.stringify({
        path: selected.path,
        branch: branch(),
        commit_message: `Delete ${selected.path}`,
      }),
    });
    const removed = selected.path;
    state.currentDirectory = parentPath(removed);
    state.selected = null;
    state.originalContent = '';
    elements.editor.value = '';
    setDirty(false);
    showSelection();
    await syncAfterCommit(`Deleted ${removed}`);
    await loadTree();
  }

  async function newBranch() {
    if (!canWrite()) return;
    const value = await ask({
      title: 'Create a branch',
      description: `The new branch will start from ${branch()}.`,
      label: 'Branch name',
      value: 'feature/editor-change',
      confirm: 'Create branch',
    });
    if (value === null) return;
    const name = value.trim();
    if (!name) return;
    await api(`/api/v1/repositories/${repositoryId}/branches`, {
      method: 'POST',
      body: JSON.stringify({ name, source_branch: branch() }),
    });
    await loadBranches(name);
    state.currentDirectory = '';
    state.selected = null;
    setDirty(false);
    await loadTree();
    showSelection();
    setStatus(`Created branch ${name}`);
  }

  async function pullMirror() {
    if (!canSync() || !guardUnsaved()) return;
    elements.pull.disabled = true;
    setStatus(`Pulling ${state.mirror.full_name}:${branch()}…`);
    try {
      const result = await api(`/api/v1/github/repositories/${repositoryId}/pull`, {
        method: 'POST',
        body: JSON.stringify({ branch: branch(), commit_message: 'Pull GitHub mirror' }),
      });
      elements.mirrorState.textContent = `Pulled ${result.commit.slice(0, 7)}`;
      state.currentDirectory = '';
      state.selected = null;
      await Promise.all([loadBranches(branch()), loadTree()]);
      showSelection();
      setStatus(`Mirror pulled at ${result.commit.slice(0, 7)}`);
    } finally {
      updatePermissions();
    }
  }

  async function pushMirror({ quiet = false } = {}) {
    if (!canSync()) return false;
    elements.push.disabled = true;
    if (!quiet) setStatus(`Pushing ${state.mirror.full_name}:${branch()}…`);
    try {
      const result = await api(`/api/v1/github/repositories/${repositoryId}/push`, {
        method: 'POST',
        body: JSON.stringify({ branch: branch(), commit_message: 'Sync changes from The Editor of the Web' }),
      });
      elements.mirrorState.textContent = `Pushed ${result.commit.slice(0, 7)}`;
      if (!quiet) setStatus(`Mirror pushed at ${result.commit.slice(0, 7)}`);
      return true;
    } finally {
      updatePermissions();
    }
  }

  async function syncAfterCommit(localMessage) {
    if (state.mirror && elements.autoSync.checked && canSync()) {
      try {
        await pushMirror({ quiet: true });
        setStatus(`${localMessage} and synchronized to GitHub.`);
      } catch (error) {
        setStatus(`${localMessage} locally, but GitHub sync failed: ${error.message}`);
      }
    } else {
      setStatus(localMessage);
    }
  }

  elements.breadcrumbs.addEventListener('click', event => {
    const button = event.target.closest('[data-path]');
    if (!button || !guardUnsaved()) return;
    state.currentDirectory = button.dataset.path;
    state.selected = null;
    elements.search.value = '';
    showSelection();
  });

  elements.tree.addEventListener('click', event => {
    const select = event.target.closest('[data-select-path]');
    if (select) {
      if (select.dataset.selectType === 'directory') selectDirectory(select.dataset.selectPath, false);
      else openFile(select.dataset.selectPath).catch(error => setStatus(error.message));
      return;
    }
    const open = event.target.closest('[data-open-path]');
    if (!open) return;
    if (open.dataset.openType === 'directory') selectDirectory(open.dataset.openPath, true);
    else openFile(open.dataset.openPath).catch(error => setStatus(error.message));
  });

  elements.search.addEventListener('input', renderTree);
  elements.editor.addEventListener('input', () => {
    setDirty(elements.editor.value !== state.originalContent || Boolean(state.selected?.isNew));
  });
  elements.branch.addEventListener('change', async event => {
    if (!guardUnsaved()) {
      event.target.value = elements.detailBranch.textContent;
      return;
    }
    state.currentDirectory = '';
    state.selected = null;
    setDirty(false);
    await loadTree();
    showSelection();
    setStatus(`Opened branch ${branch()}`);
  });

  elements.newFile.addEventListener('click', () => createFile().catch(error => setStatus(error.message)));
  elements.newFolder.addEventListener('click', () => createFolder().catch(error => setStatus(error.message)));
  elements.folderNewFile.addEventListener('click', () => createFile(state.selected?.path || '').catch(error => setStatus(error.message)));
  elements.folderNewFolder.addEventListener('click', () => createFolder(state.selected?.path || '').catch(error => setStatus(error.message)));
  elements.newBranch.addEventListener('click', () => newBranch().catch(error => setStatus(error.message)));
  elements.viewMode.addEventListener('click', () => setMode('view'));
  elements.editMode.addEventListener('click', () => setMode('edit'));
  elements.focus.addEventListener('click', () => {
    document.body.classList.toggle('eow-focus-mode');
    elements.focus.textContent = document.body.classList.contains('eow-focus-mode') ? 'Exit focus' : 'Focus';
  });
  elements.rename.addEventListener('click', () => renameSelection().catch(error => setStatus(error.message)));
  elements.delete.addEventListener('click', () => deleteSelection().catch(error => setStatus(error.message)));
  elements.save.addEventListener('click', () => saveFile().catch(error => setStatus(error.message)));
  elements.pull.addEventListener('click', () => pullMirror().catch(error => setStatus(error.message)));
  elements.push.addEventListener('click', () => pushMirror().catch(error => setStatus(error.message)));

  window.addEventListener('beforeunload', event => {
    if (!state.dirty) return;
    event.preventDefault();
    event.returnValue = '';
  });
  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      if (!elements.save.disabled) saveFile().catch(error => setStatus(error.message));
    }
    if (event.key === 'Escape' && document.body.classList.contains('eow-focus-mode')) {
      document.body.classList.remove('eow-focus-mode');
      elements.focus.textContent = 'Focus';
    }
  });

  (async () => {
    try {
      await loadRepository();
      await loadBranches();
      await Promise.all([loadMirror(), loadTree()]);
      elements.search.disabled = false;
      showSelection();
      setStatus(`${state.repository.owner_name}/${state.repository.name} is ready in The Editor of the Web.`);
    } catch (error) {
      setStatus(`Could not open the editor: ${error.message}`);
      if (error.status === 404 || error.status === 403) {
        elements.tree.innerHTML = '<div class="eow-empty-row">Repository not found or access denied.</div>';
      }
    }
  })();
})();
