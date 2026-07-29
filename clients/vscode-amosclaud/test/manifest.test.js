'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '..');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const chatSource = fs.readFileSync(path.join(root, 'web-extension.js'), 'utf8');
const terminalSource = fs.readFileSync(path.join(root, 'src', 'terminal.js'), 'utf8');
const browserEntry = fs.readFileSync(path.join(root, 'src', 'browser-entry.js'), 'utf8');

test('extension builds one desktop and browser bundle', () => {
  assert.equal(manifest.main, './dist/web-extension.js');
  assert.equal(manifest.browser, './dist/web-extension.js');
  assert.equal(manifest.capabilities.virtualWorkspaces.supported, true);
  assert.match(manifest.scripts.build, /esbuild/);
});

test('extension registers one Amosclaud chat participant', () => {
  assert.equal(manifest.contributes.chatParticipants.length, 1);
  const participant = manifest.contributes.chatParticipants[0];
  assert.equal(participant.id, 'amosclaud-autonomous.amosclaud');
  assert.equal(participant.name, 'amosclaud');
  assert.ok(participant.commands.some((command) => command.name === 'run'));
  assert.ok(participant.commands.some((command) => command.name === 'agents'));
  assert.match(chatSource, /createChatParticipant/);
});

test('extension contributes the Amosclaud self terminal', () => {
  const profiles = manifest.contributes.terminal.profiles;
  assert.equal(profiles.length, 1);
  assert.equal(profiles[0].id, 'amosclaud-autonomous.self-terminal');
  assert.ok(manifest.activationEvents.includes('onTerminalProfile:amosclaud-autonomous.self-terminal'));
  assert.ok(manifest.contributes.commands.some((command) => command.command === 'amosclaud.openTerminal'));
  assert.match(terminalSource, /registerTerminalProfileProvider/);
  assert.match(terminalSource, /Pseudoterminal/);
  assert.match(terminalSource, /vscode-terminal\/repositories/);
});

test('browser bundle entry combines chat and terminal activation', () => {
  assert.match(browserEntry, /baseExtension\.activate/);
  assert.match(browserEntry, /registerTerminal/);
  assert.doesNotMatch(terminalSource, /require\('node:/);
});
