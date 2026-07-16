(() => {
  const root = document.getElementById('live-autonomous-workbench');
  if (!root) return;

  const timeline = root.querySelector('[data-workbench-timeline]');
  const progress = root.querySelector('[data-workbench-progress]');
  const status = root.querySelector('[data-workbench-status]');
  const mission = root.querySelector('[data-workbench-mission]');
  const runtime = root.querySelector('[data-workbench-runtime]');
  const mode = root.querySelector('[data-workbench-mode]');
  const files = root.querySelector('[data-workbench-files]');
  const checks = root.querySelector('[data-workbench-checks]');
  const results = root.querySelector('[data-workbench-results]');
  const approvals = root.querySelector('[data-workbench-approvals]');
  let startedAt = null;
  let timer = null;

  function escapeText(value) { return String(value ?? ''); }
  function stamp() { return new Date().toLocaleTimeString(); }
  function setProgress(value) { progress.style.width = `${Math.max(0, Math.min(100, value))}%`; }
  function setRuntime() {
    if (!startedAt) { runtime.textContent = '00:00'; return; }
    const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
    runtime.textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  }
  function addEvent(title, detail, state = 'active', icon = '•') {
    timeline.querySelector('.workbench-empty')?.remove();
    const item = document.createElement('article');
    item.className = `workbench-event ${state}`;
    item.innerHTML = '<div class="workbench-event-icon"></div><div><strong></strong><p></p><time></time></div>';
    item.querySelector('.workbench-event-icon').textContent = icon;
    item.querySelector('strong').textContent = escapeText(title);
    item.querySelector('p').textContent = escapeText(detail);
    item.querySelector('time').textContent = stamp();
    timeline.appendChild(item);
    timeline.scrollTop = timeline.scrollHeight;
  }
  function fillList(container, items, emptyMessage, render) {
    container.innerHTML = '';
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'workbench-empty';
      empty.textContent = emptyMessage;
      container.appendChild(empty);
      return;
    }
    items.forEach(item => container.appendChild(render(item)));
  }
  function listItem(left, right = '') {
    const row = document.createElement('div'); row.className = 'workbench-item';
    const a = document.createElement('code'); a.textContent = left; row.appendChild(a);
    if (right) { const b = document.createElement('span'); b.textContent = right; row.appendChild(b); }
    return row;
  }
  function extractFiles(data) {
    const direct = Array.isArray(data.changed_files) ? data.changed_files : [];
    const fromLogs = (Array.isArray(data.logs) ? data.logs : []).flatMap(line => {
      const matches = String(line).match(/(?:[A-Za-z0-9_.-]+\/)+[A-Za-z0-9_.-]+/g);
      return matches || [];
    });
    return [...new Set([...direct, ...fromLogs])].slice(0, 50);
  }
  function extractLinks(data) {
    const links = [];
    const values = [data.result_url, data.pull_request_url, data.issue_url, data.deployment_url, ...(Array.isArray(data.result_locations) ? data.result_locations : [])].filter(Boolean);
    (Array.isArray(data.logs) ? data.logs : []).forEach(line => {
      const found = String(line).match(/https?:\/\/[^\s)]+/g); if (found) values.push(...found);
    });
    [...new Set(values)].forEach(value => links.push(String(value)));
    if (data.pipeline_id) links.unshift(`/pipelines/${encodeURIComponent(data.pipeline_id)}`);
    return links.slice(0, 20);
  }
  function resultLabel(value) {
    if (value.startsWith('/pipelines/')) return 'Open Amosclaud pipeline';
    if (/github\.com\/.+\/pull\//i.test(value)) return 'Open GitHub pull request';
    if (/github\.com\/.+\/issues\//i.test(value)) return 'Open GitHub issue';
    if (/railway\.(app|com)/i.test(value)) return 'Open Railway deployment';
    if (/fastapi\.tiangolo\.com/i.test(value)) return 'Official FastAPI reference';
    if (value.startsWith('http')) return 'External reference';
    return 'Open Amosclaud result';
  }
  function resultSummary(value) {
    if (/fastapi\.tiangolo\.com\/advanced\/events/i.test(value)) {
      return 'Reference for replacing deprecated startup events with FastAPI lifespan handlers. Amosclaud should apply and verify the code fix before marking the mission complete.';
    }
    if (value.startsWith('/pipelines/')) return 'Internal mission evidence, checks, logs, and final status.';
    if (/github\.com\/.+\/pull\//i.test(value)) return 'External code review result created by Autonomous.';
    if (/github\.com\/.+\/issues\//i.test(value)) return 'Issue reported for administrator and developer follow-up.';
    return value.startsWith('http') ? 'Optional external destination. The current Amosclaud mission remains open in this page.' : 'Internal Amosclaud result.';
  }
  function resultCard(value) {
    const row = document.createElement('div');
    row.className = 'workbench-item workbench-result-card';
    const body = document.createElement('div');
    const title = document.createElement('strong');
    const summary = document.createElement('p');
    const link = document.createElement('a');
    title.textContent = resultLabel(value);
    summary.textContent = resultSummary(value);
    link.className = 'workbench-result-link';
    link.href = value;
    link.textContent = value.startsWith('http') ? 'Open optional reference' : 'Open result';
    link.target = value.startsWith('http') ? '_blank' : '_self';
    link.rel = 'noopener noreferrer';
    body.append(title, summary, link);
    row.appendChild(body);
    return row;
  }

  root.querySelectorAll('.workbench-tab').forEach(button => button.addEventListener('click', () => {
    root.querySelectorAll('.workbench-tab').forEach(tab => tab.classList.toggle('active', tab === button));
    root.querySelectorAll('.workbench-view').forEach(view => view.classList.toggle('active', view.dataset.workbenchView === button.dataset.workbenchTab));
  }));

  window.addEventListener('amosclaud:agent-start', event => {
    const detail = event.detail || {};
    startedAt = Date.now(); clearInterval(timer); timer = setInterval(setRuntime, 1000); setRuntime();
    timeline.innerHTML = '';
    mission.textContent = detail.objective || 'Agent mission'; mode.textContent = detail.mode || 'inspect'; status.textContent = 'Running'; setProgress(8);
    fillList(files, [], 'Files will appear when Autonomous inspects or changes them.', listItem);
    fillList(checks, [], 'Verification checks will appear here.', listItem);
    fillList(results, [], 'Result locations and optional references will appear here.', listItem);
    approvals.innerHTML = '<div class="workbench-empty">No approval is currently required.</div>';
    addEvent('Mission accepted', detail.objective || 'Instruction received', 'complete', '1');
  });

  window.addEventListener('amosclaud:agent-phase', event => {
    const detail = event.detail || {};
    const percentByPhase = [15, 32, 48, 68, 86, 96];
    setProgress(percentByPhase[detail.index] || 10);
    addEvent(detail.phase || 'Agent activity', detail.note || detail.state || 'Working', detail.state === 'failed' ? 'failed' : detail.state === 'complete' ? 'complete' : 'active', String((detail.index ?? 0) + 1));
    if (detail.index === 3 && /authoriz|approval|write/i.test(detail.note || '')) {
      approvals.innerHTML = '<div class="approval-card"><strong>Protected action</strong><div>Autonomous may only write, commit, open a pull request, or deploy when the selected mode authorizes it.</div></div>';
    }
  });

  window.addEventListener('amosclaud:agent-result', event => {
    const data = event.detail || {};
    clearInterval(timer); setRuntime();
    const failed = String(data.status || '').toLowerCase() === 'failed'; status.textContent = failed ? 'Needs attention' : 'Verified'; setProgress(100);
    addEvent(failed ? 'Mission stopped with evidence' : 'Mission completed', data.reply || data.message || 'Result received', failed ? 'failed' : 'complete', failed ? '×' : '✓');
    const fileItems = extractFiles(data);
    fillList(files, fileItems, 'No repository files were changed for this request.', item => listItem(item, 'observed'));
    const checkItems = Array.isArray(data.checks) ? data.checks : [];
    fillList(checks, checkItems, 'No engineering checks were required for this assistant response.', item => listItem(item.name || 'check', `${item.status || 'unknown'} — ${item.summary || ''}`));
    const links = extractLinks(data);
    fillList(results, links, 'No result location was returned.', resultCard);
  });

  window.addEventListener('amosclaud:agent-error', event => {
    clearInterval(timer); setRuntime(); status.textContent = 'Failed'; setProgress(100);
    addEvent('Mission failed safely', event.detail?.message || 'Unknown error', 'failed', '×');
  });
})();
