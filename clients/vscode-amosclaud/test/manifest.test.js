'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '..');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const source = fs.readFileSync(path.join(root, 'web-extension.js'), 'utf8');

test('extension has desktop and browser entry points', () => {
  assert.equal(manifest.main, './web-extension.js');
  assert.equal(manifest.browser, './web-extension.js');
  assert.equal(manifest.capabilities.virtualWorkspaces.supported, true);
});

test('extension registers one Amosclaud chat participant', () => {
  assert.equal(manifest.contributes.chatParticipants.length, 1);
  const participant = manifest.contributes.chatParticipants[0];
  assert.equal(participant.id, 'amosclaud-autonomous.amosclaud');
  assert.equal(participant.name, 'amosclaud');
  assert.ok(participant.commands.some((command) => command.name === 'run'));
  assert.ok(participant.commands.some((command) => command.name === 'agents'));
});

test('web entry point uses browser-safe module loading', () => {
  assert.match(source, /require\('vscode'\)/);
  assert.doesNotMatch(source, /require\('node:/);
  assert.doesNotMatch(source, /require\('\.\//);
  assert.match(source, /createChatParticipant/);
});
