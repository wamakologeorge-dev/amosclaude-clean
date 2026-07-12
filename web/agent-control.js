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
  mirror.hidden = true;
  mirror.innerHTML = `
    <div class="agent-mirror-head">
      <div><strong>Agent Work Demonstration</strong><span id="agent-mirror-state">Waiting</span></div>
      <span class="agent-mirror-pulse" aria-hidden="true"></span>
    </div>
    <div id="agent-mirror-objective" class="agent-mirror-objective"></div>
    <ol id="agent-mirror-steps" class="agent-mirror-steps"></ol>
    <div class="agent-code-mirror">
      <div class="agent-code-toolbar">
        <span id="agent-code-file">No file selected</span>
        <span id="agent-code-progress">ready</span>
      </div>
      <pre id="agent-code-output" aria-live="polite"><code></code></pre>
    </div>
  `;
  replies.before(mirror);

  const state = document.getElementById('agent-mirror-state');
  const objectiveView = document.getElementById('agent-mirror-objective');
  const stepsView = document.getElementById('agent-mirror-steps');
  const codeOutput = document.getElementById('agent-code-output');
  const codeFile = document.getElementById('agent-code-file');
  const codeProgress = document.getElementById('agent-code-progress');
  const statusBadge = document.getElementById('agent-status');

  let controller = null;
  let activeRunId = null;
  let stopped = false;
  let stepTimer = null;
  let writeTimer = null;

  const greetingWords = new Set(['hi', 'hello', 'hey', 'hiya', 'yo', 'good morning', 'good afternoon', 'good evening']);

  function addReply(text, kind = '') {
    const muted = replies.querySelector('.agent-reply.muted');
    if (muted) replies.innerHTML = '';
    const item = document.createElement('div');
    item.className = `agent-reply ${kind}`.trim();
    item.textContent = text;
    replies.prepend(item);
  }

  function developerName() {
    const raw = document.getElementById('current-user')?.textContent?.trim() || 'Developer';
    return raw.split(/\s+/)[0] || 'Developer';
  }

  function buildPlan(objective, mode) {
    const target = mode === 'deploy' ? 'deployment' : mode === 'monitor' ? 'monitoring setup' : 'application';
    return [
      ['Understand', `I am reading your request and identifying what the ${target} needs.`],
      ['Plan', 'I will explain the files and changes before writing them.'],
      ['Create files', 'I will show each file name before I write its contents.'],
      ['Build and test', 'I will run the workflow checks and report what passed or failed.'],
      ['Finish', 'I will summarize the result and offer to deploy it for you.'],
    ];
  }

  function codePreview(objective, mode) {
    const safeObjective = objective.replace(/`/g, "'").replace(/</g, '&lt;').replace(/>/g, '&gt;');
    if (mode === 'build' || mode === 'autonomous-check') {
      return [
        ['.Amosclaud-workflow/workflow.yml', `name: Amosclaud Workflow\nversion: 1\nentry: Src/app/example.tsx\nsteps:\n  - understand\n  - build\n  - test\n  - review\n`],
        ['Src/app/example.tsx', `type ProjectProps = {\n  request: string;\n};\n\nexport default function Example({ request }: ProjectProps) {\n  return (\n    <main className="amosclaud-project">\n      <h1>Your project is ready</h1>\n      <p>${safeObjective}</p>\n      <button type="button">Get started</button>\n    </main>\n  );\n}\n`],
      ];
    }
    if (mode === 'deploy') {
      return [['.Amosclaud-workflow/deploy.yml', `environment: production\nsource: Src/app/example.tsx\nchecks:\n  - build\n  - test\n  - healthcheck\nrequest: ${safeObjective}\n`]];
    }
    return [['.Amosclaud-workflow/monitor.yml', `service: Amosclaud application\nchecks:\n  - health\n  - uptime\n  - errors\nrequest: ${safeObjective}\n`]];
  }

  function prepareMirror(objective, mode) {
    stopped = false;
    mirror.hidden = false;
    mirror.classList.add('agent-mirror-running');
    mirror.classList.remove('agent-mirror-stopped', 'agent-mirror-done');
    objectiveView.textContent = `Your request: ${objective}`;
    state.textContent = 'Understanding your request';
    stepsView.innerHTML = '';
    codeOutput.textContent = '';
    codeFile.textContent = 'Preparing work plan';
    codeProgress.textContent = 'planning';

    buildPlan(objective, mode).forEach(([title, text]) => {
      const item = document.createElement('li');
      item.innerHTML = `<span class="mirror-step-icon"></span><div><strong>${title}</strong><span>${text}</span></div>`;
      stepsView.appendChild(item);
    });
  }

  async function demonstratePlan(objective, mode) {
    const steps = [...stepsView.children];
    addReply(`I understand that you want: ${objective}`);
    await delay(350);
    addReply('Here is how I am going to build it: I will inspect the repository, create the required files, run the build and tests, review the result, and then prepare it for deployment.');

    for (let index = 0; index < steps.length; index += 1) {
      if (stopped) return;
      steps.forEach(item => item.classList.remove('is-active'));
      if (index > 0) steps[index - 1].classList.add('is-done');
      const step = steps[index];
      step.classList.add('is-active');
      state.textContent = step.querySelector('strong').textContent;
      await delay(550);
    }
  }

  async function demonstrateFiles(objective, mode) {
    const files = codePreview(objective, mode);
    for (const [path, content] of files) {
      if (stopped) return;
      addReply(`Now I will create ${path}.`);
      codeFile.textContent = path;
      codeOutput.textContent = '';
      codeProgress.textContent = 'writing';
      let position = 0;

      await new Promise(resolve => {
        const writeChunk = () => {
          if (stopped) {
            resolve();
            return;
          }
          const remaining = content.length - position;
          const chunkSize = Math.min(remaining, 5 + Math.floor(Math.random() * 8));
          position += chunkSize;
          codeOutput.textContent = content.slice(0, position);
          codeOutput.scrollTop = codeOutput.scrollHeight;
          codeProgress.textContent = `${Math.round((position / content.length) * 100)}%`;
          if (position >= content.length) {
            codeProgress.textContent = 'created';
            writeTimer = setTimeout(resolve, 500);
          } else {
            writeTimer = setTimeout(writeChunk, 24);
          }
        };
        writeChunk();
      });
      addReply(`${path} is created. I am moving to the next step.`);
    }
  }

  function delay(ms) {
    return new Promise(resolve => {
      stepTimer = setTimeout(resolve, ms);
    });
  }

  function finishMirror(success = true) {
    clearTimeout(stepTimer);
    clearTimeout(writeTimer);
    [...stepsView.children].forEach(item => {
      item.classList.remove('is-active');
      if (success) item.classList.add('is-done');
    });
    state.textContent = success ? 'Work demonstrated' : 'Stopped';
    codeProgress.textContent = success ? 'complete' : 'stopped';
    mirror.classList.remove('agent-mirror-running');
    mirror.classList.add(success ? 'agent-mirror-done' : 'agent-mirror-stopped');
  }

  async function stopAgent() {
    if (!controller) return;
    stopped = true;
    controller.abort();
    finishMirror(false);
    stopButton.hidden = true;
    runButton.disabled = false;
    statusBadge.className = 'badge badge-failed';
    statusBadge.textContent = 'stopped';
    addReply('I stopped the work. Ask your question, and I will explain before continuing.');
  }

  stopButton.addEventListener('click', stopAgent);

  runButton.addEventListener('click', async event => {
    event.preventDefault();
    event.stopImmediatePropagation();

    const objective = objectiveInput.value.trim();
    const mode = modeInput.value;
    const normalized = objective.toLowerCase().replace(/[.!?]+$/, '').trim();

    if (!objective || greetingWords.has(normalized)) {
      mirror.hidden = true;
      addReply(`Hi ${developerName()}. What do you want to create today?`);
      return;
    }

    activeRunId = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    controller = new AbortController();
    prepareMirror(objective, mode);
    runButton.disabled = true;
    stopButton.hidden = false;
    statusBadge.className = 'badge badge-running';
    statusBadge.textContent = 'understanding';

    try {
      await demonstratePlan(objective, mode);
      if (stopped) return;
      statusBadge.textContent = 'building';
      const responsePromise = fetch('/api/v1/agent/run', {
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

      await demonstrateFiles(objective, mode);
      const response = await responsePromise;
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      if (stopped) return;

      finishMirror(true);
      addReply(data.reply || 'The build work is complete.');
      addReply(`The files are ready, ${developerName()}. You can deploy them now, or I can handle the deployment for you.`);
      objectiveInput.value = '';
      statusBadge.className = 'badge badge-success';
      statusBadge.textContent = 'ready';
    } catch (error) {
      if (error.name !== 'AbortError') {
        finishMirror(false);
        addReply(`I could not finish this work: ${error.message}`);
      }
    } finally {
      controller = null;
      activeRunId = null;
      runButton.disabled = false;
      stopButton.hidden = true;
    }
  }, true);
})();
