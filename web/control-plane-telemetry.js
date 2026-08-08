(() => {
  const apiRoot = '/api/v1/pipelines/cooperation/runtime';
  const byId = (id) => document.getElementById(id);
  const pipelineList = byId('pipeline-list');
  const proposerForm = byId('node-proposer-form');
  const proposalList = byId('node-proposal-list');
  const telemetryNotice = byId('telemetry-notice');
  const pipelineOptions = byId('telemetry-pipeline-options');

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

  function setNotice(message, kind = '') {
    telemetryNotice.textContent = message;
    telemetryNotice.className = `runtime-notice ${kind}`.trim();
  }

  function element(tag, className = '', text = '') {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== '') item.textContent = text;
    return item;
  }

  function badge(text, state) {
    const item = element('span', 'telemetry-badge', text);
    item.dataset.state = state;
    return item;
  }

  function formatNumber(value) {
    return new Intl.NumberFormat().format(Number(value || 0));
  }

  function resourceLabel(key) {
    return {
      cpu_millis: 'CPU',
      memory_mb: 'Memory',
      disk_mb: 'Disk',
      gpu_units: 'GPU',
    }[key] || key;
  }

  function resourceValue(key, value) {
    if (key === 'cpu_millis') return `${formatNumber(value)}m`;
    if (key === 'gpu_units') return String(value || 0);
    return `${formatNumber(value)} MB`;
  }

  function renderProposals(data) {
    proposalList.innerHTML = '';
    if (!(data.proposals || []).length) {
      proposalList.append(element('p', 'telemetry-empty', 'No execution nodes are registered.'));
      return;
    }

    const contract = element('p', 'telemetry-description');
    contract.textContent = data.selected_node_id
      ? `Proposed node: ${data.selected_node_id}. Pod creation will revalidate capacity.`
      : 'No eligible node currently satisfies the request.';
    proposalList.append(contract);

    data.proposals.forEach((proposal) => {
      const card = element('article', 'node-proposal-card');
      card.dataset.selected = String(Boolean(proposal.selected));
      card.dataset.eligible = String(Boolean(proposal.eligible));

      const heading = element('div', 'node-proposal-heading');
      const title = element('strong', '', `#${proposal.rank} ${proposal.name}`);
      const state = proposal.selected ? 'selected' : proposal.eligible ? 'eligible' : 'blocked';
      heading.append(title, badge(proposal.selected ? 'selected' : state, state));

      const score = element('small', '', `Score ${proposal.score} · ${proposal.status} · heartbeat ${proposal.heartbeat_age_seconds ?? 'unknown'}s`);
      const resources = element('div', 'node-resource-grid');
      Object.entries(proposal.resource_fit || {}).forEach(([key, fit]) => {
        const cell = element('span');
        cell.append(
          element('small', '', resourceLabel(key)),
          element('strong', '', `${resourceValue(key, fit.requested)} / ${resourceValue(key, fit.available)}`),
        );
        resources.append(cell);
      });

      const reasons = element('small');
      reasons.textContent = (proposal.reasons || []).join(' · ');
      card.append(heading, score, resources, reasons);
      proposalList.append(card);
    });
  }

  function renderBars(container, items) {
    container.innerHTML = '';
    if (!(items || []).length) {
      container.append(element('p', 'telemetry-empty', 'No PipeFail data.'));
      return;
    }
    items.forEach((item) => {
      const row = element('div', 'telemetry-bar-row');
      const label = element('span', '', item.key);
      const track = element('span', 'telemetry-bar-track');
      const fill = element('i', 'telemetry-bar-fill');
      fill.style.setProperty('--telemetry-percent', `${Math.max(item.percent, 2)}%`);
      track.append(fill);
      row.append(label, track, element('strong', '', String(item.count)));
      container.append(row);
    });
  }

  function renderTimeline(container, items) {
    container.innerHTML = '';
    if (!(items || []).length) {
      container.append(element('p', 'telemetry-empty', 'No failure timeline yet.'));
      return;
    }
    const maximum = Math.max(...items.map((item) => Number(item.total || 0)), 1);
    items.slice(-24).forEach((item) => {
      const column = element('span', 'telemetry-timeline-column');
      const bar = element('i');
      bar.title = `${item.bucket}: ${item.total} PipeFail events`;
      bar.style.setProperty('--telemetry-height', `${Math.max((item.total / maximum) * 56, 3)}px`);
      const label = element('small', '', String(item.bucket).slice(5, 13));
      column.append(bar, label);
      container.append(column);
    });
  }

  function renderFlow(container, graph) {
    container.innerHTML = '';
    const flow = element('div', 'pipefail-flow');
    (graph.nodes || []).forEach((node) => {
      const cell = element('article', 'pipefail-flow-node');
      cell.dataset.state = node.state;
      cell.append(
        element('strong', '', formatNumber(node.value)),
        element('small', '', node.label),
      );
      flow.append(cell);
    });
    container.append(flow);
  }

  function renderPipelineList(items, graphics) {
    const container = byId('pipefail-pipeline-list');
    container.innerHTML = '';
    if (!(items || []).length) {
      container.append(element('p', 'telemetry-empty', 'No pipelines have PipeFail events.'));
      return;
    }
    const graphById = new Map((graphics || []).map((graph) => [graph.pipeline.id, graph]));
    items.forEach((item) => {
      const card = element('article', 'pipefail-pipeline-card');
      const heading = element('div', 'pipefail-pipeline-heading');
      const title = element('strong', '', item.objective || item.id);
      heading.append(title, badge(item.state, item.state === 'failed' ? 'terminal' : 'pipeline'));
      const meta = element('small', '', `${item.id} · ${item.mode} · ${item.branch}`);
      const flowContainer = element('div');
      const graph = graphById.get(item.id);
      if (graph) renderFlow(flowContainer, graph);
      card.append(heading, meta, flowContainer);
      container.append(card);
    });
  }

  function renderEvents(items) {
    const container = byId('pipefail-event-list');
    container.innerHTML = '';
    if (!(items || []).length) {
      container.append(element('p', 'telemetry-empty', 'No PipeFail events have been recorded.'));
      return;
    }
    items.slice(0, 30).forEach((item) => {
      const event = element('article', 'pipefail-event');
      const heading = element('div', 'pipefail-event-heading');
      heading.append(
        element('strong', '', item.kind),
        badge(item.action, item.action === 'retry_reassigned' ? 'recovered' : item.action === 'failed' ? 'terminal' : 'waiting'),
      );
      const detail = element('p', '', item.error_detail);
      const meta = element(
        'small',
        '',
        `${item.pipeline_objective || item.pipeline_id} · ${item.node_name || item.node_id || 'unassigned'} · ${item.created_at}`,
      );
      event.append(heading, detail, meta);
      container.append(event);
    });
  }

  function renderTelemetry(data) {
    const summary = data.summary || {};
    byId('pipefail-total').textContent = formatNumber(summary.total);
    byId('pipefail-recovered').textContent = formatNumber(summary.recovered);
    byId('pipefail-waiting').textContent = formatNumber(summary.waiting_for_node);
    byId('pipefail-terminal').textContent = formatNumber(summary.terminal);
    renderBars(byId('pipefail-kind-chart'), data.dimensions?.kind || []);
    renderBars(byId('pipefail-action-chart'), data.dimensions?.action || []);
    renderTimeline(byId('pipefail-timeline'), data.timeline || []);
    renderPipelineList(data.pipelines || [], data.graphics || []);
    renderEvents(data.items || []);
  }

  async function refreshTelemetry() {
    const data = await request(`${apiRoot}/telemetry/pipefail?limit=1000`);
    renderTelemetry(data);
    setNotice('Node proposer, all-PipeFail telemetry, and pipeline graphics are current.', 'success');
  }

  async function loadPipelineTelemetry(card) {
    const pipelineId = card.dataset.pipelineId;
    const container = card.querySelector('.pipeline-pipefail-graphics');
    if (!pipelineId || !container) return;
    try {
      const data = await request(`${apiRoot}/pipelines/${pipelineId}/telemetry?limit=500`);
      container.innerHTML = '';
      const heading = element('div', 'telemetry-section-heading');
      heading.append(
        element('strong', '', 'PipeFail / pipeline graphics'),
        badge(`${data.summary.total} events`, data.summary.terminal ? 'terminal' : data.summary.recovered ? 'recovered' : 'pipeline'),
      );
      container.append(heading);
      const graph = data.graphics?.[0];
      if (graph) renderFlow(container, graph);
    } catch (error) {
      container.textContent = error.message;
      container.classList.add('error');
    }
  }

  function updatePipelineOptions() {
    const ids = [...pipelineList.querySelectorAll('.pipeline-card')]
      .map((card) => card.dataset.pipelineId)
      .filter(Boolean);
    const existing = new Set([...pipelineOptions.options].map((option) => option.value));
    ids.forEach((id) => {
      if (existing.has(id)) return;
      const option = document.createElement('option');
      option.value = id;
      pipelineOptions.append(option);
    });
  }

  function decoratePipelineCards() {
    updatePipelineOptions();
    pipelineList.querySelectorAll('.pipeline-card').forEach((card) => {
      if (card.dataset.telemetryConnected === 'true') return;
      card.dataset.telemetryConnected = 'true';
      loadPipelineTelemetry(card);
    });
  }

  proposerForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const pipelineId = byId('node-proposer-pipeline').value.trim();
      const data = await request(`${apiRoot}/telemetry/node-proposer`, {
        method: 'POST',
        body: JSON.stringify({
          pipeline_id: pipelineId || null,
          jdk: byId('node-proposer-jdk').value,
          build_tool: byId('node-proposer-tool').value,
          cpu_millis: Number(byId('node-proposer-cpu').value),
          memory_mb: Number(byId('node-proposer-memory').value),
          disk_mb: Number(byId('node-proposer-disk').value),
          gpu_units: Number(byId('node-proposer-gpu').value),
          stale_after_seconds: 300,
        }),
      });
      renderProposals(data);
      setNotice('Node proposal calculated from current heartbeat, capability, and resource telemetry.', 'success');
    } catch (error) {
      setNotice(error.message, 'error');
    } finally {
      button.disabled = false;
    }
  });

  new MutationObserver(decoratePipelineCards).observe(pipelineList, {
    childList: true,
    subtree: true,
  });

  byId('refresh').addEventListener('click', () => {
    refreshTelemetry().catch((error) => setNotice(error.message, 'error'));
    [...pipelineList.querySelectorAll('.pipeline-card')].forEach((card) => {
      loadPipelineTelemetry(card);
    });
  });

  (async () => {
    try {
      await refreshTelemetry();
      decoratePipelineCards();
    } catch (error) {
      setNotice(error.message, 'error');
    }
  })();
})();
