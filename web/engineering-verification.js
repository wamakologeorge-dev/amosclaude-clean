const el = (id) => document.getElementById(id);

async function api(url, options = {}) {
  const response = await fetch(url, {credentials: 'same-origin', headers: {'Accept':'application/json'}, ...options});
  if (response.status === 401) { location.href = '/login'; throw new Error('Authentication required'); }
  if (response.status === 403) { location.href = '/cloud/agent'; throw new Error('Administrator access required'); }
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
  return response.json();
}

function renderReport(report) {
  const state = el('verification-state');
  if (!report) {
    state.className = 'state pending'; state.textContent = 'No report';
    el('report-meta').textContent = 'No retained verification report exists for this installation.';
    el('checks').innerHTML = '';
    el('verification-output').textContent = '';
    return;
  }
  const verified = report.status === 'verified';
  state.className = `state ${verified ? 'ready' : 'failed'}`;
  state.textContent = verified ? 'Verified' : 'Failed';
  el('report-meta').textContent = `${report.commit_sha?.slice(0, 12) || 'unknown'} · ${new Date(report.generated_at).toLocaleString()} · ${report.summary?.passed || 0}/${report.summary?.total || 0} passed`;
  el('checks').innerHTML = (report.checks || []).map((check) => `<article><b>${check.status === 'passed' ? '✓' : '×'}</b><span><strong>${check.name}</strong><small>${check.status} · ${check.duration_seconds}s</small></span></article>`).join('');
  el('verification-output').textContent = (report.checks || []).map((check) => `# ${check.name} [${check.status}]\n${check.output || 'No output'}`).join('\n\n');
}

function renderMerges(items) {
  el('merges').innerHTML = items.map((item) => {
    const pr = item.pull_request ? `PR #${item.pull_request}` : item.short_sha;
    const status = item.verification_status === 'verified' ? 'Verified' : item.verification_status === 'failed' ? 'Failed' : 'Historical — no retained report';
    return `<tr><td><strong>${pr}</strong><br><small>${item.title}</small></td><td>${status}</td><td>${item.files_changed}</td><td>${item.merged_at ? new Date(item.merged_at).toLocaleString() : 'Unknown'}</td></tr>`;
  }).join('') || '<tr><td colspan="4">No Git history available in this installation.</td></tr>';
}

async function load() {
  el('error').hidden = true;
  try {
    const [reports, merges] = await Promise.all([
      api('/api/v1/admin/engineering-verification/reports?limit=1'),
      api('/api/v1/admin/merge-results?limit=150'),
    ]);
    renderReport(reports[0] || null);
    renderMerges(merges);
  } catch (error) {
    el('error').hidden = false; el('error').textContent = error.message;
  }
}

el('run').addEventListener('click', async () => {
  el('run').disabled = true;
  el('verification-state').className = 'state pending';
  el('verification-state').textContent = 'Running';
  try {
    const report = await api('/api/v1/admin/engineering-verification/run', {method: 'POST'});
    renderReport(report);
    await load();
  } catch (error) {
    el('error').hidden = false; el('error').textContent = error.message;
  } finally {
    el('run').disabled = false;
  }
});
el('refresh').addEventListener('click', load);
load();
