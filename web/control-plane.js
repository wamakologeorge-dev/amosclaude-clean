(() => {
  const apiRoot = '/api/v1/pipelines/cooperation';
  const state = { repositories: [], pipelines: [], workers: [], claims: new Map() };
  const byId = (id) => document.getElementById(id);
  const notice = byId('notice');
  const repositorySelect = byId('repository-select');
  const environmentSelect = byId('environment-select');
  const moduleList = byId('module-list');
  const pipelineList = byId('pipeline-list');
  const workerList = byId('worker-list');
  const pipelineTemplate = byId('pipeline-template');

  function setNotice(message, kind = '') {
    notice.textContent = message;
    notice.className = `notice ${kind}`.trim();
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      cache: 'no-store',
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
    if (response.status === 204) return null;
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || payload.error || `Request failed (${response.status})`);
    return payload;
  }

  const titleCase = (value) => String(value || '')
    .replaceAll('_', ' ')
    .replaceAll('-', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

  function renderModules(modules) {
    moduleList.innerHTML = '';
    modules.forEach((module) => {
      const item = document.createElement('li');
      item.dataset.status = module.status;
      const name = document.createElement('span');
      name.textContent = module.name;
      const status = document.createElement('small');
      status.textContent = module.status;
      item.append(name, status);
      moduleList.append(item);
    });
  }

  function renderRepositories(items) {
    state.repositories = items;
    const selected = repositorySelect.value;
    repositorySelect.innerHTML = '<option value="">Platform workspace</option>';
    items.forEach((repository) => {
      const option = document.createElement('option');
      option.value = String(repository.id);
      option.textContent = `${repository.name} · ${repository.role}`;
      repositorySelect.append(option);
    });
    if ([...repositorySelect.options].some((option) => option.value === selected)) {
      repositorySelect.value = selected;
    }
  }

  const count = (map, key) => Number(map?.[key] || 0);

  function renderOverview(data) {
    const pipelineCounts = data.pipeline_counts || {};
    const taskCounts = data.task_counts || {};
    const workerCounts = data.worker_counts || {};
    const active = ['created', 'queued', 'running', 'waiting_for_approval', 'verifying']
      .reduce((total, key) => total + count(pipelineCounts, key), 0);
    byId('active-pipelines').textContent = String(active);
    byId('pending-approvals').textContent = String(data.pending_approvals || 0);
    byId('ready-workers').textContent = String(count(workerCounts, 'ready'));
    byId('queued-tasks').textContent = String(count(taskCounts, 'queued'));
    renderModules(data.modules || []);
  }

  function renderArtifacts(container, artifacts) {
    container.innerHTML = '';
    if (!artifacts.length) {
      container.textContent = 'No artifacts have been submitted yet.';
      return;
    }
    artifacts.forEach((artifact) => {
      const row = document.createElement('div');
      const safeLink = /^(https?:\/\/|\/)/.test(artifact.uri || '');
      if (safeLink) {
        const link = document.createElement('a');
        link.href = artifact.uri;
        link.target = '_blank';
        link.rel = 'noreferrer';
        link.textContent = `${artifact.kind}: ${artifact.name}`;
        row.append(link);
      } else {
        row.textContent = `${artifact.kind}: ${artifact.name} · ${artifact.uri}`;
      }
      container.append(row);
    });
  }

  function actionButton(label, handler, className = '') {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.className = className;
    button.addEventListener('click', async () => {
      button.disabled = true;
      try { await handler(); }
      catch (error) { setNotice(error.message, 'error'); }
      finally { button.disabled = false; }
    });
    return button;
  }

  function renderPipelines(items) {
    state.pipelines = items;
    pipelineList.innerHTML = '';
    if (!items.length) {
      pipelineList.textContent = 'No cooperation pipelines yet.';
      return;
    }

    items.forEach((pipeline) => {
      const card = pipelineTemplate.content.firstElementChild.cloneNode(true);
      card.dataset.pipelineId = pipeline.id;
      card.querySelector('.pipeline-mode').textContent = pipeline.mode;
      card.querySelector('.pipeline-objective').textContent = pipeline.objective;
      const pipelineState = card.querySelector('.pipeline-state');
      pipelineState.textContent = titleCase(pipeline.state);
      pipelineState.dataset.state = pipeline.state;

      const meta = card.querySelector('.pipeline-meta');
      const repository = state.repositories.find((item) => item.id === pipeline.repository_id);
      [
        ['Pipeline', pipeline.id.slice(0, 18)],
        ['Repository', repository?.name || pipeline.project_id || 'Platform workspace'],
        ['Environment', pipeline.environment],
        ['Branch', pipeline.branch],
        ['Role', pipeline.repository_role || 'platform'],
      ].forEach(([term, value]) => {
        const wrapper = document.createElement('div');
        const dt = document.createElement('dt');
        const dd = document.createElement('dd');
        dt.textContent = term;
        dd.textContent = value;
        wrapper.append(dt, dd);
        meta.append(wrapper);
      });

      const taskList = card.querySelector('.task-list');
      (pipeline.tasks || []).forEach((task) => {
        const item = document.createElement('li');
        item.dataset.sequence = task.sequence;
        item.dataset.state = task.state;
        const name = document.createElement('span');
        name.textContent = task.name;
        const status = document.createElement('small');
        status.textContent = `${task.state} · ${task.capability}`;
        item.append(name, status);
        taskList.append(item);
      });

      const actions = card.querySelector('.pipeline-actions');
      const pending = (pipeline.approvals || []).find((approval) => approval.state === 'pending');
      if (pending) {
        actions.append(actionButton('Approve protected stages', async () => {
          await request(`${apiRoot}/pipelines/${pipeline.id}/approve`, {
            method: 'POST',
            body: JSON.stringify({ reason: 'Approved from the Amosclaud Control Plane' }),
          });
          setNotice('Protected stages approved. Matching workers may claim them.', 'success');
          await refreshAll();
        }));
        actions.append(actionButton('Reject', async () => {
          const reason = window.prompt('Reason for rejecting this approval:', 'Not authorized');
          if (reason === null) return;
          await request(`${apiRoot}/pipelines/${pipeline.id}/reject`, {
            method: 'POST', body: JSON.stringify({ reason }),
          });
          setNotice('Approval rejected and blocked work cancelled.', 'success');
          await refreshAll();
        }, 'danger'));
      }

      if (!['completed', 'failed', 'cancelled'].includes(pipeline.state)) {
        actions.append(actionButton('Cancel pipeline', async () => {
          await request(`${apiRoot}/pipelines/${pipeline.id}/cancel`, { method: 'POST' });
          setNotice('Pipeline cancelled.', 'success');
          await refreshAll();
        }, 'danger'));
      }

      renderArtifacts(card.querySelector('.artifact-list'), pipeline.artifacts || []);
      pipelineList.append(card);
    });
  }

  async function claimTask(worker) {
    const result = await request(`${apiRoot}/workers/${worker.id}/claim`, { method: 'POST' });
    if (!result.task) {
      setNotice(`No queued task matches ${worker.name}'s capabilities.`);
      return;
    }
    state.claims.set(worker.id, result.task);
    setNotice(`${worker.name} claimed: ${result.task.name}`, 'success');
    await Promise.all([loadWorkers(), loadPipelines(), loadOverview()]);
  }

  async function completeClaim(worker, task) {
    const summary = window.prompt('Completion summary:', `${task.name} completed with evidence.`);
    if (summary === null) return;
    await request(`${apiRoot}/tasks/${task.id}/complete`, {
      method: 'POST',
      body: JSON.stringify({ worker_id: worker.id, summary, output: {}, artifacts: [] }),
    });
    state.claims.delete(worker.id);
    setNotice(`${task.name} completed. The next dependency-ready task was queued.`, 'success');
    await refreshAll();
  }

  async function failClaim(worker, task) {
    const error = window.prompt('Failure evidence:', 'Worker could not complete the task.');
    if (error === null) return;
    const retryable = window.confirm('Should Amosclaud retry this task?');
    await request(`${apiRoot}/tasks/${task.id}/fail`, {
      method: 'POST', body: JSON.stringify({ worker_id: worker.id, error, retryable }),
    });
    state.claims.delete(worker.id);
    setNotice(retryable ? 'Task returned to the queue.' : 'Task and pipeline marked failed.', retryable ? 'success' : 'error');
    await refreshAll();
  }

  function renderWorkers(items) {
    state.workers = items;
    workerList.innerHTML = '';
    if (!items.length) {
      workerList.textContent = 'No workers registered.';
      return;
    }
    items.forEach((worker) => {
      const card = document.createElement('article');
      card.className = 'worker-card';
      const header = document.createElement('header');
      const name = document.createElement('strong');
      name.textContent = worker.name;
      const status = document.createElement('span');
      status.textContent = `${worker.status} · ${worker.active_tasks}/${worker.capacity}`;
      header.append(name, status);

      const capabilities = document.createElement('div');
      capabilities.className = 'capability-list';
      worker.capabilities.forEach((capability) => {
        const tag = document.createElement('span');
        tag.textContent = capability;
        capabilities.append(tag);
      });
      card.append(header, capabilities);

      const actions = document.createElement('div');
      actions.className = 'pipeline-actions';
      const claim = state.claims.get(worker.id);
      if (claim) {
        const claimLabel = document.createElement('p');
        claimLabel.textContent = `Claimed: ${claim.name}`;
        card.append(claimLabel);
        actions.append(actionButton('Complete with evidence', () => completeClaim(worker, claim)));
        actions.append(actionButton('Fail or retry', () => failClaim(worker, claim), 'danger'));
      } else {
        actions.append(actionButton('Claim next task', () => claimTask(worker)));
      }
      card.append(actions);
      workerList.append(card);
    });
  }

  async function loadRepositories() {
    const data = await request('/api/v1/repositories');
    renderRepositories(Array.isArray(data) ? data : data.items || []);
  }
  async function loadOverview() { renderOverview(await request(`${apiRoot}/overview`)); }
  async function loadPipelines() {
    const data = await request(`${apiRoot}/pipelines?limit=100`);
    renderPipelines(data.items || []);
  }
  async function loadWorkers() {
    const data = await request(`${apiRoot}/workers`);
    renderWorkers(data.items || []);
  }
  async function refreshAll() {
    await Promise.all([loadOverview(), loadPipelines(), loadWorkers()]);
  }

  byId('pipeline-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const repositoryId = Number(repositorySelect.value) || null;
      const mode = byId('pipeline-mode').value;
      const allowWrites = byId('pipeline-write-approval').checked;
      await request(`${apiRoot}/pipelines`, {
        method: 'POST',
        body: JSON.stringify({
          objective: byId('pipeline-objective').value.trim(),
          mode,
          repository_id: repositoryId,
          project_id: repositoryId ? null : 'platform-workspace',
          environment: environmentSelect.value,
          branch: byId('pipeline-branch').value.trim() || 'main',
          allow_writes: allowWrites,
          metadata: { source: 'amosclaud-control-plane' },
        }),
      });
      setNotice(
        allowWrites || !['build', 'fix', 'deploy'].includes(mode)
          ? 'Pipeline created and ready for cooperating workers.'
          : 'Pipeline created. Read-only stages can run before protected write approval.',
        'success',
      );
      byId('pipeline-objective').value = '';
      byId('pipeline-write-approval').checked = false;
      await refreshAll();
    } catch (error) {
      setNotice(error.message, 'error');
    } finally {
      button.disabled = false;
    }
  });

  byId('worker-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const capabilities = byId('worker-capabilities').value
        .split(',').map((value) => value.trim()).filter(Boolean);
      await request(`${apiRoot}/workers`, {
        method: 'POST',
        body: JSON.stringify({
          name: byId('worker-name').value.trim(),
          capabilities,
          capacity: Number(byId('worker-capacity').value || 1),
          metadata: { source: 'amosclaud-control-plane' },
        }),
      });
      setNotice('Cooperating worker registered.', 'success');
      byId('worker-name').value = '';
      await refreshAll();
    } catch (error) {
      setNotice(error.message, 'error');
    } finally {
      button.disabled = false;
    }
  });

  byId('refresh').addEventListener('click', async () => {
    try { await refreshAll(); setNotice('Control plane refreshed.', 'success'); }
    catch (error) { setNotice(error.message, 'error'); }
  });

  (async () => {
    try {
      await loadRepositories();
      await refreshAll();
      setNotice('Control plane connected. Pipelines and workers are ready.', 'success');
    } catch (error) {
      setNotice(error.message, 'error');
    }
  })();
})();
