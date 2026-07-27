import { apiRequest, selectedBranch, terminalApi } from './api.js';

function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'"'"'`)}'`;
}

function safeRelativePath(value) {
  const path = String(value || '').trim().replace(/\\/g, '/').replace(/^\.\//, '');
  if (!path || path.startsWith('/') || path.split('/').some(part => part === '..')) {
    throw new Error('Use a file path inside this repository.');
  }
  return path;
}

export class ProjectToolbelt {
  constructor({ root, repositoryId, ensureTerminal, isWorkspaceRunning }) {
    this.root = root;
    this.repositoryId = repositoryId;
    this.ensureTerminal = ensureTerminal;
    this.isWorkspaceRunning = isWorkspaceRunning;
    this.payload = null;
    this.busy = false;
    this.renderShell();
  }

  renderShell() {
    this.root.innerHTML = `
      <div class="terminal-project-tools-head">
        <div>
          <h3>Project tools</h3>
          <p>Smart commands, run and debug, file editing, Git status, commit, pull, push, and one-click Sync &amp; Push.</p>
        </div>
        <span class="terminal-project-source" data-project-source>Loading project…</span>
      </div>
      <div class="terminal-project-summary" data-project-summary></div>
      <div class="terminal-project-commands" data-project-commands></div>
      <div class="terminal-project-bottom">
        <div class="terminal-custom-command">
          <input data-project-command type="text" placeholder="Run any command, for example: python -m pytest -q" />
          <button data-project-run type="button">Run command</button>
          <button data-project-run-app class="project" type="button">Run app</button>
          <button data-project-debug class="debug" type="button">Debug</button>
          <button data-project-files type="button">Files</button>
          <button data-project-edit type="button">Edit file</button>
        </div>
        <div class="terminal-project-actions">
          <input data-project-message type="text" maxlength="200" value="Update from Amosclaud cloud terminal" aria-label="Commit message" />
          <button data-project-commit class="primary" type="button">Commit</button>
          <button data-project-sync-push class="sync" type="button" hidden>Sync &amp; Push</button>
          <button data-project-pull class="github" type="button" hidden>Pull</button>
          <button data-project-push class="github" type="button" hidden>Push</button>
          <button data-project-refresh type="button">Refresh</button>
        </div>
      </div>
      <div class="terminal-project-result" data-project-result aria-live="polite">Loading repository tools…</div>`;

    this.source = this.root.querySelector('[data-project-source]');
    this.summary = this.root.querySelector('[data-project-summary]');
    this.commands = this.root.querySelector('[data-project-commands]');
    this.commandInput = this.root.querySelector('[data-project-command]');
    this.messageInput = this.root.querySelector('[data-project-message]');
    this.runButton = this.root.querySelector('[data-project-run]');
    this.runAppButton = this.root.querySelector('[data-project-run-app]');
    this.debugButton = this.root.querySelector('[data-project-debug]');
    this.commitButton = this.root.querySelector('[data-project-commit]');
    this.syncPushButton = this.root.querySelector('[data-project-sync-push]');
    this.pullButton = this.root.querySelector('[data-project-pull]');
    this.pushButton = this.root.querySelector('[data-project-push]');
    this.result = this.root.querySelector('[data-project-result]');

    this.runButton.addEventListener('click', () => this.run(this.commandInput.value));
    this.commandInput.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        this.run(this.commandInput.value);
      }
    });
    this.runAppButton.addEventListener('click', () => this.runDetected('run'));
    this.debugButton.addEventListener('click', () => this.runDetected('debug'));
    this.root.querySelector('[data-project-files]').addEventListener('click', () => {
      this.run("find . -path './.git' -prune -o -type f -maxdepth 4 -print | sort | sed 's#^./##' | head -300");
    });
    this.root.querySelector('[data-project-edit]').addEventListener('click', () => this.editFile());
    this.commitButton.addEventListener('click', () => this.commit());
    this.syncPushButton.addEventListener('click', () => this.sync('sync-push'));
    this.pullButton.addEventListener('click', () => this.sync('pull'));
    this.pushButton.addEventListener('click', () => this.sync('push'));
    this.root.querySelector('[data-project-refresh]').addEventListener('click', () => this.load());
  }

  setBusy(busy) {
    this.busy = busy;
    this.root.querySelectorAll('button').forEach(button => { button.disabled = busy; });
  }

  setResult(message, kind = '') {
    this.result.textContent = message;
    this.result.className = `terminal-project-result${kind ? ` ${kind}` : ''}`;
  }

  async load() {
    try {
      const payload = await apiRequest(terminalApi(this.repositoryId, '/tools'));
      this.payload = payload;
      this.render(payload);
      this.setResult('Project tools are ready.', 'success');
      return payload;
    } catch (error) {
      this.setResult(`Project tools unavailable: ${error.message}`, 'error');
      return null;
    }
  }

  render(payload) {
    const repository = payload.repository || {};
    const status = payload.status || {};
    const source = repository.source || 'amosclaud';
    this.source.className = `terminal-project-source ${source}`;
    this.source.textContent = source === 'github'
      ? `GitHub · ${repository.github_full_name || repository.name}`
      : `Amosclaud · ${repository.name || 'native repository'}`;

    this.summary.innerHTML = '';
    const chips = [
      `Branch: ${status.branch || 'detached'}`,
      `Commit: ${status.head_short || 'none'}`,
      status.dirty ? `${status.changed_files?.length || 0} changed file(s)` : 'Working tree clean',
    ];
    if (Number.isInteger(status.ahead)) chips.push(`Ahead: ${status.ahead}`);
    if (Number.isInteger(status.behind)) chips.push(`Behind: ${status.behind}`);
    chips.forEach((textValue, index) => {
      const chip = document.createElement('span');
      chip.textContent = textValue;
      if (index === 2) chip.className = status.dirty ? 'dirty' : 'clean';
      this.summary.appendChild(chip);
    });

    this.commands.innerHTML = '';
    (payload.commands || []).forEach(tool => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `terminal-project-command ${tool.kind || ''}`;
      button.textContent = tool.label;
      button.title = `${tool.description}\n${tool.command}`;
      button.addEventListener('click', () => this.run(tool.command));
      this.commands.appendChild(button);
    });

    const github = source === 'github';
    this.pullButton.hidden = !github;
    this.pushButton.hidden = !github;
    this.syncPushButton.hidden = !github;
    this.commitButton.textContent = github ? 'Commit' : 'Save commit';
    this.commitButton.title = github
      ? 'Commit changes locally, then push them to GitHub.'
      : 'Commit changes to the Amosclaud-native repository.';
  }

  async terminal() {
    if (!this.isWorkspaceRunning()) throw new Error('Start the cloud workspace first.');
    const session = await this.ensureTerminal();
    if (!session) throw new Error('A terminal session could not be created.');
    return session;
  }

  detectedRunCommand() {
    const commands = this.payload?.commands || [];
    const preferredIds = ['npm-dev', 'npm-start', 'make-dev', 'make-run', 'django'];
    for (const id of preferredIds) {
      const command = commands.find(item => item.id === id)?.command;
      if (command) return command;
    }
    return 'amos run';
  }

  async runDetected(mode) {
    const command = mode === 'debug' ? 'amos debug' : this.detectedRunCommand();
    await this.run(command);
  }

  async run(command) {
    const prepared = String(command || '').trim();
    if (!prepared || this.busy) return;
    this.setBusy(true);
    this.setResult(`Running: ${prepared}`);
    try {
      const session = await this.terminal();
      await session.runCommand(prepared);
      this.commandInput.value = '';
      this.setResult('Command sent to the active cloud terminal.', 'success');
    } catch (error) {
      this.setResult(error.message, 'error');
    } finally {
      this.setBusy(false);
    }
  }

  async editFile() {
    const suggested = window.prompt('File path inside this repository:', 'README.md');
    if (suggested === null) return;
    try {
      const path = safeRelativePath(suggested);
      await this.run(`mkdir -p -- $(dirname -- ${shellQuote(path)}) && nano -- ${shellQuote(path)}`);
    } catch (error) {
      this.setResult(error.message, 'error');
    }
  }

  async commit() {
    if (this.busy) return;
    const message = this.messageInput.value.trim();
    if (!message) {
      this.setResult('Enter a commit message.', 'error');
      this.messageInput.focus();
      return;
    }
    this.setBusy(true);
    this.setResult('Committing the real repository changes…');
    try {
      const payload = await apiRequest(terminalApi(this.repositoryId, '/tools/commit'), {
        method: 'POST',
        body: JSON.stringify({ message, branch: selectedBranch() }),
      });
      this.setResult(payload.message || `Commit ${payload.commit?.slice(0, 12) || ''} created.`, 'success');
      await this.load();
    } catch (error) {
      this.setResult(error.message, 'error');
    } finally {
      this.setBusy(false);
    }
  }

  async sync(action) {
    if (this.busy) return;
    this.setBusy(true);
    const labels = {
      pull: 'Pulling from GitHub…',
      push: 'Pushing to GitHub…',
      'sync-push': 'Synchronizing remote changes, rebasing safely, and pushing to GitHub…',
    };
    this.setResult(labels[action] || 'Synchronizing GitHub…');
    try {
      const payload = await apiRequest(terminalApi(this.repositoryId, `/tools/${action}`), {
        method: 'POST',
        body: JSON.stringify({
          branch: selectedBranch(),
          commit_message: this.messageInput.value.trim() || 'Update from Amosclaud cloud terminal',
        }),
      });
      const verb = action === 'pull' ? 'Pulled' : action === 'push' ? 'Pushed' : 'Synchronized and pushed';
      this.setResult(`${verb} ${payload.branch || selectedBranch()} at ${String(payload.commit || '').slice(0, 12)}.`, 'success');
      await this.load();
    } catch (error) {
      this.setResult(error.message, 'error');
    } finally {
      this.setBusy(false);
    }
  }
}
