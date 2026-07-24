const $ = (id) => document.getElementById(id);
const pretty = (key) => key.replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase());
const bytes = (value) => { const units=['B','KB','MB','GB','TB']; let n=Number(value||0),i=0; while(n>=1024&&i<units.length-1){n/=1024;i++;} return `${n.toFixed(i?1:0)} ${units[i]}`; };

function renderList(id, data) {
  $(id).innerHTML = Object.entries(data || {}).map(([key, value]) => `<div><dt>${pretty(key)}</dt><dd>${typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value)}</dd></div>`).join('');
}

async function json(url) {
  const response = await fetch(url, {credentials: 'same-origin', headers: {'Accept':'application/json'}});
  if (response.status === 401) { location.href = '/login'; throw new Error('Authentication required'); }
  if (response.status === 403) { location.href = '/cloud/agent'; throw new Error('Administrator access required'); }
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
  return response.json();
}

async function load() {
  $('system-state').className = 'state pending'; $('system-state').textContent = 'Connecting'; $('error').hidden = true;
  try {
    const [overview, readiness, core] = await Promise.all([
      json('/api/v1/admin/overview'),
      json('/api/v1/agent/readiness?test_model=false'),
      json('/api/v1/core/status').catch(() => ({})),
    ]);
    const identity = {
      Product: 'Amosclaud', Runtime: 'Amosclaud.py', Edition: 'Community',
      Status: overview.status || 'operational', Agent: readiness.agent || 'Amosclaud Agent',
      Language: 'Amo Runtime'
    };
    $('identity').innerHTML = Object.entries(identity).map(([k,v]) => `<article><span>${k}</span><strong>${v}</strong></article>`).join('');
    renderList('runtime', {status: overview.status, generated_at: overview.generated_at, access_mode: core.access_mode || 'local', execution_engine: core.model_runtime || 'local'});
    renderList('agent', {status: readiness.status, agent: readiness.agent, provider: readiness.provider, model: readiness.model});
    renderList('network', {domain: location.hostname, protocol: location.protocol.replace(':',''), origin: location.origin, access_mode: core.access_mode || 'local'});
    renderList('storage', {repository_storage: bytes(overview.repository_storage_bytes), database: bytes(overview.database_bytes), repositories: overview.repositories, deployments: overview.deployments});
    const counts = {users:overview.users, administrators:overview.administrators, sessions:overview.active_sessions, repositories:overview.repositories, pipelines:overview.pipelines, deployments:overview.deployments, messages:overview.mail_messages, posts:overview.community_posts};
    $('workspace-counts').innerHTML = Object.entries(counts).map(([k,v]) => `<article><span>${pretty(k)}</span><strong>${v ?? 0}</strong></article>`).join('');
    const caps = ['Folder-first workspace','Local autonomous agent','Amo Runtime','Repository hosting','Pipelines','Deployments','Encrypted Vault','Amosclaud tokens','Local model','Optional GitHub adapter'];
    $('capabilities').innerHTML = caps.map((x) => `<article><b>✓</b><span>${x}</span></article>`).join('');
    $('configuration').innerHTML = ['Secrets redacted','Administrator protected','Same-origin API','No raw environment values'].map((x)=>`<span>${x}</span>`).join('');
    $('generated-at').textContent = new Date(overview.generated_at || Date.now()).toLocaleString();
    $('system-state').className = 'state ready'; $('system-state').textContent = 'Operational';
  } catch (error) {
    $('system-state').textContent = 'Unavailable'; $('error').hidden = false; $('error').textContent = error.message;
  }
}
$('refresh').addEventListener('click', load); load();
