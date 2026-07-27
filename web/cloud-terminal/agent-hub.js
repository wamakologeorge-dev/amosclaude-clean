import { apiRequest, selectedBranch, terminalApi } from './api.js';

function textNode(tag, value, className = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value;
  return node;
}

export class TerminalAgentHub {
  constructor({ root, repositoryId, getTerminalContext }) {
    this.root = root;
    this.repositoryId = repositoryId;
    this.getTerminalContext = getTerminalContext;
    this.agents = [];
    this.activeAgent = 'doctor';
    this.busy = false;
    this.renderShell();
  }

  renderShell() {
    this.root.innerHTML = `
      <div class="terminal-agent-head">
        <h3>Amosclaud terminal support hub</h3>
        <p>Doctor, Fixer, Autonomous, and Underground support share the selected cloud workspace and report real evidence or a truthful blocker.</p>
        <span class="terminal-agent-cloud">Cloud control plane</span>
      </div>
      <div class="terminal-agent-selector" data-agent-selector></div>
      <div class="terminal-agent-messages" data-agent-messages aria-live="polite"></div>
      <form class="terminal-agent-form" data-agent-form>
        <textarea data-agent-input maxlength="12000" placeholder="Ask the selected Amosclaud agent to diagnose, repair, build, or verify…" required></textarea>
        <div class="terminal-agent-options">
          <label><input data-agent-terminal-context type="checkbox" checked /> Attach recent output from the active terminal. Likely credentials are redacted by the server.</label>
          <label><input data-agent-allow-changes type="checkbox" /> Authorize verified repository changes for this message.</label>
        </div>
        <div class="terminal-agent-actions">
          <button type="submit" data-agent-send>Send to cloud agent</button>
          <button type="button" class="secondary" data-agent-clear>Clear chat</button>
        </div>
        <div class="terminal-agent-status" data-agent-status>Connecting to the Amosclaud cloud agent hub…</div>
      </form>`;

    this.selector = this.root.querySelector('[data-agent-selector]');
    this.messages = this.root.querySelector('[data-agent-messages]');
    this.form = this.root.querySelector('[data-agent-form]');
    this.input = this.root.querySelector('[data-agent-input]');
    this.attachOutput = this.root.querySelector('[data-agent-terminal-context]');
    this.allowChanges = this.root.querySelector('[data-agent-allow-changes]');
    this.sendButton = this.root.querySelector('[data-agent-send]');
    this.statusNode = this.root.querySelector('[data-agent-status]');

    this.form.addEventListener('submit', event => {
      event.preventDefault();
      this.send(this.input.value);
    });
    this.input.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        this.form.requestSubmit();
      }
    });
    this.root.querySelector('[data-agent-clear]').addEventListener('click', () => {
      this.messages.innerHTML = '';
      this.addMessage('assistant', 'Agent chat cleared. The cloud workspace and terminal sessions remain connected.');
    });
  }

  async load() {
    try {
      const payload = await apiRequest(terminalApi(this.repositoryId, '/agent-hub'));
      this.agents = Array.isArray(payload.agents) ? payload.agents : [];
      this.renderAgents();
      const policy = payload.policy || {};
      this.addMessage(
        'assistant',
        'Cloud agent hub connected. Choose Doctor for diagnosis, Fixer for bounded repairs, Autonomous for complete engineering tasks, or Underground for safe escalation after normal repair fails.',
        [],
        false,
      );
      this.status(
        policy.success_requires_runtime_evidence
          ? 'Connected · runtime evidence required · protected-branch bypass disabled'
          : 'Connected to the Amosclaud cloud agent hub.',
      );
    } catch (error) {
      this.status(`Agent hub unavailable: ${error.message}`);
      this.addMessage('assistant', `Cloud agent hub failed safely: ${error.message}`, [], true);
    }
  }

  renderAgents() {
    this.selector.innerHTML = '';
    this.agents.forEach(agent => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'terminal-agent-choice';
      button.dataset.agent = agent.id;
      button.append(
        textNode('strong', agent.name),
        textNode('span', agent.description),
      );
      button.addEventListener('click', () => this.selectAgent(agent.id));
      this.selector.appendChild(button);
    });
    if (!this.agents.some(agent => agent.id === this.activeAgent)) {
      this.activeAgent = this.agents[0]?.id || 'doctor';
    }
    this.selectAgent(this.activeAgent, { announce: false });
  }

  selectAgent(agentId, { announce = true } = {}) {
    const agent = this.agents.find(item => item.id === agentId);
    if (!agent) return;
    this.activeAgent = agentId;
    this.selector.querySelectorAll('[data-agent]').forEach(button => {
      button.classList.toggle('active', button.dataset.agent === agentId);
    });
    this.allowChanges.disabled = !agent.write_capable;
    if (!agent.write_capable) this.allowChanges.checked = false;
    this.input.placeholder = agent.quick_prompts?.[0] || `Message ${agent.name}…`;
    if (announce) {
      this.status(`${agent.name} selected · ${agent.write_capable ? 'changes require explicit authorization' : 'diagnosis only'}`);
    }
  }

  activeAgentSpec() {
    return this.agents.find(item => item.id === this.activeAgent) || {
      id: this.activeAgent,
      name: 'Amosclaud Agent',
      write_capable: false,
    };
  }

  status(value) {
    this.statusNode.textContent = value;
  }

  setBusy(busy) {
    this.busy = busy;
    this.input.disabled = busy;
    this.sendButton.disabled = busy;
    this.sendButton.textContent = busy ? 'Working in cloud…' : 'Send to cloud agent';
  }

  addMessage(role, message, evidence = [], blocked = false) {
    const article = document.createElement('article');
    article.className = `terminal-agent-message ${role}${blocked ? ' blocked' : ''}`;
    const label = role === 'user' ? 'You' : this.activeAgentSpec().name;
    article.append(textNode('strong', label), textNode('span', message));
    if (Array.isArray(evidence) && evidence.length) {
      const list = document.createElement('ul');
      list.className = 'terminal-agent-evidence';
      evidence.slice(0, 12).forEach(item => list.appendChild(textNode('li', String(item))));
      article.appendChild(list);
    }
    this.messages.appendChild(article);
    this.messages.scrollTop = this.messages.scrollHeight;
  }

  async send(rawMessage) {
    const message = String(rawMessage || '').trim();
    if (!message || this.busy) return;
    const agent = this.activeAgentSpec();
    const terminal = this.getTerminalContext?.() || {};
    const changesAuthorized = Boolean(agent.write_capable && this.allowChanges.checked);
    const terminalOutput = this.attachOutput.checked ? String(terminal.output || '').slice(-12000) : '';

    this.addMessage('user', message);
    this.input.value = '';
    this.setBusy(true);
    this.status(`${agent.name} is using the Amosclaud cloud control plane…`);
    try {
      const payload = await apiRequest(terminalApi(this.repositoryId, '/agent-hub/messages'), {
        method: 'POST',
        body: JSON.stringify({
          agent: agent.id,
          message,
          branch: selectedBranch(),
          terminal_id: terminal.id || null,
          profile: terminal.profile || 'bash',
          allow_changes: changesAuthorized,
          terminal_output: terminalOutput,
        }),
      });
      const blocked = payload.status !== 'completed';
      this.addMessage(
        'assistant',
        payload.reply || 'The cloud agent returned no summary.',
        payload.evidence || [],
        blocked,
      );
      this.status(
        `${agent.name} · ${payload.status || 'unknown'} · ${payload.operation || 'engineering operation'} · ${payload.terminal_context_used ? 'terminal context used' : 'no terminal output attached'}`,
      );
    } catch (error) {
      this.addMessage('assistant', `Cloud agent request failed safely: ${error.message}`, [], true);
      this.status('The last cloud agent request did not complete.');
    } finally {
      this.setBusy(false);
      this.input.focus();
    }
  }
}
