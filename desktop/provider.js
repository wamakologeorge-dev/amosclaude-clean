'use strict';

const desktop = window.amosclaudDesktop;
const form = document.querySelector('#provider-form');
const baseUrl = document.querySelector('#base-url');
const model = document.querySelector('#model');
const apiKey = document.querySelector('#api-key');
const testButton = document.querySelector('#test');
const saveButton = document.querySelector('#save');
const clearButton = document.querySelector('#clear');
const status = document.querySelector('#status');

let currentConfig;

function setStatus(message, kind = '') {
  status.textContent = message;
  status.className = `status ${kind}`.trim();
}

function formConfig() {
  return {
    baseUrl: baseUrl.value.trim(),
    model: model.value.trim(),
    apiKey: apiKey.value.trim(),
  };
}

function setBusy(value) {
  testButton.disabled = value;
  saveButton.disabled = value;
  clearButton.disabled = value;
}

function describeModels(models) {
  if (!models.length) return 'The gateway responded, but did not advertise any models.';
  return `Available models: ${models.join(', ')}`;
}

async function loadConfig() {
  if (!desktop || !desktop.provider) {
    setStatus('Desktop provider controls are unavailable.', 'error');
    return;
  }
  try {
    currentConfig = await desktop.provider.getConfig();
    baseUrl.value = currentConfig.baseUrl;
    model.value = currentConfig.model;
    const keyState = currentConfig.apiKeyConfigured
      ? `Saved key: ${currentConfig.apiKeyPrefix}`
      : 'No key is saved yet.';
    setStatus(`${keyState}\nSelect Test connection to verify the gateway.`, '');
  } catch (error) {
    setStatus(error.message || 'Could not load provider settings.', 'error');
  }
}

testButton.addEventListener('click', async () => {
  setBusy(true);
  setStatus('Testing the Amosclaud gateway…');
  try {
    const result = await desktop.provider.testConnection(formConfig());
    setStatus(`Connected (${result.status}) at ${result.apiBaseUrl}.\n${describeModels(result.models)}`, 'success');
  } catch (error) {
    setStatus(error.message || 'Gateway test failed.', 'error');
  } finally {
    setBusy(false);
  }
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  setBusy(true);
  setStatus('Saving the provider configuration in OS secure storage…');
  try {
    currentConfig = await desktop.provider.saveConfig(formConfig());
    apiKey.value = '';
    setStatus(
      `Saved securely. Provider: ${currentConfig.apiBaseUrl}\nKey: ${currentConfig.apiKeyPrefix}`,
      'success',
    );
  } catch (error) {
    setStatus(error.message || 'Could not save provider settings.', 'error');
  } finally {
    setBusy(false);
  }
});

clearButton.addEventListener('click', async () => {
  if (!window.confirm('Clear the saved Amosclaud provider configuration?')) return;
  setBusy(true);
  try {
    currentConfig = await desktop.provider.clearConfig();
    apiKey.value = '';
    baseUrl.value = currentConfig.baseUrl;
    model.value = currentConfig.model;
    const message = currentConfig.apiKeyConfigured
      ? 'The saved key was cleared. An environment-provided key is still active.'
      : 'Saved provider configuration cleared.';
    setStatus(message, 'success');
  } catch (error) {
    setStatus(error.message || 'Could not clear provider settings.', 'error');
  } finally {
    setBusy(false);
  }
});

loadConfig();
