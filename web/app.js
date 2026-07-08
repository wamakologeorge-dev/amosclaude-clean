/**
 * Amosclaud-AI Web App
 * app.js — UI logic, chat engine, browser controller
 */

/* ═══════════════════════════════════════════════════════════════════════════
   Config & State
   ═══════════════════════════════════════════════════════════════════════════ */

const DEFAULT_API = window.location.origin; // same host when served by Flask

const state = {
  apiUrl: localStorage.getItem('apiUrl') || DEFAULT_API,
  sessionId: localStorage.getItem('sessionId') || null,
  darkMode: localStorage.getItem('darkMode') === 'true',
  messageCount: 0,
};

/* ═══════════════════════════════════════════════════════════════════════════
   DOM Helpers
   ═══════════════════════════════════════════════════════════════════════════ */

const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

function showToast(message, type = 'info', duration = 3500) {
  const container = $('#toast-container');
  const toast = document.createElement('div');
  toast.className = `toast toast--${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), duration);
}

function setLoading(visible) {
  $('#loading-overlay').classList.toggle('hidden', !visible);
}

/* ═══════════════════════════════════════════════════════════════════════════
   Tab Navigation
   ═══════════════════════════════════════════════════════════════════════════ */

function activateTab(tabId) {
  $$('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.tab === tabId));
  $$('.tab').forEach(tab => tab.classList.toggle('active', tab.id === `tab-${tabId}`));

  if (tabId === 'dashboard') loadDashboard();
}

$$('.nav-item').forEach(item => {
  item.addEventListener('click', () => activateTab(item.dataset.tab));
});

/* ═══════════════════════════════════════════════════════════════════════════
   Chat
   ═══════════════════════════════════════════════════════════════════════════ */

const chatMessages = $('#chat-messages');
const chatInput = $('#chat-input');
const btnSend = $('#btn-send');

/** Auto-grow textarea */
chatInput.addEventListener('input', () => {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + 'px';
  btnSend.disabled = chatInput.value.trim().length === 0;
});

/** Send on Enter (Shift+Enter = new line) */
chatInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (!btnSend.disabled) sendMessage();
  }
});

btnSend.addEventListener('click', sendMessage);

/** Quick-action chips */
chatMessages.addEventListener('click', e => {
  const chip = e.target.closest('.chip');
  if (chip) {
    chatInput.value = chip.dataset.prompt;
    chatInput.dispatchEvent(new Event('input'));
    sendMessage();
  }
});

/** New chat button */
$('#btn-new-chat').addEventListener('click', () => {
  state.sessionId = null;
  localStorage.removeItem('sessionId');
  chatMessages.innerHTML = '';
  state.messageCount = 0;
  appendWelcome();
  showToast('New conversation started', 'info');
});

/** Clear button */
$('#btn-clear-chat').addEventListener('click', async () => {
  if (state.sessionId) {
    await fetch(`${state.apiUrl}/api/chat/history/${state.sessionId}`, { method: 'DELETE' });
  }
  chatMessages.innerHTML = '';
  state.sessionId = null;
  state.messageCount = 0;
  localStorage.removeItem('sessionId');
  appendWelcome();
});

/** Export button */
$('#btn-export-chat').addEventListener('click', () => {
  const messages = $$('.message', chatMessages);
  const lines = messages.map(msg => {
    const role = msg.classList.contains('message--user') ? 'You' : 'Amosclaud-AI';
    const text = msg.querySelector('.message-bubble')?.innerText || '';
    return `[${role}]\n${text}\n`;
  });
  const blob = new Blob([lines.join('\n---\n\n')], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `amosclaud-ai-chat-${Date.now()}.txt`;
  a.click();
});

function appendWelcome() {
  const welcome = document.createElement('div');
  welcome.className = 'message message--assistant';
  welcome.id = 'msg-welcome';
  welcome.innerHTML = `
    <div class="message-avatar">🤖</div>
    <div class="message-bubble">
      <p>Hello! I'm <strong>Amosclaud-AI</strong> — your intelligent CI/CD &amp; DevOps automation assistant.</p>
      <p>How can I help you today?</p>
      <div class="quick-actions">
        <button class="chip" data-prompt="Deploy my app to production">Deploy app</button>
        <button class="chip" data-prompt="Run tests for my project">Run tests</button>
        <button class="chip" data-prompt="Analyse my code for issues">Analyse code</button>
        <button class="chip" data-prompt="Help me with database migration">DB migration</button>
      </div>
    </div>`;
  chatMessages.appendChild(welcome);
}

function appendMessage(role, content) {
  const div = document.createElement('div');
  div.className = `message message--${role}`;

  const avatarContent = role === 'user' ? '👤' : '🤖';
  div.innerHTML = `
    <div class="message-avatar">${avatarContent}</div>
    <div class="message-bubble">${formatContent(content)}</div>`;

  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

function appendTypingIndicator() {
  const div = document.createElement('div');
  div.className = 'message message--assistant';
  div.id = 'typing-indicator';
  div.innerHTML = `
    <div class="message-avatar">🤖</div>
    <div class="message-bubble typing-indicator">
      <span class="dot"></span><span class="dot"></span><span class="dot"></span>
    </div>`;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

/** Lightweight markdown → HTML (bold, italic, inline code, code blocks, lists, links) */
function formatContent(text) {
  if (!text) return '';

  // Placeholders to protect code from HTML escaping
  const codeBlocks = [];
  const inlineCodes = [];

  // Extract fenced code blocks first
  text = text.replace(/```[\w]*\n?([\s\S]*?)```/g, (_, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push(`<pre><code>${escapeHtml(code.trim())}</code></pre>`);
    return `\x00CODE_BLOCK_${idx}\x00`;
  });

  // Extract inline code
  text = text.replace(/`([^`]+)`/g, (_, code) => {
    const idx = inlineCodes.length;
    inlineCodes.push(`<code>${escapeHtml(code)}</code>`);
    return `\x00INLINE_${idx}\x00`;
  });

  // Escape all remaining HTML entities (prevents XSS from user/API text)
  text = escapeHtml(text);

  // Bold (operate on escaped text, markers are plain ASCII)
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  // Italic
  text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');

  // Safe URLs — only allow http(s) schemes to prevent javascript: XSS
  text = text.replace(/(https?:\/\/[^\s&lt;&gt;&quot;]+)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');

  // Bullet lists
  text = text.replace(/^[•\-\*] (.+)$/gm, '<li>$1</li>');
  text = text.replace(/(<li>.*<\/li>(\n|$))+/g, m => `<ul>${m}</ul>`);

  // Numbered lists
  text = text.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

  // Paragraphs
  text = text.split('\n\n').map(p => p.trim()).filter(Boolean).map(p => {
    if (p.startsWith('\x00CODE_BLOCK') || p.startsWith('<ul>') || p.startsWith('<li>')) return p;
    return `<p>${p.replace(/\n/g, '<br />')}</p>`;
  }).join('');

  // Restore placeholders
  codeBlocks.forEach((block, i) => { text = text.replace(`\x00CODE_BLOCK_${i}\x00`, block); });
  inlineCodes.forEach((code, i)  => { text = text.replace(`\x00INLINE_${i}\x00`, code); });

  return text;
}

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function sendMessage() {
  const message = chatInput.value.trim();
  if (!message) return;

  chatInput.value = '';
  chatInput.style.height = 'auto';
  btnSend.disabled = true;

  // Remove welcome message if still visible
  $('#msg-welcome')?.remove();

  appendMessage('user', message);
  state.messageCount++;

  const typing = appendTypingIndicator();

  try {
    const res = await fetch(`${state.apiUrl}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, session_id: state.sessionId }),
    });

    typing.remove();

    if (!res.ok) throw new Error(`Server error ${res.status}`);

    const data = await res.json();
    state.sessionId = data.session_id;
    localStorage.setItem('sessionId', state.sessionId);

    appendMessage('assistant', data.reply);
    state.messageCount++;

    // Update chat counter in dashboard
    const statChats = $('#stat-chats');
    if (statChats) statChats.textContent = Math.ceil(state.messageCount / 2);

  } catch (err) {
    typing.remove();
    appendMessage('assistant',
      '⚠️ I couldn\'t reach the backend right now. Please check your connection or the API URL in Settings.');
    showToast('Failed to connect to API', 'error');
    console.error('[Chat error]', err);
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   Browser Tab
   ═══════════════════════════════════════════════════════════════════════════ */

const browserFrame = $('#browser-frame');
const browserUrl = $('#browser-url');
const browserOverlay = $('#browser-overlay');
const overlayLink = $('#overlay-link');

const iframeHistory = [browserUrl.value];
let iframeIndex = 0;

/**
 * Validate a URL and return it only if it uses an allowed scheme (http/https).
 * Falls back to Google homepage for any disallowed or unparseable URL.
 */
function sanitizeUrl(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol === 'https:' || parsed.protocol === 'http:') {
      return parsed.href;
    }
  } catch { /* fall through */ }
  return 'https://www.google.com';
}

function navigateTo(url) {
  let safeUrl = url.trim();

  if (!/^https?:\/\//i.test(safeUrl)) {
    // Treat as a search query
    safeUrl = 'https://www.google.com/search?q=' + encodeURIComponent(safeUrl);
  }

  // Validate through URL parsing — rejects javascript:, data:, and any other unsafe scheme
  const verifiedUrl = sanitizeUrl(safeUrl);

  browserUrl.value = verifiedUrl;
  browserOverlay.classList.add('hidden');
  browserFrame.src = verifiedUrl;
  overlayLink.setAttribute('href', verifiedUrl);

  // Trim forward history
  iframeHistory.splice(iframeIndex + 1);
  iframeHistory.push(verifiedUrl);
  iframeIndex = iframeHistory.length - 1;
}

$('#browser-go').addEventListener('click', () => navigateTo(browserUrl.value));
browserUrl.addEventListener('keydown', e => { if (e.key === 'Enter') navigateTo(browserUrl.value); });
$('#browser-home').addEventListener('click', () => navigateTo('https://www.google.com'));
$('#browser-back').addEventListener('click', () => {
  if (iframeIndex > 0) { iframeIndex--; navigateTo(iframeHistory[iframeIndex]); }
});
$('#browser-forward').addEventListener('click', () => {
  if (iframeIndex < iframeHistory.length - 1) { iframeIndex++; navigateTo(iframeHistory[iframeIndex]); }
});
$('#browser-refresh').addEventListener('click', () => {
  navigateTo(browserUrl.value);
});

// Bookmarks
$$('.bookmark').forEach(btn => {
  btn.addEventListener('click', () => navigateTo(btn.dataset.url));
});

// Show overlay if frame blocks embedding
browserFrame.addEventListener('load', () => {
  try {
    // Cross-origin access check — throws if X-Frame-Options/CSP blocks embedding
    const accessCheck = browserFrame.contentWindow.location.href;
    if (accessCheck) browserOverlay.classList.add('hidden');
  } catch {
    // Cannot access; the site blocks embedding
    browserOverlay.classList.remove('hidden');
  }
});

/* ═══════════════════════════════════════════════════════════════════════════
   Dashboard
   ═══════════════════════════════════════════════════════════════════════════ */

async function loadDashboard() {
  try {
    const res = await fetch(`${state.apiUrl}/api/capabilities`);
    if (!res.ok) return;
    const data = await res.json();

    const grid = $('#capabilities-list');
    grid.innerHTML = '';
    data.capabilities.forEach(cap => {
      const span = document.createElement('span');
      span.className = 'capability-chip';
      span.textContent = cap.replace(/_/g, ' ');
      grid.appendChild(span);
    });

    $('#about-backend-version').textContent = data.version || '—';
  } catch { /* silently ignore */ }

  // Simulated stats (replace with real API calls if available)
  animateStat('#stat-deployments', 14);
  animateStat('#stat-tests', 127);
  animateStat('#stat-db', 8);
  const statChats = $('#stat-chats');
  if (statChats && statChats.textContent === '—') statChats.textContent = '0';
}

function animateStat(selector, target) {
  const el = $(selector);
  if (!el || el.textContent !== '—') return;
  let current = 0;
  const step = Math.ceil(target / 30);
  const timer = setInterval(() => {
    current = Math.min(current + step, target);
    el.textContent = current;
    if (current >= target) clearInterval(timer);
  }, 30);
}

/* ═══════════════════════════════════════════════════════════════════════════
   Settings
   ═══════════════════════════════════════════════════════════════════════════ */

const settingApiUrl = $('#setting-api-url');
const settingDarkMode = $('#setting-dark-mode');

settingApiUrl.value = state.apiUrl;
settingDarkMode.checked = state.darkMode;

settingApiUrl.addEventListener('change', () => {
  state.apiUrl = settingApiUrl.value.replace(/\/$/, '') || DEFAULT_API;
  localStorage.setItem('apiUrl', state.apiUrl);
});

settingDarkMode.addEventListener('change', () => {
  state.darkMode = settingDarkMode.checked;
  localStorage.setItem('darkMode', state.darkMode);
  document.body.classList.toggle('dark', state.darkMode);
});

$('#btn-test-connection').addEventListener('click', async () => {
  const status = $('#connection-status');
  status.textContent = 'Testing…';
  status.className = 'status-text';
  try {
    const res = await fetch(`${state.apiUrl}/health`);
    const data = await res.json();
    status.textContent = `✅ Connected — ${data.service} v${data.version}`;
    status.className = 'status-text ok';
  } catch {
    status.textContent = '❌ Cannot reach the backend. Check the URL.';
    status.className = 'status-text err';
  }
});

/* ═══════════════════════════════════════════════════════════════════════════
   Initialise
   ═══════════════════════════════════════════════════════════════════════════ */

function init() {
  // Apply dark mode preference
  if (state.darkMode) document.body.classList.add('dark');

  // Activate default tab (chat)
  activateTab('chat');
}

init();
