(() => {
  const repositoryId = location.pathname.split('/').filter(Boolean).pop();
  const branchSelect = document.getElementById('ws-branch');
  const tree = document.getElementById('ws-tree');
  const editor = document.getElementById('ws-editor');
  const currentFile = document.getElementById('ws-current-file');
  const status = document.getElementById('ws-status');
  const output = document.getElementById('ws-output');
  let selectedPath = '';
  let repository = null;

  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: 'same-origin', ...options, headers: { ...(options.body ? {'Content-Type':'application/json'} : {}), ...(options.headers || {}) } });
    if (response.status === 401) location.assign('/login');
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok) throw new Error(data?.detail || `Request failed (${response.status})`);
    return data;
  }

  const branch = () => branchSelect.value || repository?.default_branch || 'main';
  const setStatus = message => { status.textContent = message; };

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

  async function loadTree() {
    tree.textContent = 'Loading files…';
    const entries = await api(`/api/v1/repositories/${repositoryId}/tree?branch=${encodeURIComponent(branch())}`);
    tree.innerHTML = entries.length ? entries.map(entry => `<div class="ws-tree-row" data-path="${escapeHtml(entry.path)}" data-type="${entry.type}"><span>${entry.type === 'directory' ? '📁' : '📄'}</span><span>${escapeHtml(entry.path)}</span></div>`).join('') : '<div class="ws-tree-row">Repository is empty.</div>';
  }

  async function loadCommits() {
    const commits = await api(`/api/v1/repositories/${repositoryId}/commits?branch=${encodeURIComponent(branch())}&limit=10`);
    document.getElementById('ws-commits').innerHTML = commits.map(commit => `<div class="ws-commit"><strong>${escapeHtml(commit.message)}</strong><span>${escapeHtml(commit.sha.slice(0,7))} · ${escapeHtml(commit.author)}</span></div>`).join('') || 'No commits yet.';
  }

  async function openFile(path) {
    const file = await api(`/api/v1/repositories/${repositoryId}/files?path=${encodeURIComponent(path)}&branch=${encodeURIComponent(branch())}`);
    selectedPath = path;
    currentFile.textContent = path;
    editor.value = file.content;
    editor.disabled = false;
    ['ws-save','ws-rename','ws-delete'].forEach(id => document.getElementById(id).disabled = false);
    tree.querySelectorAll('.ws-tree-row').forEach(row => row.classList.toggle('active', row.dataset.path === path));
    setStatus(`Editing ${path}`);
  }

  async function saveFile() {
    if (!selectedPath) return;
    setStatus('Committing…');
    await api(`/api/v1/repositories/${repositoryId}/files`, { method:'PUT', body: JSON.stringify({ path:selectedPath, content:editor.value, branch:branch(), commit_message:document.getElementById('ws-commit-message').value.trim() || `Update ${selectedPath}` }) });
    setStatus('Committed');
    await Promise.all([loadTree(), loadCommits()]);
  }

  async function createFile() {
    const path = prompt('New file path', 'Src/app/example.tsx');
    if (!path) return;
    selectedPath = path.trim();
    currentFile.textContent = selectedPath;
    editor.value = '';
    editor.disabled = false;
    ['ws-save','ws-rename','ws-delete'].forEach(id => document.getElementById(id).disabled = false);
    document.getElementById('ws-commit-message').value = `Create ${selectedPath}`;
    setStatus('New file ready to commit');
  }

  async function renameFile() {
    if (!selectedPath) return;
    const destination = prompt('Rename or move file to', selectedPath);
    if (!destination || destination === selectedPath) return;
    await api(`/api/v1/repositories/${repositoryId}/move`, { method:'POST', body:JSON.stringify({ source_path:selectedPath, destination_path:destination, branch:branch(), commit_message:`Move ${selectedPath} to ${destination}` }) });
    selectedPath = destination;
    currentFile.textContent = destination;
    await Promise.all([loadTree(), loadCommits()]);
    setStatus('File moved');
  }

  async function deleteFile() {
    if (!selectedPath || !confirm(`Delete ${selectedPath}?`)) return;
    await api(`/api/v1/repositories/${repositoryId}/files`, { method:'DELETE', body:JSON.stringify({ path:selectedPath, branch:branch(), commit_message:`Delete ${selectedPath}` }) });
    selectedPath = '';
    currentFile.textContent = 'Select a file';
    editor.value = '';
    editor.disabled = true;
    ['ws-save','ws-rename','ws-delete'].forEach(id => document.getElementById(id).disabled = true);
    await Promise.all([loadTree(), loadCommits()]);
    setStatus('File deleted');
  }

  async function newBranch() {
    const name = prompt('New branch name', 'feature/new-work');
    if (!name) return;
    await api(`/api/v1/repositories/${repositoryId}/branches`, { method:'POST', body:JSON.stringify({ name, source_branch:branch() }) });
    await loadBranches();
    branchSelect.value = name;
    await Promise.all([loadTree(), loadCommits()]);
  }

  async function runTool(mode, label) {
    output.textContent = `${label} started for ${repository.name} on ${branch()}…`;
    try {
      const result = await api('/api/v1/agent/run', { method:'POST', body:JSON.stringify({ mode, objective:`${label} repository ${repository.name} on branch ${branch()} using .Amosclaud-workflow/workflow.yml`, branch:branch(), metadata:{ repository_id:Number(repositoryId), repository_name:repository.name } }) });
      output.textContent = result.reply || `${label} completed.`;
    } catch (error) {
      output.textContent = `${label} failed: ${error.message}`;
    }
  }

  tree.addEventListener('click', event => { const row = event.target.closest('[data-path]'); if (row?.dataset.type === 'file') openFile(row.dataset.path).catch(error => setStatus(error.message)); });
  branchSelect.addEventListener('change', () => { selectedPath=''; editor.value=''; Promise.all([loadTree(),loadCommits()]); });
  document.getElementById('ws-save').addEventListener('click', () => saveFile().catch(error => setStatus(error.message)));
  document.getElementById('ws-new-file').addEventListener('click', createFile);
  document.getElementById('ws-rename').addEventListener('click', () => renameFile().catch(error => setStatus(error.message)));
  document.getElementById('ws-delete').addEventListener('click', () => deleteFile().catch(error => setStatus(error.message)));
  document.getElementById('ws-new-branch').addEventListener('click', () => newBranch().catch(error => setStatus(error.message)));
  document.getElementById('ws-build').addEventListener('click', () => runTool('build','Build'));
  document.getElementById('ws-test').addEventListener('click', () => runTool('autonomous-check','Tests'));
  document.getElementById('ws-review').addEventListener('click', () => runTool('autonomous-check','Review'));
  document.getElementById('ws-deploy').addEventListener('click', () => runTool('deploy','Deployment'));

  function escapeHtml(value){return String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

  (async () => { try { await loadRepository(); await loadBranches(); await Promise.all([loadTree(), loadCommits()]); editor.disabled = true; } catch (error) { setStatus(error.message); } })();
})();