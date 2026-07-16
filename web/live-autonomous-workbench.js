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
    const row = document.createElement('div');
    row.className = 'workbench-item';
    const a = document.createElement('code');
    a.textContent = left;
    row.appendChild(a);
    if (right) {
      const b = document.createElement('span');
      b.textContent = right;
      row.appendChild(b);
    }
    return row;
  }
  function extractFiles(data) {
    const direct = Array.isArray(data.changed_files) ? data.changed_files : [];
    const fromLogs = (Array.isArray(data.logs) ? data.logs : []).flatMap(line => {
      const matches = String(line).match(/(?:[A-Za-z0-9_.-]+\/)+[A-Za-z0-9_.-]+/g);
      return matches || [];
    });
    return [...new Set([...direct, ...fromLogs])].filter(value => !value.startsWith('http')).slice(0, 50);
  }
  function explicitResultLinks(data) {
    const values = [
      data.result_url,
      data.pull_request_url,
      data.issue_url,
      data.deployment_url,
      ...(Array.isArray(data.result_locations) ? data.result_locations : []),
    ].filter(Boolean).map(String);
    if (data.pipeline_id) values.unshift(`/pipelines/${encodeURIComponent(data.pipeline_id)}`);
    return [...new Set(values)].slice(0, 20);
  }
  function documentationLinks(data) {
    const links = [];
    (Array.isArray(data.logs) ? data.logs : []).forEach(line => {
      const found = String(line).match(/https?:\/\/[^\s)]+/g);
      if (found) links.push(...found);
    });
    return [...new Set(links)].filter(value => !explicitResultLinks(data).includes(value)).slice(0, 5);
  }
  function problemAdvice(check) {
    const name = String(check.name || 'verification');
    const text = `${name} ${check.summary || ''} ${(check.details || []).join(' ')}`.toLowerCase();
    if (name === 'server-tests') {
      return {
        title: 'Focused server verification failed',
        cause: 'One or more server contracts did not match the current application response.',
        steps: ['Keep the mission open', 'Record the exact failed assertion', 'Run the Amosclaud focused server tests', 'Apply only an authorized code fix', 'Retest before reporting success'],
        automatic: 'Autonomous recorded the evidence and can retry safe verification. Code changes require Fix authorization.',
      };
    }
    if (text.includes('deprecated') || text.includes('on_event')) {
      return {
        title: 'Deprecated startup handler detected',
        cause: 'The application still uses an older FastAPI startup-event API.',
        steps: ['Locate the startup handler', 'Prepare a lifespan replacement', 'Run focused health checks', 'Deploy only after verification'],
        automatic: 'This is normally non-blocking. Autonomous should prepare the repair and request approval before editing.',
      };
    }
    if (text.includes('connection refused') || text.includes('unavailable')) {
      return {
        title: 'Required runtime service is unavailable',
        cause: 'A worker or model endpoint could not accept the connection.',
        steps: ['Check service health', 'Retry with bounded backoff', 'Use a configured fallback', 'Report the unavailable connector to the administrator'],
        automatic: 'Autonomous may retry and use safe fallbacks, but it must not claim completion without a healthy result.',
      };
    }
    return {
      title: `${name} needs attention`,
      cause: check.summary || 'Verification returned a blocker.',
      steps: ['Preserve the evidence', 'Classify the failure', 'Apply a safe recovery when available', 'Retest', 'Escalate unresolved work to the administrator'],
      automatic: 'Autonomous recorded this problem. Unsafe or write actions remain approval-controlled.',
    };
  }
  function problemCard(check) {
    const advice = problemAdvice(check);
    const card = document.createElement('article');
    card.className = 'workbench-item workbench-problem-card';
    const title = document.createElement('strong');
    title.textContent = advice.title;
    const cause = document.createElement('p');
    cause.textContent = `What happened: ${advice.cause}`;
    const auto = document.createElement('p');
    auto.textContent = `Autonomous action: ${advice.automatic}`;
    const list = document.createElement('ol');
    advice.steps.forEach(step => {
      const item = document.createElement('li');
      item.textContent = step;
      list.appendChild(item);
    });
    card.append(title, cause, auto, list);
    return card;
  }
  function resultLink(value) {
    const row = document.createElement('div');
    row.className = 'workbench-item';
    const link = document.createElement('a');
    link.className = 'workbench-result-link';
    link.href = value;
    link.textContent = value.startsWith('/pipelines/') ? 'Open Amosclaud mission and administrator report' : value;
    link.target = value.startsWith('http') ? '_blank' : '_self';
    link.rel = 'noopener';
    row.appendChild(link);
    return row;
  }
  function documentationCard(value) {
    const row = document.createElement('div');
    row.className = 'workbench-item workbench-documentation-card';
    const text = document.createElement('span');
    text.textContent = 'Official documentation is available as an optional reference. Amosclaud has kept your mission open here.';
    const link = document.createElement('a');
    link.href = value;
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = 'Open official documentation';
    row.append(text, link);
    return row;
  }

  root.querySelectorAll('.workbench-tab').forEach(button => button.addEventListener('click', () => {
    root.querySelectorAll('.workbench-tab').forEach(tab => tab.classList.toggle('active', tab === button));
    root.querySelectorAll('.workbench-view').forEach(view => view.classList.toggle('active', view.dataset.workbenchView === button.dataset.workbenchTab));
  }));

  window.addEventListener('amosclaud:agent-start', event => {
    const detail = event.detail || {};
    startedAt = Date.now();
    clearInterval(timer);
    timer = setInterval(setRuntime, 1000);
    setRuntime();
    timeline.innerHTML = '';
    mission.textContent = detail.objective || 'Agent mission';
    mode.textContent = detail.mode || 'inspect';
    status.textContent = 'Running';
    setProgress(8);
    fillList(files, [], 'Files will appear when Autonomous inspects or changes them.', listItem);
    fillList(checks, [], 'Verification checks will appear here.', listItem);
    fillList(results, [], 'Result links will appear after creation or deployment.', listItem);
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
    clearInterval(timer);
    setRuntime();
    const failed = String(data.status || '').toLowerCase() === 'failed';
    status.textContent = failed ? 'Needs attention' : 'Verified';
    setProgress(100);
    addEvent(failed ? 'Mission stopped with evidence' : 'Mission completed', data.reply || data.message || 'Result received', failed ? 'failed' : 'complete', failed ? '×' : '✓');

    const fileItems = extractFiles(data);
    fillList(files, fileItems, 'No repository files were changed for this request.', item => listItem(item, 'observed'));

    const checkItems = Array.isArray(data.checks) ? data.checks : [];
    fillList(checks, checkItems, 'No engineering checks were required for this assistant response.', item => {
      if (item.status === 'failed' || item.status === 'warning') return problemCard(item);
      return listItem(item.name || 'check', `${item.status || 'unknown'} — ${item.summary || ''}`);
    });

    const links = explicitResultLinks(data);
    fillList(results, links, 'No external result was created. The mission evidence remains available in Amosclaud.', resultLink);
    documentationLinks(data).forEach(value => results.appendChild(documentationCard(value)));

    if (failed && data.pipeline_id) {
      addEvent('Problem reported to administrator', `Internal incident is attached to pipeline ${data.pipeline_id}.`, 'complete', '!');
    }
  });

  window.addEventListener('amosclaud:agent-error', event => {
    clearInterval(timer);
    setRuntime();
    status.textContent = 'Failed';
    setProgress(100);
    addEvent('Mission failed safely', event.detail?.message || 'Unknown error', 'failed', '×');
    addEvent('Administrator report prepared', 'The failure remains in the Agent activity record for diagnosis and recovery.', 'complete', '!');
  });
})();
