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
    item.querySelector('strong').textContent = String(title || 'Activity');
    item.querySelector('p').textContent = String(detail || '');
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
    const primary = document.createElement('code');
    primary.textContent = left;
    row.appendChild(primary);
    if (right) {
      const secondary = document.createElement('span');
      secondary.textContent = right;
      row.appendChild(secondary);
    }
    return row;
  }

  function extractFiles(data) {
    const direct = Array.isArray(data.changed_files) ? data.changed_files : [];
    const fromLogs = (Array.isArray(data.logs) ? data.logs : []).flatMap(line => {
      const matches = String(line).match(/(?:[A-Za-z0-9_.-]+\/)+[A-Za-z0-9_.-]+/g);
      return matches || [];
    });
    return [...new Set([...direct, ...fromLogs])]
      .filter(value => !value.startsWith('http') && !value.startsWith('/api/'))
      .slice(0, 50);
  }

  function resultCards(data) {
    const cards = [];
    const summary = document.createElement('article');
    summary.className = 'workbench-result-card';
    const title = document.createElement('strong');
    title.textContent = String(data.status || '').toLowerCase() === 'failed' ? 'Job needs attention' : 'Verified job result';
    const message = document.createElement('p');
    message.textContent = data.reply || data.message || 'The runtime returned a completed result.';
    summary.append(title, message);
    cards.push(summary);

    const jobs = Array.isArray(data.jobs) ? data.jobs : [];
    jobs.forEach(job => {
      const card = document.createElement('article');
      card.className = 'workbench-result-card';
      const heading = document.createElement('strong');
      heading.textContent = job.name || 'Executed job';
      const state = document.createElement('span');
      state.textContent = `Status: ${job.status || 'unknown'}`;
      card.append(heading, state);
      const jobLogs = Array.isArray(job.logs) ? job.logs : [];
      if (jobLogs.length) {
        const pre = document.createElement('pre');
        pre.textContent = jobLogs.join('\n');
        card.appendChild(pre);
      }
      cards.push(card);
    });

    const logs = Array.isArray(data.logs) ? data.logs : [];
    if (!jobs.length && logs.length) {
      const evidence = document.createElement('article');
      evidence.className = 'workbench-result-card';
      const heading = document.createElement('strong');
      heading.textContent = 'Execution evidence';
      const pre = document.createElement('pre');
      pre.textContent = logs.join('\n');
      evidence.append(heading, pre);
      cards.push(evidence);
    }

    const externalLocations = [
      data.result_url,
      data.pull_request_url,
      data.issue_url,
      data.deployment_url,
      ...(Array.isArray(data.result_locations) ? data.result_locations : []),
    ].filter(value => /^https?:\/\//i.test(String(value || '')));

    [...new Set(externalLocations)].forEach(value => {
      const card = document.createElement('article');
      card.className = 'workbench-result-card';
      const heading = document.createElement('strong');
      heading.textContent = 'Verified external result';
      const link = document.createElement('a');
      link.href = value;
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = value;
      card.append(heading, link);
      cards.push(card);
    });

    return cards;
  }

  async function createDoctorIssue(data) {
    const failedChecks = (Array.isArray(data.checks) ? data.checks : [])
      .filter(item => String(item.status).toLowerCase() === 'failed');
    if (!failedChecks.length) return;
    try {
      const response = await fetch('/api/v1/doctor/issues', {
        method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          source: 'autonomous-workbench', severity: 'error', auto_start: true,
          title: `Autonomous mission needs attention: ${mission.textContent || 'mission'}`,
          endpoint: '/api/v1/agent/run', error_type: 'verification_failure',
          safe_detail: failedChecks.map(item => `${item.name}: ${item.summary || 'failed'}`).join('; ').slice(0, 1800),
          evidence: {pipeline_id: data.pipeline_id || '', mode: mode.textContent || '', failed_checks: failedChecks},
        }),
      });
      if (!response.ok) throw new Error('Administrator authorization is required');
      const issue = await response.json();
      addEvent('Doctor Medical issue created', `Issue ${issue.issue_id} is diagnosing the failure in baby steps.`, 'complete', 'D');
    } catch (error) {
      addEvent('Admin report pending', error.message || 'Doctor Medical could not create the issue.', 'failed', '!');
    }
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
    fillList(results, [], 'Real job results will appear here after execution.', item => item);
    approvals.innerHTML = '<div class="workbench-empty">No approval is currently required.</div>';
    addEvent('Mission accepted', detail.objective || 'Instruction received', 'complete', '1');
  });

  window.addEventListener('amosclaud:agent-phase', event => {
    const detail = event.detail || {};
    const percentByPhase = [15, 32, 56, 78, 94, 98];
    setProgress(percentByPhase[detail.index] || 10);
    addEvent(
      detail.phase || 'Agent activity',
      detail.note || detail.state || 'Working',
      detail.state === 'failed' ? 'failed' : detail.state === 'complete' ? 'complete' : 'active',
      String((detail.index ?? 0) + 1),
    );
  });

  window.addEventListener('amosclaud:agent-result', async event => {
    const data = event.detail || {};
    clearInterval(timer);
    setRuntime();
    const failed = String(data.status || '').toLowerCase() === 'failed';
    status.textContent = failed ? 'Needs attention' : 'Verified';
    setProgress(100);
    addEvent(
      failed ? 'Mission stopped with evidence' : 'Mission completed',
      data.reply || data.message || 'Result received',
      failed ? 'failed' : 'complete',
      failed ? '×' : '✓',
    );

    const fileItems = extractFiles(data);
    fillList(files, fileItems, 'No repository files were changed for this request.', item => listItem(item, 'observed'));
    const checkItems = Array.isArray(data.checks) ? data.checks : [];
    fillList(
      checks,
      checkItems,
      'No separate verification checks were returned.',
      item => listItem(item.name || 'check', `${item.status || 'unknown'} — ${item.summary || ''}`),
    );
    fillList(results, resultCards(data), 'The runtime returned no result evidence.', item => item);

    root.querySelector('[data-workbench-tab="results"]')?.click();
    root.scrollIntoView({ behavior: 'smooth', block: 'start' });

    if (failed) {
      addEvent('Self-healing handoff', 'Autonomous is organizing the failure and reporting it to Doctor Medical.', 'active', '+');
      await createDoctorIssue(data);
    }
  });

  window.addEventListener('amosclaud:agent-error', event => {
    clearInterval(timer);
    setRuntime();
    status.textContent = 'Failed';
    setProgress(100);
    addEvent('Mission failed safely', event.detail?.message || 'Unknown error', 'failed', '×');
  });
})();
