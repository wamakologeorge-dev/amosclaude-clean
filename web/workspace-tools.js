(() => {
  const repositoryId = location.pathname.split('/').filter(Boolean).pop();
  const escapeHtml = value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  function safeGithubUrl(value) {
    try {
      const url = new URL(String(value || ''));
      return url.protocol === 'https:' && url.hostname === 'github.com' ? url.href : '';
    } catch {
      return '';
    }
  }

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
    const raw = response.status === 204 ? '' : await response.text();
    let data = null;
    if (raw) {
      try { data = JSON.parse(raw); } catch { data = { detail: raw }; }
    }
    if (!response.ok) {
      const error = new Error(data?.detail || data?.message || `Request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function openTab(name) {
    const tab = document.querySelector(`.ws-tab[data-tab="${name}"]`);
    if (tab) tab.click();
    document.getElementById('account-drawer')?.setAttribute('hidden', '');
    document.getElementById('account-drawer-backdrop')?.setAttribute('hidden', '');
  }

  async function loadIssues() {
    const target = document.getElementById('ws-issues');
    target.innerHTML = '<div class="ws-empty-row">Loading issues…</div>';
    try {
      const issues = await api(`/api/v1/repositories/${repositoryId}/issues`);
      target.innerHTML = issues.map(issue => `<article class="ws-tool-item">
        <strong>#${issue.id} ${escapeHtml(issue.title)}</strong>
        <span>${escapeHtml(issue.state)}${issue.labels?.length ? ` · ${escapeHtml(issue.labels.join(', '))}` : ''}</span>
        ${issue.body ? `<span>${escapeHtml(issue.body)}</span>` : ''}
        <div class="ws-tool-item-actions"><button type="button" data-toggle-issue="${issue.id}" data-state="${escapeHtml(issue.state)}">${issue.state === 'open' ? 'Close issue' : 'Reopen issue'}</button></div>
      </article>`).join('') || '<div class="ws-empty-row">No issues yet.</div>';
    } catch (error) {
      target.innerHTML = `<div class="ws-empty-row">${escapeHtml(error.message)}</div>`;
    }
  }

  async function createIssue() {
    const title = prompt('Issue title');
    if (!title?.trim()) return;
    const body = prompt('Issue description (optional)', '') || '';
    const labelText = prompt('Labels separated by commas (optional)', '') || '';
    const labels = labelText.split(',').map(item => item.trim()).filter(Boolean);
    await api(`/api/v1/repositories/${repositoryId}/issues`, {
      method: 'POST',
      body: JSON.stringify({ title: title.trim(), body, labels }),
    });
    await loadIssues();
  }

  async function toggleIssue(id, state) {
    await api(`/api/v1/repositories/${repositoryId}/issues/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ state: state === 'open' ? 'closed' : 'open' }),
    });
    await loadIssues();
  }

  async function pullRequestFeed() {
    try {
      const result = await api(`/api/v1/github/repositories/${repositoryId}/pull-requests`);
      return {
        source: 'github',
        label: result.github_full_name || 'GitHub',
        items: Array.isArray(result.pull_requests) ? result.pull_requests : [],
      };
    } catch (error) {
      if (error.status !== 404) throw error;
      const items = await api(`/api/v1/repositories/${repositoryId}/pull-requests`);
      return { source: 'amosclaud', label: 'Amosclaud', items };
    }
  }

  function renderPullRequest(pr, feed) {
    const source = pr.source || feed.source;
    const state = pr.draft && pr.state === 'open' ? 'draft' : pr.state;
    const url = source === 'github' ? safeGithubUrl(pr.html_url) : '';
    const body = String(pr.body || '').slice(0, 2000);
    const updated = pr.updated_at ? ` · updated ${escapeHtml(pr.updated_at)}` : '';
    const actions = [];
    if (source === 'amosclaud' && pr.state === 'open') {
      actions.push(`<button type="button" data-merge-pr="${pr.id}">Merge pull request</button>`);
    }
    if (url) {
      actions.push(`<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Open on GitHub</a>`);
    }
    return `<article class="ws-tool-item">
      <strong>#${pr.number || pr.id} ${escapeHtml(pr.title)}</strong>
      <span>${escapeHtml(pr.head_branch)} → ${escapeHtml(pr.base_branch)} · ${escapeHtml(state)} · ${escapeHtml(source)}${updated}</span>
      ${body ? `<span>${escapeHtml(body)}</span>` : ''}
      ${actions.length ? `<div class="ws-tool-item-actions">${actions.join('')}</div>` : ''}
    </article>`;
  }

  async function loadPullRequests() {
    const target = document.getElementById('ws-pull-requests');
    target.innerHTML = '<div class="ws-empty-row">Refreshing pull requests…</div>';
    try {
      const feed = await pullRequestFeed();
      const header = `<div class="ws-empty-row">Live source: ${escapeHtml(feed.label)} · open, closed, and merged</div>`;
      const cards = feed.items.map(pr => renderPullRequest(pr, feed)).join('');
      target.innerHTML = header + (cards || '<div class="ws-empty-row">No pull requests yet.</div>');
    } catch (error) {
      target.innerHTML = `<div class="ws-empty-row">${escapeHtml(error.message)}</div>`;
    }
  }

  async function createPullRequest() {
    const branchSelect = document.getElementById('ws-branch');
    const headBranch = prompt('Head branch (branch with your changes)', branchSelect?.value || 'feature/new-work');
    if (!headBranch?.trim()) return;
    const baseBranch = prompt('Base branch (branch to merge into)', 'main');
    if (!baseBranch?.trim()) return;
    const title = prompt('Pull request title', `Merge ${headBranch} into ${baseBranch}`);
    if (!title?.trim()) return;
    const body = prompt('Pull request description (optional)', '') || '';
    await api(`/api/v1/repositories/${repositoryId}/pull-requests`, {
      method: 'POST',
      body: JSON.stringify({ title: title.trim(), body, head_branch: headBranch.trim(), base_branch: baseBranch.trim() }),
    });
    await loadPullRequests();
  }

  async function mergePullRequest(id) {
    if (!confirm(`Merge pull request #${id}?`)) return;
    await api(`/api/v1/repositories/${repositoryId}/pull-requests/${id}/merge`, { method: 'POST' });
    await loadPullRequests();
  }

  function runAgent(sourceButtonId, label) {
    const output = document.getElementById('ws-agent-output');
    const hiddenOutput = document.getElementById('ws-output');
    output.textContent = `${label} started…`;
    document.getElementById(sourceButtonId)?.click();
    const copyResult = () => {
      if (hiddenOutput?.textContent) output.textContent = hiddenOutput.textContent;
    };
    copyResult();
    if (hiddenOutput) {
      const observer = new MutationObserver(copyResult);
      observer.observe(hiddenOutput, { childList: true, characterData: true, subtree: true });
      setTimeout(() => observer.disconnect(), 120000);
    }
  }

  document.querySelectorAll('[data-open-tab]').forEach(button => button.addEventListener('click', () => openTab(button.dataset.openTab)));
  document.querySelector('.ws-tab[data-tab="issues"]')?.addEventListener('click', () => loadIssues());
  document.querySelector('.ws-tab[data-tab="pull-requests"]')?.addEventListener('click', () => loadPullRequests());
  document.getElementById('ws-new-issue')?.addEventListener('click', () => createIssue().catch(error => alert(error.message)));
  document.getElementById('ws-refresh-issues')?.addEventListener('click', loadIssues);
  document.getElementById('ws-new-pr')?.addEventListener('click', () => createPullRequest().catch(error => alert(error.message)));
  document.getElementById('ws-refresh-prs')?.addEventListener('click', loadPullRequests);
  document.getElementById('ws-issues')?.addEventListener('click', event => {
    const button = event.target.closest('[data-toggle-issue]');
    if (button) toggleIssue(button.dataset.toggleIssue, button.dataset.state).catch(error => alert(error.message));
  });
  document.getElementById('ws-pull-requests')?.addEventListener('click', event => {
    const button = event.target.closest('[data-merge-pr]');
    if (button) mergePullRequest(button.dataset.mergePr).catch(error => alert(error.message));
  });
  document.getElementById('ws-agent-build')?.addEventListener('click', () => runAgent('ws-build', 'Build'));
  document.getElementById('ws-agent-test')?.addEventListener('click', () => runAgent('ws-test', 'Test'));
  document.getElementById('ws-agent-review')?.addEventListener('click', () => runAgent('ws-review', 'Review'));
  document.getElementById('ws-agent-deploy')?.addEventListener('click', () => runAgent('ws-deploy', 'Deploy'));

  setInterval(() => {
    const tab = document.querySelector('.ws-tab[data-tab="pull-requests"]');
    if (!document.hidden && tab?.classList.contains('active')) loadPullRequests();
  }, 60000);
})();
