'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '..');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const mainSource = fs.readFileSync(path.join(root, 'main.js'), 'utf8');
const preloadSource = fs.readFileSync(path.join(root, 'preload.js'), 'utf8');
const providerHtml = fs.readFileSync(path.join(root, 'provider.html'), 'utf8');

test('packages the secure Desktop gateway setup window', () => {
  assert.equal(manifest.main, 'main.js');
  for (const file of ['provider-config.js', 'provider.html', 'provider.css', 'provider.js']) {
    assert.ok(manifest.build.files.includes(file));
  }
  assert.match(manifest.scripts.check, /node --check provider-config\.js/);
  assert.match(mainSource, /safeStorage/);
  assert.match(mainSource, /Gateway provider setup/);
  assert.match(mainSource, /autoHideMenuBar: false/);
  assert.match(mainSource, /SUPPORTED_GATEWAY_PATHS/);
  assert.match(preloadSource, /testConnection/);
  assert.match(providerHtml, /Save securely/);
  assert.match(providerHtml, /Content-Security-Policy/);
});
