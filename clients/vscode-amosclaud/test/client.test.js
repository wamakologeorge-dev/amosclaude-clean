'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  MAX_SELECTION_CHARS,
  buildEditorContext,
  buildPayload,
  isSensitivePath,
  normalizeBaseUrl,
  normalizeRelativePath,
} = require('../src/client');

test('normalizes secure platform and exact localhost URLs', () => {
  assert.equal(normalizeBaseUrl('https://www.amosclaud.com/'), 'https://www.amosclaud.com');
  assert.equal(normalizeBaseUrl('http://localhost:8000/'), 'http://localhost:8000');
  assert.equal(normalizeBaseUrl('http://127.0.0.1:8000/'), 'http://127.0.0.1:8000');
  assert.throws(() => normalizeBaseUrl('http://example.com'), /must use HTTPS/);
  assert.throws(() => normalizeBaseUrl('http://localhost.example.com'), /must use HTTPS/);
});

test('rejects absolute and escaping editor paths', () => {
  assert.equal(normalizeRelativePath('src/main.js'), 'src/main.js');
  assert.throws(() => normalizeRelativePath('../secret.txt'), /repository-relative/);
  assert.throws(() => normalizeRelativePath('/tmp/file.js'), /repository-relative/);
});

test('blocks sensitive paths', () => {
  assert.equal(isSensitivePath('.env'), true);
  assert.equal(isSensitivePath('config/.env.production'), true);
  assert.equal(isSensitivePath('certs/server.pem'), true);
  assert.equal(isSensitivePath('secrets/provider.json'), true);
  assert.throws(
    () => buildEditorContext({ filePath: '.env', selection: 'TOKEN=value' }),
    /Sensitive files/,
  );
});

test('bounds selected text and preserves explicit routing preference', () => {
  const context = buildEditorContext({
    repository: 'wamakologeorge-dev/amosclaude-clean',
    branch: 'feature/test',
    filePath: 'src/index.js',
    language: 'javascript',
    selection: 'x'.repeat(MAX_SELECTION_CHARS + 20),
    source: 'test',
  });
  assert.equal(context.selection.length, MAX_SELECTION_CHARS);
  const payload = buildPayload('Fix this code', context, 'amosclaud-fixer');
  assert.equal(payload.requested_agent, 'amosclaud-fixer');
  assert.equal(payload.context.file_path, 'src/index.js');
});

test('rejects empty tasks', () => {
  assert.throws(() => buildPayload('   ', {}, undefined), /task is required/i);
});
