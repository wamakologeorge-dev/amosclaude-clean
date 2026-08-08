(() => {
  const apiRoot = '/api/v1/pipelines/cooperation/runtime';
  const byId = (id) => document.getElementById(id);
  const nodeForm = byId('runtime-node-form');
  const nodeList = byId('runtime-node-list');
  const runtimeNotice = byId('runtime-notice');
  const pipelineList = byId('pipeline-list');

  function setRuntimeNotice(message, kind = '') {
    runtimeNotice.textContent = message;
    runtimeNotice.className = `runtime-notice ${kind}`.trim();
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      cache: 'no-store',
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
    const payload = response.status === 204 ? null : await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload?.detail || payload?.error || `Request failed (${response.status})`);
    }
    return payload;
  }

  function count(map, key) {
    return Number(map?.[key] || 0);
  }

  function renderOverview(data) {
    byId('runtime-ready-nodes').textContent = String(count(data.nodes, 'ready'));
    byId('runtime-active-leases').textContent = String(data.active_resource_leases || 0);
    byId('runtime-running-pods').textContent = String(count(data.java_pods, 'running'));
    byId('runtime-waiting-pods').textContent = String(count(data.java_pods, 'waiting_for_node'));
  }

  function resourceText(resources) {
    const available = resources?.available || {};
    return `${available.cpu_millis || 0}m CPU · ${available.memory_mb || 0} MB RAM · ${available.disk_mb || 0} MB disk`;
  }

  function actionButton(label, handler, className = '') {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.className = className;
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        await handler();
      } catch (error) {
        setRuntimeNotice(error.message, 'error');
      } finally {
        button.disabled = false;
      }
    });
    return button;
  }

  function renderNodes(items) {
    nodeList.innerHTML = '';
    if (!items.length) {
      nodeList.textContent = 'No execution nodes are registered. Register a node before creating a Java pod.';
      return;
    }
    items.forEach((node) => {
      const card = document.createElement('article');
      card.className = 'runtime-node-card';

      const heading = document.createElement('header');
      const title = document.createElement('strong');
      title.textContent = node.name;
      const status = document.createElement('span');
      status.textContent = node.status;
      status.dataset.status = node.status;
      heading.append(title, status);

      const endpoint = document.createElement('p');
      endpoint.textContent = node.endpoint || 'Local or privately connected node';
      const capacity = document.createElement('p');
      capacity.textContent = resourceText(node.resources);
      const capabilities = document.createElement('div');
      capabilities.className = 'runtime-capabilities';
      (node.capabilities || []).forEach((capability) => {
        const tag = document.createElement('span');
        tag.textContent = capability;
        capabilities.append(tag);
      });

      const actions = document.createElement('div');
      actions.className = 'runtime-node-actions';
      if (node.status === 'offline') {
        actions.append(actionButton('Return to ready', async () => {
          await request(`${apiRoot}/nodes/${node.id}/heartbeat`, {
            method: 'POST',
            body: JSON.stringify({ status: 'ready', metadata: { source: 'control-plane' } }),
          });
          setRuntimeNotice(`${node.name} is ready to accept resource leases.`, 'success');
          await refreshRuntime();
        }));
      } else {
        actions.append(actionButton('Mark offline', async () => {
          await request(`${apiRoot}/nodes/${node.id}/heartbeat`, {
            method: 'POST',
            body: JSON.stringify({ status: 'offline', metadata: { source: 'control-plane' } }),
          });
          setRuntimeNotice(`${node.name} is offline. PipeFail reassigned eligible Java pods.`, 'success');
          await refreshRuntime();
          await refreshPipelinePods();
        }, 'danger'));
      }

      card.append(heading, endpoint, capacity, capabilities, actions);
      nodeList.append(card);
    });
  }

  function renderPods(container, items) {
    container.innerHTML = '';
    if (!items.length) {
      container.textContent = 'No Java pods are attached to this pipeline.';
      return;
    }
    items.forEach((pod) => {
      const row = document.createElement('article');
      row.className = 'java-pod-row';
      const title = document.createElement('strong');
      title.textContent = `${pod.build_tool} · JDK ${pod.jdk}`;
      const state = document.createElement('span');
      state.textContent = pod.state;
      state.dataset.state = pod.state;
      const details = document.createElement('small');
      details.textContent = pod.node
        ? `${pod.node.name} · attempt ${pod.attempt}/${pod.max_attempts}`
        : `Waiting for a compatible node · attempt ${pod.attempt}/${pod.max_attempts}`;
      row.append(title, state, details);
      container.append(row);
    });
  }

  async function loadPipelinePods(card) {
    const pipelineId = card.dataset.pipelineId;
    const container = card.querySelector('.pipeline-java-pods');
    if (!pipelineId || !container) return;
    try {
      const data = await request(`${apiRoot}/pipelines/${pipelineId}/java-pods`);
      renderPods(container, data.items || []);
    } catch (error) {
      container.textContent = error.message;
      container.classList.add('error');
    }
  }

  async function createJavaPod(card) {
    const pipelineId = card.dataset.pipelineId;
    const tool = window.prompt('Java build tool: auto, maven, gradle, or javac', 'auto');
    if (tool === null) return;
    const buildTool = tool.trim().toLowerCase();
    if (!['auto', 'maven', 'gradle', 'javac'].includes(buildTool)) {
      throw new Error('Build tool must be auto, maven, gradle, or javac.');
    }
    await request(`${apiRoot}/pipelines/${pipelineId}/java-pods`, {
      method: 'POST',
      body: JSON.stringify({
        jdk: '21',
        build_tool: buildTool,
        cpu_millis: 1000,
        memory_mb: 2048,
        disk_mb: 4096,
        gpu_units: 0,
        network: 'restricted',
        max_attempts: 3,
        metadata: { source: 'amosclaud-control-plane' },
      }),
    });
    setRuntimeNotice('Java pod scheduled through a bounded resource lease.', 'success');
    await Promise.all([loadPipelinePods(card), refreshRuntime()]);
  }

  function decoratePipelineCard(card) {
    if (card.dataset.runtimeConnected === 'true') return;
    card.dataset.runtimeConnected = 'true';
    const actions = card.querySelector('.pipeline-runtime-actions');
    const state = card.querySelector('.pipeline-state')?.dataset.state;
    if (actions && !['completed', 'failed', 'cancelled'].includes(state)) {
      actions.append(actionButton('Create Java pod', () => createJavaPod(card)));
      actions.append(actionButton('Refresh Java pods', () => loadPipelinePods(card), 'secondary'));
    }
    loadPipelinePods(card);
  }

  function decoratePipelines() {
    pipelineList.querySelectorAll('.pipeline-card').forEach(decoratePipelineCard);
  }

  async function loadNodes() {
    const data = await request(`${apiRoot}/nodes`);
    renderNodes(data.items || []);
  }

  async function refreshRuntime() {
    const [overview, nodes] = await Promise.all([
      request(`${apiRoot}/overview`),
      request(`${apiRoot}/nodes`),
    ]);
    renderOverview(overview);
    renderNodes(nodes.items || []);
  }

  async function refreshPipelinePods() {
    await Promise.all([...pipelineList.querySelectorAll('.pipeline-card')].map(loadPipelinePods));
  }

  nodeForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const capabilities = byId('runtime-node-capabilities').value
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean);
      await request(`${apiRoot}/nodes`, {
        method: 'POST',
        body: JSON.stringify({
          name: byId('runtime-node-name').value.trim(),
          endpoint: byId('runtime-node-endpoint').value.trim() || null,
          capabilities,
          cpu_millis: Number(byId('runtime-node-cpu').value),
          memory_mb: Number(byId('runtime-node-memory').value),
          disk_mb: Number(byId('runtime-node-disk').value),
          gpu_units: 0,
          metadata: { source: 'amosclaud-control-plane' },
        }),
      });
      byId('runtime-node-name').value = '';
      setRuntimeNotice('Execution node registered with the shared pipeline resource broker.', 'success');
      await refreshRuntime();
    } catch (error) {
      setRuntimeNotice(error.message, 'error');
    } finally {
      button.disabled = false;
    }
  });

  new MutationObserver(decoratePipelines).observe(pipelineList, { childList: true, subtree: true });
  byId('refresh').addEventListener('click', () => {
    refreshRuntime().catch((error) => setRuntimeNotice(error.message, 'error'));
    refreshPipelinePods().catch((error) => setRuntimeNotice(error.message, 'error'));
  });

  (async () => {
    try {
      await refreshRuntime();
      decoratePipelines();
      setRuntimeNotice('Execution nodes, resource leases, Java pods, and PipeFail are connected.', 'success');
    } catch (error) {
      setRuntimeNotice(error.message, 'error');
    }
  })();
})();
