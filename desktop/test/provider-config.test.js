'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const {
  DEFAULT_AMOSCLAUD_URL,
  DEFAULT_MODEL,
  apiBaseUrl,
  gatewayUrl,
  maskedKeyPrefix,
  normalizeApiKey,
  normalizeBaseUrl,
  normalizeProviderConfig,
  publicProviderConfig,
} = require('../provider-config');

test('normalizes hosted and loopback gateway URLs', () => {
  assert.equal(normalizeBaseUrl(DEFAULT_AMOSCLAUD_URL), DEFAULT_AMOSCLAUD_URL);
  assert.equal(normalizeBaseUrl('https://www.amosclaud.com/v1/'), DEFAULT_AMOSCLAUD_URL);
  assert.equal(normalizeBaseUrl('https://example.com/api/v1'), 'https://example.com/api');
  assert.equal(normalizeBaseUrl('http://localhost:8000/'), 'http://localhost:8000');
  assert.equal(apiBaseUrl('http://127.0.0.1:8000/v1'), 'http://127.0.0.1:8000/v1');
  assert.throws(() => normalizeBaseUrl('http://example.com'), /must use HTTPS/);
  assert.throws(() => normalizeBaseUrl('https://user:pass@example.com'), /credentials/);
  assert.throws(() => normalizeBaseUrl('https://example.com/?redirect=elsewhere'), /query/);
});

test('normalizes a provider config without returning its secret in public state', () => {
  const config = normalizeProviderConfig({
    baseUrl: 'https://www.amosclaud.com/',
    model: DEFAULT_MODEL,
    apiKey: 'amos_aut_example_secret',
  });
  assert.equal(config.apiBaseUrl, 'https://www.amosclaud.com/v1');
  assert.equal(maskedKeyPrefix(config.apiKey), 'amos_aut_••••');
  const publicConfig = publicProviderConfig(config, 'secure-storage');
  assert.equal(publicConfig.apiKeyConfigured, true);
  assert.equal(publicConfig.apiKeyPrefix, 'amos_aut_••••');
  assert.doesNotMatch(JSON.stringify(publicConfig), /example_secret/);
});

test('rejects unsafe or malformed keys and models', () => {
  assert.equal(normalizeApiKey('', { required: false }), '');
  assert.throws(() => normalizeApiKey('amos bad'), /invalid/);
  assert.throws(() => normalizeProviderConfig({ model: 'model name', apiKey: 'secret-key' }), /whitespace/);
  assert.throws(() => normalizeProviderConfig({ model: DEFAULT_MODEL, apiKey: '' }), /required/);
});

test('restricts Desktop requests to the supported Amosclaud gateway contract', () => {
  assert.equal(
    gatewayUrl('https://www.amosclaud.com', '/v1/models'),
    'https://www.amosclaud.com/v1/models',
  );
  assert.equal(
    gatewayUrl('https://www.amosclaud.com/v1', '/v1/responses'),
    'https://www.amosclaud.com/v1/responses',
  );
  assert.throws(() => gatewayUrl('https://www.amosclaud.com', '/v1/unknown'), /only permits/);
});
