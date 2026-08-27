'use strict';

const DEFAULT_AMOSCLAUD_URL = 'https://www.amosclaud.com';
const DEFAULT_MODEL = 'amosclaud-agent';
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', '::1']);
const SUPPORTED_GATEWAY_PATHS = new Set([
  '/v1/models',
  '/v1/chat/completions',
  '/v1/responses',
]);

function normalizeBaseUrl(value) {
  let candidate = String(value || DEFAULT_AMOSCLAUD_URL).trim();
  if (!candidate) throw new Error('Amosclaud URL is required');
  if (!candidate.includes('://')) candidate = `https://${candidate}`;
  candidate = candidate.replace(/\/+$/, '');

  let parsed;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error('Amosclaud URL is invalid');
  }

  const isSecureRemote = parsed.protocol === 'https:' && Boolean(parsed.hostname);
  const isLoopbackDevelopment =
    parsed.protocol === 'http:' && LOOPBACK_HOSTS.has(parsed.hostname);
  if (!isSecureRemote && !isLoopbackDevelopment) {
    throw new Error('Amosclaud URL must use HTTPS, except for exact localhost development hosts');
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error('Amosclaud URL cannot contain credentials, a query, or a fragment');
  }

  let pathname = parsed.pathname.replace(/\/+$/, '');
  if (pathname === '/v1' || pathname.endsWith('/v1')) pathname = pathname.slice(0, -3);
  return `${parsed.protocol}//${parsed.host}${pathname}`;
}

function apiBaseUrl(value) {
  return `${normalizeBaseUrl(value)}/v1`;
}

function normalizeModel(value) {
  const model = String(value || DEFAULT_MODEL).trim();
  if (!model) throw new Error('An Amosclaud model is required');
  if (model.length > 100 || /[\u0000-\u001f\u007f\s]/.test(model)) {
    throw new Error('Amosclaud model names must be 1-100 characters without whitespace');
  }
  return model;
}

function normalizeApiKey(value, { required = true } = {}) {
  const apiKey = String(value || '').trim();
  if (!apiKey && !required) return '';
  if (!apiKey) throw new Error('An Amosclaud API key is required for gateway requests');
  if (apiKey.length > 500 || /[\u0000-\u001f\u007f\s]/.test(apiKey)) {
    throw new Error('The Amosclaud API key is invalid');
  }
  return apiKey;
}

function normalizeProviderConfig(input = {}, { allowMissingKey = false } = {}) {
  const baseUrl = normalizeBaseUrl(input.baseUrl);
  const model = normalizeModel(input.model);
  const apiKey = normalizeApiKey(input.apiKey, { required: !allowMissingKey });
  return {
    baseUrl,
    apiBaseUrl: `${baseUrl}/v1`,
    model,
    apiKey,
  };
}

function gatewayUrl(baseUrl, pathname) {
  if (!SUPPORTED_GATEWAY_PATHS.has(pathname)) {
    throw new Error('This Desktop gateway only permits supported Amosclaud API paths');
  }
  return `${apiBaseUrl(baseUrl)}${pathname.slice('/v1'.length)}`;
}

function maskedKeyPrefix(apiKey) {
  const value = String(apiKey || '');
  const knownPrefix = /^(amos_(?:aut|live|test)_)/.exec(value);
  return knownPrefix ? `${knownPrefix[1]}••••` : value ? 'configured••••' : '';
}

function publicProviderConfig(config, source = 'defaults') {
  const normalized = normalizeProviderConfig(config, { allowMissingKey: true });
  return {
    providerId: 'amosclaud',
    baseUrl: normalized.baseUrl,
    apiBaseUrl: normalized.apiBaseUrl,
    model: normalized.model,
    apiKeyConfigured: Boolean(normalized.apiKey),
    apiKeyPrefix: maskedKeyPrefix(normalized.apiKey),
    source,
    capabilities: {
      chatCompletions: true,
      responses: true,
      streaming: false,
    },
  };
}

module.exports = {
  DEFAULT_AMOSCLAUD_URL,
  DEFAULT_MODEL,
  SUPPORTED_GATEWAY_PATHS,
  apiBaseUrl,
  gatewayUrl,
  maskedKeyPrefix,
  normalizeApiKey,
  normalizeBaseUrl,
  normalizeModel,
  normalizeProviderConfig,
  publicProviderConfig,
};
