(() => {
  const repositoryId = location.pathname.split('/').filter(Boolean).pop();
  const container = document.getElementById('ws-issues');
  const newIssueButton = document.getElementById('ws-new-issue');
  const refreshButton = document.getElementById('ws-refresh-issues');
  if (!container || !/^\d+$/.test(repositoryId || '')) return;

  let activeIssueId = null;
  let pollTimer = null;
  let requestSequence = 0;

  const escapeHtml = value => String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

  const fullText = value => {
    const text = String(value || '').trim();
    if (!text) return '<p class="ws-issue-empty-copy">No instructions were written for this issue.</p>';
    return `<div class="ws-issue-copy">${escapeHtml(text).replace(/\n/g, '<br>')}</div>`;
  };

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      cache: 'no-store',
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
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail || data.message || `Request failed (${response.status})`;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return data;
  }

  function selectedBranch() {
    return document.getElementById('ws-branch')?.value || 'main';
  }

  function setWorkspaceStatus(message) {
    const target = document.getElementById('ws-status');
    if (target) target.textContent = message;
  }

  function activateTab(name) {
    const tab = document.querySelector(`.ws-tab[data-tab="${name}"]`);
    const panel = document.querySelector(`.ws-panel[data-panel="${name}"]`);
    if (!tab || !panel) return;
    document.querySelectorAll('.ws-tab').forEach(item => {
      item.classList.toggle('active', item === tab);
      item.setAttribute('aria-selected', String(item === tab));
    });
    document.querySelectorAll('.ws-panel').forEach(item => {
      item.classList.toggle('active', item === panel);
    });
    history.replaceState(null, '', `${location.pathname}${location.search}#${name}`);
    if (name === 'issues') loadIssues();
  }

  function stopPolling() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = null;
  }

  function scheduleRefresh(issue) {
    stopPolling();
    const active = (issue.activity || []).some(item => {
      const status = item.pipeline?.status;
      return status === 'pending' || status === 'running';
    });
    if (active && activeIssueId === issue.id) {
      pollTimer = setTimeout(() => openIssue(issue.id, true), 4000);
    }
  }

  function renderActivity(item) {
    const pipeline = item.pipeline || null;
    const status = pipeline?.status || item.event_kind;
    const reply = pipeline?.reply || item.body || 'No result was recorded.';
    const sameAsBody = String(reply).trim() === String(item.body || '').trim();
    return `<article class="ws-issue-activity">
      <div class="ws-issue-activity-head">
        <strong>${item.actor_kind === 'amosclaud' ? 'Amosclaud Action' : escapeHtml(item.actor_kind)}</strong>
        <span class="ws-issue-status ws-issue-status-${escapeHtml(status)}">${escapeHtml(status)}</span>
      </div>
      <time>${escapeHtml((item.created_at || '').replace('T', ' ').slice(0, 19))}</time>
      <div class="ws-issue-activity-body">${fullText(item.body)}</div>
      ${sameAsBody ? '' : `<div class="ws-issue-result"><strong>Current result</strong>${fullText(reply)}</div>`}
      ${pipeline?.id ? `<div class="ws-issue-pipeline">Pipeline: <code>${escapeHtml(pipeline.id)}</code></div>` : ''}
    </article>`;
  }

  function renderIssueDetail(issue) {
    const activity = issue.activity || [];
    container.innerHTML = `<section class="ws-issue-detail" data-open-issue="${issue.id}">
      <div class="ws-issue-detail-toolbar">
        <button type="button" data-issue-back>← All issues</button>
        <button type="button" data-issue-refresh="${issue.id}">Refresh</button>
      </div>
      <header class="ws-issue-detail-head">
        <div>
          <span>Issue #${issue.id}</span>
          <h3>${escapeHtml(issue.title)}</h3>
          <p>${escapeHtml(issue.state)} · updated ${escapeHtml((issue.updated_at || '').slice(0, 10))}</p>
        </div>
      </header>
      <section class="ws-issue-instructions" aria-label="Complete issue instructions">
        <h4>Instructions</h4>
        ${fullText(issue.body)}
      </section>
      <div class="ws-issue-action-bar">
        <button type="button" data-run-issue-action="${issue.id}">Run Amosclaud Action</button>
        <span>The Action result will stay attached to this issue after refresh.</span>
      </div>
      <section class="ws-issue-timeline" aria-label="Issue activity timeline">
        <h4>Activity</h4>
        ${activity.length ? activity.map(renderActivity).join('') : '<div class="ws-empty-row">No Amosclaud Action has reported on this issue yet.</div>'}
      </section>
    </section>`;
    scheduleRefresh(issue);
  }

  async function openIssue(issueId, silent = false) {
    const sequence = ++requestSequence;
    activeIssueId = Number(issueId);
    if (!silent) container.innerHTML = '<div class="ws-empty-row">Loading the complete issue…</div>';
    try {
      const issue = await api(`/api/v1/repositories/${repositoryId}/issues/${issueId}`);
      if (sequence !== requestSequence || activeIssueId !== Number(issueId)) return;
      renderIssueDetail(issue);
      setWorkspaceStatus(`Viewing issue #${issue.id}`);
    } catch (error) {
      if (sequence !== requestSequence) return;
      container.innerHTML = `<div class="ws-empty-row ws-error-row">Could not open issue: ${escapeHtml(error.message)}</div>`;
    }
  }

  function renderIssueCard(issue) {
    return `<article class="ws-tool-item ws-issue-card" data-issue-id="${issue.id}" role="button" tabindex="0" aria-label="Open issue ${escapeHtml(issue.title)}">
      <div class="ws-issue-card-head">
        <strong>#${issue.id} ${escapeHtml(issue.title)}</strong>
        <span>${escapeHtml(issue.state)} · updated ${escapeHtml((issue.updated_at || '').slice(0, 10))}</span>
      </div>
      <div class="ws-issue-card-body">${fullText(issue.body)}</div>
      <span class="ws-issue-open-hint">Tap to open the full issue and Amosclaud Action timeline.</span>
    </article>`;
  }

  async function loadIssues() {
    stopPolling();
    activeIssueId = null;
    const sequence = ++requestSequence;
    container.innerHTML = '<div class="ws-empty-row">Loading issues…</div>';
    try {
      const issues = await api(`/api/v1/repositories/${repositoryId}/issues`);
      if (sequence !== requestSequence || activeIssueId !== null) return;
      container.innerHTML = issues.length
        ? issues.map(renderIssueCard).join('')
        : '<div class="ws-empty-row">No issues yet.</div>';
      setWorkspaceStatus(`${issues.length} issue${issues.length === 1 ? '' : 's'} loaded`);
    } catch (error) {
      if (sequence !== requestSequence) return;
      container.innerHTML = `<div class="ws-empty-row ws-error-row">Could not load issues: ${escapeHtml(error.message)}</div>`;
    }
  }

  async function createIssue() {
    const title = prompt('Issue title');
    if (!title?.trim()) return;
    const body = prompt('Write the complete issue instructions') || '';
    await api(`/api/v1/repositories/${repositoryId}/issues`, {
      method: 'POST',
      body: JSON.stringify({ title: title.trim(), body }),
    });
    await loadIssues();
    setWorkspaceStatus('Issue created with its instructions visible.');
  }

  async function runIssueAction(issueId) {
    const extra = prompt(
      'Optional follow-up for Amosclaud Action. Leave blank to use the issue instructions exactly.',
      '',
    );
    if (extra === null) return;
    const actionButton = container.querySelector(`[data-run-issue-action="${issueId}"]`);
    if (actionButton) {
      actionButton.disabled = true;
      actionButton.textContent = 'Starting Amosclaud Action…';
    }
    try {
      const issue = await api(`/api/v1/repositories/${repositoryId}/issues/${issueId}/actions`, {
        method: 'POST',
        body: JSON.stringify({
          mode: 'fix',
          branch: selectedBranch(),
          instructions: extra,
        }),
      });
      activeIssueId = Number(issueId);
      renderIssueDetail(issue);
      setWorkspaceStatus(`Amosclaud Action attached to issue #${issueId}.`);
    } catch (error) {
      setWorkspaceStatus(`Could not start Amosclaud Action: ${error.message}`);
      if (actionButton) {
        actionButton.disabled = false;
        actionButton.textContent = 'Run Amosclaud Action';
      }
    }
  }

  newIssueButton?.addEventListener('click', event => {
    event.preventDefault();
    event.stopImmediatePropagation();
    createIssue().catch(error => setWorkspaceStatus(`Could not create issue: ${error.message}`));
  }, true);

  refreshButton?.addEventListener('click', event => {
    event.preventDefault();
    event.stopImmediatePropagation();
    if (activeIssueId) openIssue(activeIssueId); else loadIssues();
  }, true);

  container.addEventListener('click', event => {
    const back = event.target.closest('[data-issue-back]');
    if (back) {
      loadIssues();
      return;
    }
    const refresh = event.target.closest('[data-issue-refresh]');
    if (refresh) {
      openIssue(refresh.dataset.issueRefresh);
      return;
    }
    const action = event.target.closest('[data-run-issue-action]');
    if (action) {
      runIssueAction(action.dataset.runIssueAction);
      return;
    }
    const card = event.target.closest('[data-issue-id]');
    if (card) openIssue(card.dataset.issueId);
  });

  container.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const card = event.target.closest('[data-issue-id]');
    if (!card) return;
    event.preventDefault();
    openIssue(card.dataset.issueId);
  });

  document.addEventListener('click', event => {
    const trigger = event.target.closest('.ws-tab[data-tab],[data-open-tab],[data-open-workspace-tab]');
    if (!trigger) return;
    const name = trigger.dataset.tab || trigger.dataset.openTab || trigger.dataset.openWorkspaceTab;
    if (!name) return;
    if (trigger.hasAttribute('data-open-tab')) {
      document.getElementById('account-drawer')?.setAttribute('hidden', '');
      document.getElementById('account-drawer-backdrop')?.setAttribute('hidden', '');
    }
    if (name === 'issues') {
      event.preventDefault();
      event.stopImmediatePropagation();
      activateTab(name);
      return;
    }
    queueMicrotask(() => activateTab(name));
  }, true);

  const requestedTab = location.hash.replace(/^#/, '');
  if (requestedTab === 'issues') queueMicrotask(() => activateTab('issues'));
})();
