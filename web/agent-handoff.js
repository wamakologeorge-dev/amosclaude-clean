(() => {
  const runButton = document.getElementById('btn-run-agent');
  const objectiveInput = document.getElementById('agent-objective-input');
  const replies = document.getElementById('agent-replies');
  if (!runButton || !objectiveInput || !replies) return;

  let activeSequence = 0;
  const greetingWords = new Set(['hi', 'hello', 'hey', 'hiya', 'yo', 'good morning', 'good afternoon', 'good evening']);

  function normalize(value) {
    return String(value || '').trim().toLowerCase().replace(/[.!?]+$/, '').replace(/\s+/g, ' ');
  }

  function addHandoffMessage(agent, message, state = 'active') {
    if (replies.querySelector('.agent-reply.muted')) replies.innerHTML = '';

    const item = document.createElement('div');
    item.className = `agent-reply agent-handoff agent-handoff--${state}`;

    const header = document.createElement('div');
    header.className = 'agent-handoff-header';

    const dot = document.createElement('span');
    dot.className = 'agent-handoff-dot';

    const name = document.createElement('strong');
    name.textContent = agent;

    const status = document.createElement('span');
    status.className = 'agent-handoff-status';
    status.textContent = state === 'done' ? 'completed' : state === 'waiting' ? 'standing by' : 'working';

    const body = document.createElement('div');
    body.className = 'agent-handoff-body';
    body.textContent = message;

    header.append(dot, name, status);
    item.append(header, body);
    replies.prepend(item);
    replies.scrollTop = 0;
    return item;
  }

  function markDone(item) {
    if (!item) return;
    item.classList.remove('agent-handoff--active', 'agent-handoff--waiting');
    item.classList.add('agent-handoff--done');
    const status = item.querySelector('.agent-handoff-status');
    if (status) status.textContent = 'completed';
  }

  function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  async function runHandoffSequence(sequenceId, objective) {
    const main = addHandoffMessage(
      'Amosclaud Agent',
      `Wait, let me go check the GitHub repository for “${objective}”. Keep watching this chat while I’m gone.`,
      'active',
    );

    await delay(900);
    if (sequenceId !== activeSequence) return;
    markDone(main);

    const scout = addHandoffMessage(
      'GitHub Scout',
      'Amosclaud Agent is checking the repository. I’m taking over here and keeping the work moving.',
      'active',
    );

    await delay(1000);
    if (sequenceId !== activeSequence) return;
    markDone(scout);

    const builder = addHandoffMessage(
      'Builder AI',
      'I have the task now. I’m preparing the code changes and project structure.',
      'active',
    );

    await delay(1100);
    if (sequenceId !== activeSequence) return;
    markDone(builder);

    const tester = addHandoffMessage(
      'Tester AI',
      'Builder handed the work to me. I’m checking code health, tests, and likely failures.',
      'active',
    );

    await delay(1100);
    if (sequenceId !== activeSequence) return;
    markDone(tester);

    addHandoffMessage(
      'Reviewer AI',
      'I’m reviewing the combined work. The main Amosclaud Agent will return here with the final result.',
      'waiting',
    );
  }

  runButton.addEventListener('click', () => {
    const objective = objectiveInput.value.trim();
    const normalized = normalize(objective);

    activeSequence += 1;
    const sequenceId = activeSequence;

    if (!objective || greetingWords.has(normalized) || ['build', 'make', 'create'].includes(normalized)) {
      return;
    }

    runHandoffSequence(sequenceId, objective);
  }, true);
})();
