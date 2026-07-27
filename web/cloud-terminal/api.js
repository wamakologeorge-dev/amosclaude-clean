export function repositoryIdFromLocation() {
  const parts = location.pathname.split('/').filter(Boolean);
  const repositoryId = parts.length === 2 && parts[0] === 'workspace' ? parts[1] : '';
  return /^\d+$/.test(repositoryId) ? repositoryId : '';
}

export function selectedBranch() {
  return document.getElementById('ws-branch')?.value || 'main';
}

export async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch (_error) {
    payload = { detail: text };
  }
  if (response.status === 401) {
    location.assign('/login');
    throw new Error('Sign in to continue.');
  }
  if (!response.ok) {
    throw new Error(payload?.detail || payload?.message || `Request failed (${response.status})`);
  }
  return payload || {};
}

export function terminalApi(repositoryId, suffix = '') {
  return `/api/v1/cloud-workspaces/repositories/${encodeURIComponent(repositoryId)}${suffix}`;
}
