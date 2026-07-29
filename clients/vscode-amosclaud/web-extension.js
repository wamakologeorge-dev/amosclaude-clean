'use strict';

const vscode = require('vscode');

const TOKEN_KEY = 'amosclaud.autonomousToken';
const MAX_SELECTION_CHARS = 16000;
const SENSITIVE_NAMES = new Set([
  '.env',
  'id_rsa',
  'id_ed25519',
  'credentials',
  'credentials.json',
  'secrets.json',
]);
const SENSITIVE_SUFFIXES = new Set(['.key', '.pem', '.p12', '.pfx']);

function configuration() {
  const config = vscode.workspace.getConfiguration('amosclaud');
  return {
    baseUrl: config.get('baseUrl', 'https://www.amosclaud.com'),
    repository: config.get('repository', ''),
    branch: config.get('branch', 'main'),
  };
}

function normalizeBaseUrl(value) {
  const candidate = String(value || 'https://www.amosclaud.com').trim().replace(/\/+$/, '');
  let parsed;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error('Amosclaud URL is invalid');
  }
  const secureRemote = parsed.protocol === 'https:' && Boolean(parsed.hostname);
  const localDevelopment =
    parsed.protocol === 'http:' &&
    ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname);
  if (!secureRemote && !localDevelopment) {
    throw new Error('Amosclaud URL must use HTTPS, except for exact localhost development hosts');
  }
  return candidate;
}

function normalizeRelativePath(value) {
  if (!value) return undefined;
  const normalized = String(value).replaceAll('\\', '/').replace(/^\.\//, '');
  if (normalized.startsWith('/') || normalized.split('/').includes('..')) {
    throw new Error("Editor paths must be repository-relative and cannot contain '..'");
  }
  return normalized;
}

function extensionName(value) {
  const name = String(value || '').split('/').at(-1) || '';
  const index = name.lastIndexOf('.');
  return index > 0 ? name.slice(index).toLowerCase() : '';
}

function isSensitivePath(value) {
  if (!value) return false;
  const normalized = String(value).toLowerCase().replaceAll('\\', '/');
  const parts = normalized.split('/');
  const name = parts.at(-1) || '';
  return (
    SENSITIVE_NAMES.has(name) ||
    name.startsWith('.env.') ||
    SENSITIVE_SUFFIXES.has(extensionName(name)) ||
    parts.includes('secrets') ||
    parts.includes('.secrets')
  );
}

function activeEditorContext(source) {
  const editor = vscode.window.activeTextEditor;
  const config = configuration();
  const context = {
    branch: String(config.branch || 'main').trim() || 'main',
    source,
  };
  if (config.repository) context.repository = String(config.repository).trim();
  if (!editor) return context;

  const document = editor.document;
  let filePath = vscode.workspace.asRelativePath(document.uri, false);
  if (!filePath || filePath === document.uri.toString()) {
    filePath = document.uri.path.split('/').filter(Boolean).at(-1);
  }
  const safeFilePath = normalizeRelativePath(filePath);
  if (isSensitivePath(safeFilePath)) {
    throw new Error('Sensitive files cannot be sent to Amosclaud as editor context');
  }
  if (safeFilePath) context.file_path = safeFilePath;
  if (document.languageId) context.language = String(document.languageId).slice(0, 64);
  if (!editor.selection.isEmpty) {
    context.selection = document.getText(editor.selection).slice(0, MAX_SELECTION_CHARS);
  }
  return context;
}

function buildPayload(task, context, requestedAgent) {
  const cleanTask = String(task || '').trim();
  if (!cleanTask) throw new Error('A task is required');
  if (cleanTask.length > 12000) throw new Error('Tasks are limited to 12000 characters');
  const payload = { task: cleanTask, context };
  if (requestedAgent) payload.requested_agent = requestedAgent;
  return payload;
}

async function requestJson({ baseUrl, pathname, method = 'GET', token, payload }) {
  const headers = { Accept: 'application/json' };
  if (payload !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${normalizeBaseUrl(baseUrl)}${pathname}`, {
    method,
    headers,
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const text = await response.text();
  let body;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`Amosclaud returned a non-JSON response (${response.status})`);
  }
  if (!response.ok) {
    const detail = body.detail || body.error || text || `HTTP ${response.status}`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return body;
}

async function configureToken(context) {
  const token = await vscode.window.showInputBox({
    title: 'Amosclaud Autonomous token',
    prompt: 'Stored in VS Code Secret Storage. It is never written to the repository.',
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
  return requestJson({
    baseUrl: config.baseUrl,
    pathname: `/api/v1/copilot/${action}`,
    method: 'POST',
    token,
    payload: buildPayload(task, activeEditorContext(source), requestedAgent || undefined),
  });
}

async function listAgents() {
  const config = configuration();
  return requestJson({
    baseUrl: config.baseUrl,
    pathname: '/api/v1/copilot/agents',
  });
}

function asMarkdownJson(value) {
  return `\n\n\`\`\`json\n${JSON.stringify(value, null, 2).replaceAll('```', '` ` `')}\n\`\`\``;
}

function commandRouting(command) {
  const normalized = String(command || 'plan').toLowerCase();
  const routes = {
    plan: { action: 'plan' },
    run: { action: 'run' },
    fix: { action: 'run', agent: 'amosclaud-fixer' },
    build: { action: 'run', agent: 'amosclaud-action' },
    deploy: { action: 'run', agent: 'amosclaud-autonomous' },
    security: { action: 'plan', agent: 'amosclaud-security' },
  };
  return routes[normalized] || routes.plan;
}

async function handleChatRequest(context, request, _chatContext, stream, cancellationToken) {
  try {
    const command = String(request.command || 'plan').toLowerCase();
    if (command === 'agents') {
      stream.progress('Loading Amosclaud capabilities...');
      const agents = await listAgents();
      if (!cancellationToken.isCancellationRequested) {
        stream.markdown('### Amosclaud internal capabilities');
        stream.markdown(asMarkdownJson(agents));
      }
      return { metadata: { command } };
    }
    if (command === 'status') {
      stream.progress('Checking Amosclaud...');
      const config = configuration();
      const [health, readiness] = await Promise.all([
        requestJson({ baseUrl: config.baseUrl, pathname: '/health' }),
        requestJson({ baseUrl: config.baseUrl, pathname: '/ready' }),
      ]);
      if (!cancellationToken.isCancellationRequested) {
        stream.markdown('### Amosclaud status');
        stream.markdown(asMarkdownJson({ health, readiness }));
      }
      return { metadata: { command } };
    }

    const routing = commandRouting(command);
    stream.progress(
      routing.action === 'run'
        ? 'Starting governed Amosclaud work...'
        : 'Preparing an Amosclaud execution plan...',
    );
    const result = await callCopilot(
      context,
      routing.action,
      request.prompt,
      routing.agent,
      `vscode-chat-participant-${command}`,
    );
    if (!cancellationToken.isCancellationRequested) {
      stream.markdown(
        routing.action === 'run'
          ? '### Amosclaud Autonomous run'
          : '### Amosclaud Autonomous plan',
      );
      stream.markdown(asMarkdownJson(result));
    }
    return { metadata: { command, action: routing.action } };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    stream.markdown(`### Amosclaud could not continue\n\n${message}`);
    stream.button({ command: 'amosclaud.configureToken', title: 'Configure Amosclaud token' });
    return { metadata: { error: message } };
  }
}

async function promptAndCall(context, action) {
  const task = await vscode.window.showInputBox({
    title: action === 'run' ? 'Run with Amosclaud Autonomous' : 'Plan with Amosclaud Autonomous',
    prompt: 'Only bounded editor context and explicitly selected text are sent.',
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
      const response = await listAgents();
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
  <p class="hint">Use this independent panel or type <strong>@amosclaud</strong> in VS Code Chat.</p>
  <label for="agent">Capability preference</label>
  <select id="agent"><option value="">Automatic routing</option></select>
  <label for="task">What should Amosclaud do?</label>
  <textarea id="task" placeholder="Explain, fix, build, test, deploy, or prepare a verified change..."></textarea>
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

  if (vscode.chat && typeof vscode.chat.createChatParticipant === 'function') {
    const participant = vscode.chat.createChatParticipant(
      'amosclaud-autonomous.amosclaud',
      (request, chatContext, stream, token) =>
        handleChatRequest(context, request, chatContext, stream, token),
    );
    participant.iconPath = vscode.Uri.joinPath(context.extensionUri, 'media', 'amosclaud.svg');
    context.subscriptions.push(participant);
  }
}

function deactivate() {}

module.exports = {
  activate,
  deactivate,
  commandRouting,
  isSensitivePath,
  normalizeBaseUrl,
  normalizeRelativePath,
};
