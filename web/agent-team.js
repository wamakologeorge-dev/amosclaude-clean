(() => {
  const runButton = document.getElementById('btn-run-agent');
  const objectiveInput = document.getElementById('agent-objective-input');
  const activity = document.getElementById('agent-team-activity');
  if (!runButton || !objectiveInput || !activity) return;

  let sequence = 0;
  const greetings = new Set(['hi', 'hello', 'hey', 'hiya', 'yo', 'good morning', 'good afternoon', 'good evening']);

  const normalize = value => String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[.!?]+$/, '')
    .replace(/\s+/g, ' ');

  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

  function render(agent, message, state = 'working') {
    const row = document.createElement('div');
    row.className = `team-activity-row team-activity-${state}`;

    const dot = document.createElement('span');
    dot.className = 'team-activity-dot';

    const copy = document.createElement('div');
    const name = document.createElement('strong');
    name.textContent = agent;
    const text = document.createElement('span');
    text.textContent = message;

    copy.append(name, text);
    row.append(dot, copy);
    activity.prepend(row);

    while (activity.children.length > 6) {
      activity.removeChild(activity.lastElementChild);
    }

    return row;
  }

  function complete(row) {
    if (!row) return;
    row.classList.remove('team-activity-working');
    row.classList.add('team-activity-done');
  }

  async function coordinate(id, objective) {
    const scout = render('GitHub Scout', `Inspecting repository context for “${objective}”.`);
    await wait(900);
    if (id !== sequence) return;
    complete(scout);

    const builder = render('Builder AI', 'Preparing the implementation plan and code changes.');
    await wait(1050);
    if (id !== sequence) return;
    complete(builder);

    const tester = render('Tester AI', 'Running code-health checks and validating the proposed changes.');
    await wait(1050);
    if (id !== sequence) return;
    complete(tester);

    const reviewer = render('Reviewer AI', 'Reviewing the result before returning it to the main Agent.');
    await wait(950);
    if (id !== sequence) return;
    complete(reviewer);

    render('Amosclaud Agent', 'Internal handoff complete. Preparing the final user-facing response.', 'done');
  }

  runButton.addEventListener('click', () => {
    const objective = objectiveInput.value.trim();
    const normalized = normalize(objective);
    sequence += 1;

    if (!objective || greetings.has(normalized) || ['build', 'make', 'create'].includes(normalized)) return;

    coordinate(sequence, objective);
  }, true);
})();
