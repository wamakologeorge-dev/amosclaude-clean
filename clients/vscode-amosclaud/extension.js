'use strict';

const path = require('node:path');
const vscode = require('vscode');
const {
  buildEditorContext,
  buildPayload,
  requestJson,
} = require('./src/client');

const TOKEN_KEY = 'amosclaud.autonomousToken';

function configuration() {
  const config = vscode.workspace.getConfiguration('amosclaud');
  return {
    baseUrl: config.get('baseUrl', 'https://www.amosclaud.com'),
    repository: config.get('repository', ''),
    branch: config.get('branch', 'main'),
  };
}

function activeEditorContext(source) {
  const editor = vscode.window.activeTextEditor;
  const config = configuration();
  if (!editor) {
    return buildEditorContext({
      repository: config.repository,
      branch: config.branch,
      source,
    });
  }

  const document = editor.document;
  const folder = vscode.workspace.getWorkspaceFolder(document.uri);
  const filePath = folder
    ? path.relative(folder.uri.fsPath, document.uri.fsPath)
    : path.basename(document.uri.fsPath);
  const selection = editor.selection.isEmpty
    ? undefined
    : document.getText(editor.selection);

  return buildEditorContext({
    repository: config.repository,
    branch: config.branch,
    filePath,
    language: document.languageId,
    selection,
    source,
  });
}

async function configureToken(context) {
  const token = await vscode.window.showInputBox({
    title: 'Amosclaud Autonomous token',
    prompt: 'The token is stored in VS Code Secret Storage and is never written to settings.json.',
    password: true,
    ignoreFocusOut: true,
  });
  if (token === undefined) return false;
  if (!token.trim()) {
    await context.secrets.delete(TOKEN_KEY);
    vscode.window.showInformationMessage('Amosclaud token removed.');
    return false;
  }
  await context.secrets.store(TOKEN_KEY, token.trim());
  vscode.window.showInformationMessage('Amosclaud token stored securely.');
  return true;
}

async function tokenOrConfigure(context) {
  let token = await context.secrets.get(TOKEN_KEY);
  if (!token) {
    const stored = await configureToken(context);
    if (!stored) throw new Error('A valid Amosclaud token is required');
    token = await context.secrets.get(TOKEN_KEY);
  }
  return token;
}

async function callCopilot(context, action, task, requestedAgent, source) {
  const token = await tokenOrConfigure(context);
  const config = configuration();
  const editorContext = activeEditorContext(source);
  const payload = buildPayload(task, editorContext, requestedAgent || undefined);
  return requestJson({
    baseUrl: config.baseUrl,
    pathname: `/api/v1/copilot/${action}`,
    method: 'POST',
    token,
    payload,
  });
}

async function promptAndCall(context, action) {
  const task = await vscode.window.showInputBox({
    title: action === 'run' ? 'Run with Amosclaud Autonomous' : 'Plan with Amosclaud Autonomous',
    prompt: 'Only the active repository, relative file path, language, and selected text are sent.',
    ignoreFocusOut: true,
  });
  if (!task) return;
  const result = await callCopilot(
    context,
    action,
    task,
    undefined,
    `vscode-command-${action}`,
  );
  const channel = vscode.window.createOutputChannel('Amosclaud Autonomous');
  channel.clear();
  channel.appendLine(JSON.stringify(result, null, 2));
  channel.show(true);
}

class AmosclaudChatViewProvider {
  constructor(context) {
    this.context = context;
    this.view = undefined;
  }

  resolveWebviewView(webviewView) {
    this.view = webviewView;
    webviewView.webview.options = { enableScripts: true };
    webviewView.webview.html = this.html();
    webviewView.webview.onDidReceiveMessage(
      async (message) => {
        try {
          if (message.type === 'ready') {
            await this.sendAgents();
            return;
          }
          if (message.type === 'configureToken') {
            await configureToken(this.context);
            return;
          }
          if (message.type === 'submit') {
            webviewView.webview.postMessage({ type: 'busy', value: true });
            const result = await callCopilot(
              this.context,
              message.action === 'run' ? 'run' : 'plan',
              message.task,
              message.agent || undefined,
              'vscode-chat-panel',
            );
            webviewView.webview.postMessage({ type: 'result', result });
          }
        } catch (error) {
          webviewView.webview.postMessage({
            type: 'error',
            message: error instanceof Error ? error.message : String(error),
          });
        } finally {
          webviewView.webview.postMessage({ type: 'busy', value: false });
        }
      },
      undefined,
      this.context.subscriptions,
    );
  }

  async sendAgents() {
    if (!this.view) return;
    try {
      const config = configuration();
      const response = await requestJson({
        baseUrl: config.baseUrl,
        pathname: '/api/v1/copilot/agents',
      });
      const agents = Array.isArray(response.agents)
        ? response.agents.map((agent) => ({
            value: String(agent.name || ''),
            label: String(agent.title || agent.name || 'Internal capability'),
          }))
        : [];
      this.view.webview.postMessage({ type: 'agents', agents });
    } catch (error) {
      this.view.webview.postMessage({
        type: 'error',
        message: error instanceof Error ? error.message : String(error),
      });
    }
  }

  html() {
    return `<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 10px; }
  textarea, select, button { width: 100%; box-sizing: border-box; margin: 6px 0; }
  textarea { min-height: 110px; resize: vertical; color: var(--vscode-input-foreground); background: var(--vscode-input-background); border: 1px solid var(--vscode-input-border); padding: 8px; }
  select { color: var(--vscode-dropdown-foreground); background: var(--vscode-dropdown-background); border: 1px solid var(--vscode-dropdown-border); padding: 6px; }
  button { border: 0; padding: 8px; color: var(--vscode-button-foreground); background: var(--vscode-button-background); cursor: pointer; }
  button.secondary { color: var(--vscode-button-secondaryForeground); background: var(--vscode-button-secondaryBackground); }
  button:disabled { opacity: .6; cursor: wait; }
  pre { white-space: pre-wrap; overflow-wrap: anywhere; background: var(--vscode-textCodeBlock-background); padding: 8px; }
  .hint { opacity: .8; font-size: .9em; }
</style>
</head>
<body>
  <h3>Amosclaud Autonomous</h3>
  <p class="hint">One governed assistant. Internal capability roles help route the task.</p>
  <label for="agent">Capability preference</label>
  <select id="agent"><option value="">Automatic routing</option></select>
  <label for="task">What should Amosclaud do?</label>
  <textarea id="task" placeholder="Explain, fix, build, test, or prepare a verified change..."></textarea>
  <button id="plan">Plan safely</button>
  <button id="run">Run authorized work</button>
  <button id="token" class="secondary">Configure token</button>
  <pre id="result">Ready.</pre>
<script>
  const vscode = acquireVsCodeApi();
  const task = document.getElementById('task');
  const agent = document.getElementById('agent');
  const result = document.getElementById('result');
  const buttons = [...document.querySelectorAll('button')];
  document.getElementById('plan').addEventListener('click', () => submit('plan'));
  document.getElementById('run').addEventListener('click', () => submit('run'));
  document.getElementById('token').addEventListener('click', () => vscode.postMessage({ type: 'configureToken' }));
  function submit(action) {
    if (!task.value.trim()) return;
    vscode.postMessage({ type: 'submit', action, task: task.value, agent: agent.value });
  }
  window.addEventListener('message', (event) => {
    const message = event.data;
    if (message.type === 'agents') {
      for (const item of message.agents) {
        const option = document.createElement('option');
        option.value = item.value;
        option.textContent = item.label;
        agent.appendChild(option);
      }
    } else if (message.type === 'result') {
      result.textContent = JSON.stringify(message.result, null, 2);
    } else if (message.type === 'error') {
      result.textContent = 'Error: ' + message.message;
    } else if (message.type === 'busy') {
      buttons.forEach((button) => { button.disabled = Boolean(message.value); });
    }
  });
  vscode.postMessage({ type: 'ready' });
</script>
</body>
</html>`;
  }
}

function activate(context) {
  const provider = new AmosclaudChatViewProvider(context);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider('amosclaud.chatView', provider),
    vscode.commands.registerCommand('amosclaud.configureToken', () => configureToken(context)),
    vscode.commands.registerCommand('amosclaud.planTask', () => promptAndCall(context, 'plan')),
    vscode.commands.registerCommand('amosclaud.runTask', () => promptAndCall(context, 'run')),
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
