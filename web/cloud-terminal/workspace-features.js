import { apiRequest, terminalApi } from './api.js';

function text(value, fallback = 'Unavailable') {
  const normalized = String(value ?? '').trim();
  return normalized || fallback;
}

export class WorkspaceFeatureCells {
  constructor({ root, repositoryId, ensureTerminal, isWorkspaceRunning, focusAgentHub }) {
    this.root = root;
    this.repositoryId = repositoryId;
    this.ensureTerminal = ensureTerminal;
    this.isWorkspaceRunning = isWorkspaceRunning;
    this.focusAgentHub = focusAgentHub;
    this.payload = null;
    this.runtime = null;
    this.renderShell();
  }

  renderShell() {
    this.root.innerHTML = `
      <div class="workspace-feature-cell" data-feature="ports">
        <div class="workspace-feature-icon">⇄</div>
        <div class="workspace-feature-copy">
          <h3>Ports</h3>
          <p data-feature-detail="ports">Start the workspace to inspect local listening ports.</p>
        </div>
        <button data-feature-action="ports" type="button">Scan ports</button>
      </div>
      <div class="workspace-feature-cell" data-feature="problems">
        <div class="workspace-feature-icon">!</div>
        <div class="workspace-feature-copy">
          <h3>Problems</h3>
          <p data-feature-detail="problems">Run repository checks and send failures to Amosclaud Doctor.</p>
        </div>
        <button data-feature-action="problems" type="button">Check problems</button>
      </div>
      <div class="workspace-feature-cell" data-feature="connectors">
        <div class="workspace-feature-icon">⌁</div>
        <div class="workspace-feature-copy">
          <h3>Connectors</h3>
          <p data-feature-detail="connectors">Loading repository and agent connections…</p>
        </div>
        <button data-feature-action="connectors" type="button">Open agents</button>
      </div>
      <div class="workspace-feature-cell" data-feature="network">
        <div class="workspace-feature-icon">◎</div>
        <div class="workspace-feature-copy">
          <h3>Network</h3>
          <p data-feature-detail="network">Loading sandbox network policy…</p>
        </div>
        <button data-feature-action="network" type="button">Diagnose network</button>
      </div>`;

    this.root.querySelectorAll('[data-feature-action]').forEach(button => {
      button.addEventListener('click', () => this.activate(button.dataset.featureAction));
    });
    this.updateAvailability();
  }

  detail(name, value) {
    const node = this.root.querySelector(`[data-feature-detail="${name}"]`);
    if (node) node.textContent = value;
  }

  updateAvailability() {
    const running = this.isWorkspaceRunning();
    this.root.querySelector('[data-feature-action="ports"]').disabled = !running;
    this.root.querySelector('[data-feature-action="problems"]').disabled = !running;
    this.root.querySelector('[data-feature-action="network"]').disabled = !running;
  }

  setRuntime(runtime) {
    this.runtime = runtime || null;
    const network = text(runtime?.network, 'unknown');
    const running = Boolean(runtime?.running);
    this.detail('ports', running
      ? 'Local port discovery is ready. Port forwarding remains governed by the workspace policy.'
      : 'Start the workspace to inspect local listening ports.');
    this.detail('network', running
      ? `Sandbox network mode: ${network}. Diagnose interfaces, routes, DNS, and outbound reachability.`
      : `Workspace network mode: ${network}. Start the workspace to run diagnostics.`);
    this.updateAvailability();
  }

  async load() {
    try {
      this.payload = await apiRequest(terminalApi(this.repositoryId, '/tools'));
      const repository = this.payload.repository || {};
      const source = repository.source === 'github'
        ? `GitHub connected: ${repository.github_full_name || repository.name}`
        : `Amosclaud-native repository: ${repository.name || 'repository'}`;
      this.detail('connectors', `${source}. Doctor, Fixer, Autonomous, and Underground agents are available through the control plane.`);

      const commands = this.payload.commands || [];
      const checkCount = commands.filter(item => ['test', 'lint', 'typecheck', 'build'].some(word => String(item.id).includes(word))).length;
      this.detail('problems', checkCount
        ? `${checkCount} detected verification command${checkCount === 1 ? '' : 's'} plus Git diff validation and Amosclaud Doctor.`
        : 'Git diff validation and Amosclaud Doctor are ready; project-specific checks can be run manually.');
      return this.payload;
    } catch (error) {
      this.detail('connectors', `Connector status unavailable: ${error.message}`);
      return null;
    }
  }

  async terminal() {
    if (!this.isWorkspaceRunning()) throw new Error('Start the cloud workspace first.');
    const session = await this.ensureTerminal();
    if (!session) throw new Error('A terminal session could not be created.');
    return session;
  }

  problemCommand() {
    const commands = this.payload?.commands || [];
    const selected = [];
    for (const item of commands) {
      const id = String(item.id || '');
      if (['lint', 'typecheck', 'test'].some(word => id.includes(word)) && !selected.includes(item.command)) {
        selected.push(item.command);
      }
      if (selected.length >= 3) break;
    }
    const checks = ['git diff --check', ...selected];
    return `printf '\n=== Amosclaud Problems scan ===\n'; ${checks.map(command => `(${command}) || true`).join('; ')}; printf '\nOpen the Doctor cell for diagnosis of any failure above.\n'`;
  }

  commandFor(name) {
    if (name === 'ports') {
      return "printf '\n=== Amosclaud Ports ===\n'; (ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null || lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null || true); printf '\nPorts are local to the isolated workspace unless platform forwarding is enabled.\n'";
    }
    if (name === 'problems') return this.problemCommand();
    if (name === 'network') {
      return "printf '\n=== Amosclaud Network ===\n'; printf 'Interfaces:\n'; (ip -brief address 2>/dev/null || true); printf '\nRoutes:\n'; (ip route 2>/dev/null || true); printf '\nDNS:\n'; (getent hosts github.com 2>/dev/null || true); printf '\nOutbound HTTPS:\n'; (curl -I --max-time 5 https://github.com 2>/dev/null | head -8 || true); printf '\nNetwork access follows the server-managed workspace policy.\n'";
    }
    return '';
  }

  async activate(name) {
    if (name === 'connectors') {
      this.focusAgentHub?.();
      return;
    }
    const command = this.commandFor(name);
    if (!command) return;
    const button = this.root.querySelector(`[data-feature-action="${name}"]`);
    button.disabled = true;
    try {
      const session = await this.terminal();
      await session.runCommand(command);
    } finally {
      button.disabled = !this.isWorkspaceRunning();
    }
  }
}
