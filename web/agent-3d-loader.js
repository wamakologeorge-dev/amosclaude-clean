import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js';

window.THREE = THREE;

try {
  await import('/static/agent-3d.js');
} catch (error) {
  console.error('[Amosclaud 3D] Failed to start the AI workspace model', error);
  const container = document.getElementById('ai-worker-canvas');
  if (container) {
    container.innerHTML = '<div style="display:grid;place-items:center;height:100%;padding:24px;text-align:center;color:#8fb4d7">3D workspace could not start. Refresh the page after deployment finishes.</div>';
  }
}
