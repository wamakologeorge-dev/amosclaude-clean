(() => {
  const runButton = document.getElementById('btn-run-agent');
  const objectiveInput = document.getElementById('agent-objective-input');
  const modeInput = document.getElementById('agent-mode-input');
  const replies = document.getElementById('agent-replies');
  if (!runButton || !objectiveInput || !modeInput || !replies) return;

  const compose = runButton.closest('.agent-compose');
  const stopButton = document.createElement('button');
  stopButton.id = 'btn-stop-agent';
  stopButton.type = 'button';
  stopButton.className = 'btn-stop-agent';
  stopButton.textContent = 'Stop Agent';
  stopButton.hidden = true;
  compose.appendChild(stopButton);

  const mirror = document.createElement('section');
  mirror.className = 'agent-mirror';
  mirror.innerHTML = `
    <div class="agent-mirror-head">
      <div><strong>Live Work Mirror</strong><span id="agent-mirror-state">Waiting</span></div>
      <span class="agent-mirror-pulse" aria-hidden="true"></span>
    </div>
    <div id="agent-mirror-objective" class="agent-mirror-objective">Send an instruction to watch the Agent work.</div>
    <ol id="agent-mirror-steps" class="agent-mirror-steps"></ol>
  `;
  replies.before(mirror);

  const state = document.getElementById('agent-mirror-state');
  const objectiveView = document.getElementById('agent-mirror-objective');
  const stepsView = document.getElementById('agent-mirror-steps');
  let controller = null;
  let activeRunId = null;
  let stopped = false;
  let stepTimer = null;

  const plans = {
    build: [
      ['Repository', 'Opening the selected repository and reading .Amosclaud-workflow/workflow.yml'],
      ['Instructions', 'Understanding the developer instruction and preparing the build plan'],
      ['Builder AI', 'Creating or updating files inside Src/app'],
      ['Tester AI', 'Running checks and finding build problems'],
      ['Reviewer AI', 'Reviewing changes and preparing the final result'],
    ],
    'autonomous-check': [
      ['Repository', 'Inspecting repository status and workflow instructions'],
      ['Health', 'Checking source files, conflicts, and compilation'],
      ['Tests', 'Running the configured test suite'],
      ['Review', 'Preparing a clear result for the developer'],
    ],
    deploy: [
      ['Repository', 'Reading the repository and deployment configuration'],
      ['Build', 'Preparing the production build'],
      ['Tests', 'Checking the build before deployment'],
      ['Deployment', 'Starting the approved deployment workflow'],
    ],
    monitor: [
      ['Repository', 'Reading monitoring instructions'],
      ['Services', 'Checking application and deployment health'],
      ['Results', 'Preparing the latest monitoring report'],
    ],
  };

  function resetMirror(objective, mode) {
    stopped = false;
    objectiveView.textContent = objective;
    state.textContent = 'Starting';
    mirror.classList.add('agent-mirror-running');
    mirror.classList.remove('agent-mirror-stopped', 'agent-mirror-done');
    stepsView.innerHTML = '';
    (plans[mode] || plans.build).forEach(([title, text]) => {
      const item = document.createElement('li');
      item.innerHTML = `<span class="mirror-step-icon"></span><div><strong>${title}</strong><span>${text}</span></div>`;
      stepsView.appendChild(item);
    });
  }

  function animateSteps() {
    const steps = [...stepsView.children];
    let index = 0;
    const advance = () => {
      if (stopped || index >= steps.length) return;
      steps.forEach(item => item.classList.remove('is-active'));
      if (index > 0) steps[index - 1].classList.add('is-done');
      steps[index].classList.add('is-active');
      state.textContent = steps[index].querySelector('strong').textContent;
      index += 1;
      stepTimer = setTimeout(advance, 1200);
    };
    advance();
  }

  function finishMirror(success = true) {
    clearTimeout(stepTimer);
    [...stepsView.children].forEach(item => {
      item.classList.remove('is-active');
      if (success) item.classList.add('is-done');
    });
    state.textContent = success ? 'Completed' : 'Stopped';
    mirror.classList.remove('agent-mirror-running');
    mirror.classList.add(success ? 'agent-mirror-done' : 'agent-mirror-stopped');
  }

  function addReply(text) {
    const muted = replies.querySelector('.agent-reply.muted');
    if (muted) replies.innerHTML = '';
    const item = document.createElement('div');
    item.className = 'agent-reply';
    item.textContent = text;
    replies.prepend(item);
  }

  async function stopAgent() {
    if (!controller) return;
    stopped = true;
    controller.abort();
    finishMirror(false);
    stopButton.hidden = true;
    runButton.disabled = false;
    document.getElementById('agent-status').className = 'badge badge-failed';
    document.getElementById('agent-status').textContent = 'stopped';
    addReply('Amosclaud Agent stopped. Ask your question or send new instructions when you are ready.');

    if (activeRunId) {
      try {
        await fetch(`/api/v1/agent/runs/${encodeURIComponent(activeRunId)}/stop`, { method: 'POST' });
      } catch (error) {
        console.debug('[Agent stop]', error);
      }
    }
  }

  stopButton.addEventListener('click', stopAgent);

  runButton.addEventListener('click', async event => {
    event.preventDefault();
    event.stopImmediatePropagation();

    const objective = objectiveInput.value.trim();
    const mode = modeInput.value;
    if (!objective) {
      addReply('What would you like me to create today?');
      return;
    }

    activeRunId = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    controller = new AbortController();
    resetMirror(objective, mode);
    animateSteps();
    runButton.disabled = true;
    stopButton.hidden = false;
    document.getElementById('agent-status').className = 'badge badge-running';
    document.getElementById('agent-status').textContent = 'working';

    try {
      const response = await fetch('/api/v1/agent/run', {
        method: 'POST',
        signal: controller.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode,
          objective,
          branch: 'main',
          metadata: { branch: 'main', client_run_id: activeRunId },
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      if (stopped) return;
      finishMirror(true);
      addReply(data.reply || 'Amosclaud finished the repository task.');
      objectiveInput.value = '';
      document.getElementById('agent-status').className = 'badge badge-success';
      document.getElementById('agent-status').textContent = 'completed';
    } catch (error) {
      if (error.name !== 'AbortError') {
        finishMirror(false);
        addReply(`Amosclaud could not complete the task: ${error.message}`);
      }
    } finally {
      controller = null;
      activeRunId = null;
      runButton.disabled = false;
      stopButton.hidden = true;
    }
  }, true);
})();
