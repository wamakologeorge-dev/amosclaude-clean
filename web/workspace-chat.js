(() => {
  const repositoryId = location.pathname.split('/').filter(Boolean).pop();
  const form = document.getElementById('ws-chat-form');
  const input = document.getElementById('ws-chat-input');
  const messages = document.getElementById('ws-chat-messages');
  const sendButton = document.getElementById('ws-chat-send');
  const clearButton = document.getElementById('ws-chat-clear');
  const state = document.getElementById('ws-chat-state');
  if (!form || !input || !messages || !/^\d+$/.test(repositoryId || '')) return;

  const storageKey = `amosclaud-repository-chat-${repositoryId}`;
  const chatTimeoutMs = 57000;
  const retryDelayMs = 750;
  let sessionId = sessionStorage.getItem(storageKey) || '';

  function repositoryName() {
    return document.getElementById('ws-repo-name')?.textContent?.trim() || `repository ${repositoryId}`;
  }

  function branchName() {
    return document.getElementById('ws-branch')?.value || 'main';
  }

  function addMessage(role, text) {
    const article = document.createElement('article');
    article.className = `ws-chat-message ${role}`;
    const label = document.createElement('strong');
    label.textContent = role === 'user' ? 'You' : 'Amosclaud';
    const body = document.createElement('p');
    body.textContent = text;
    article.append(label, body);
    messages.appendChild(article);
    messages.scrollTop = messages.scrollHeight;
  }

  function setBusy(busy) {
    input.disabled = busy;
    sendButton.disabled = busy;
    sendButton.textContent = busy ? 'Sending…' : 'Send';
  }

  function wait(milliseconds) {
    return new Promise(resolve => setTimeout(resolve, milliseconds));
  }

  async function requestChat(payload) {
    let lastError;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), chatTimeoutMs);
      try {
        return await fetch('/api/chat', {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
      } catch (error) {
        lastError = error;
        if (error?.name === 'AbortError') {
          throw new Error('Chat request timed out before the Amosclaud service answered.');
        }
        if (attempt === 0) await wait(retryDelayMs);
      } finally {
        clearTimeout(timeout);
      }
    }
    throw lastError || new Error('Chat service request failed.');
  }

  async function sendMessage(rawMessage) {
    const message = rawMessage.trim();
    if (!message) return;
    addMessage('user', message);
    input.value = '';
    setBusy(true);
    state.textContent = `Talking with Amosclaud about ${repositoryName()} on ${branchName()}…`;
    try {
      const contextualMessage = [
        `Repository context: ${repositoryName()}`,
        `Repository ID: ${repositoryId}`,
        `Selected branch: ${branchName()}`,
        '',
        message,
      ].join('\n');
      const response = await requestChat({
        message: contextualMessage,
        session_id: sessionId || null,
        base_branch: branchName(),
      });
      if (response.status === 401) {
        location.assign('/login');
        return;
      }
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || data.message || `Chat failed (${response.status})`);
      sessionId = data.session_id || sessionId;
      if (sessionId) sessionStorage.setItem(storageKey, sessionId);
      addMessage('assistant', data.reply || 'Amosclaud did not return a reply.');
      state.textContent = `${repositoryName()} · ${branchName()} · ${data.provider || 'Amosclaud'}`;
    } catch (error) {
      const detail = error instanceof TypeError
        ? 'The website loaded, but /api/chat could not be reached. Check the active deployment and /health endpoint.'
        : error.message;
      addMessage('assistant', `Chat failed safely: ${detail}`);
      state.textContent = 'Chat is available, but the last request failed.';
    } finally {
      setBusy(false);
      input.focus();
    }
  }

  function activateWorkspaceTab(name) {
    const tab = document.querySelector(`.ws-tab[data-tab="${name}"]`);
    if (!tab) return;
    tab.click();
    history.replaceState(null, '', `${location.pathname}${location.search}#${name}`);
    document.querySelector(`.ws-panel[data-panel="${name}"]`)?.scrollIntoView({ block: 'start' });
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    sendMessage(input.value);
  });

  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  document.querySelectorAll('[data-chat-prompt]').forEach(button => {
    button.addEventListener('click', () => sendMessage(button.dataset.chatPrompt || ''));
  });

  document.querySelectorAll('[data-open-workspace-tab]').forEach(button => {
    button.addEventListener('click', () => activateWorkspaceTab(button.dataset.openWorkspaceTab));
  });

  document.querySelectorAll('[data-open-tab]').forEach(button => {
    button.addEventListener('click', () => {
      activateWorkspaceTab(button.dataset.openTab);
      document.getElementById('account-drawer')?.setAttribute('hidden', '');
      document.getElementById('account-drawer-backdrop')?.setAttribute('hidden', '');
    });
  });

  clearButton?.addEventListener('click', async () => {
    if (sessionId) {
      await fetch(`/api/chat/history/${encodeURIComponent(sessionId)}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      }).catch(() => undefined);
    }
    sessionId = '';
    sessionStorage.removeItem(storageKey);
    messages.innerHTML = '';
    addMessage('assistant', 'Chat cleared. Ask me what you want to inspect, change, test, or deploy in this repository.');
    state.textContent = `${repositoryName()} · ${branchName()}`;
  });

  const requestedTab = location.hash.replace(/^#/, '');
  if (requestedTab === 'chat' || requestedTab === 'autonomous') {
    queueMicrotask(() => activateWorkspaceTab(requestedTab));
  }
})();
