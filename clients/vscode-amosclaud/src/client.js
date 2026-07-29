'use strict';

const path = require('node:path');

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

function isSensitivePath(value) {
  if (!value) return false;
  const normalized = String(value).toLowerCase().replaceAll('\\', '/');
  const parts = normalized.split('/');
  const name = parts.at(-1) || '';
  const extension = path.posix.extname(name);
  return (
    SENSITIVE_NAMES.has(name) ||
    name.startsWith('.env.') ||
    SENSITIVE_SUFFIXES.has(extension) ||
    parts.includes('secrets') ||
    parts.includes('.secrets')
  );
}

function buildEditorContext({ repository, branch, filePath, language, selection, source }) {
  const safeFilePath = normalizeRelativePath(filePath);
  if (isSensitivePath(safeFilePath)) {
    throw new Error('Sensitive files cannot be sent to Amosclaud as editor context');
  }
  const context = {
    branch: String(branch || 'main').trim() || 'main',
    source: source || 'vscode-amosclaud',
  };
  if (repository) context.repository = String(repository).trim();
  if (safeFilePath) context.file_path = safeFilePath;
  if (language) context.language = String(language).slice(0, 64);
  if (selection) context.selection = String(selection).slice(0, MAX_SELECTION_CHARS);
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
  const headers = {
    Accept: 'application/json',
    'User-Agent': 'amosclaud-vscode/0.1',
  };
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

module.exports = {
  MAX_SELECTION_CHARS,
  buildEditorContext,
  buildPayload,
  isSensitivePath,
  normalizeBaseUrl,
  normalizeRelativePath,
  requestJson,
};
