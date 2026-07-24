(() => {
  const replies = document.getElementById('agent-replies');
  if (!replies) return;

  function row(label, value) {
    const tr = document.createElement('tr');
    const th = document.createElement('th');
    const td = document.createElement('td');
    th.scope = 'row';
    th.textContent = label;
    td.textContent = value == null || value === '' ? '—' : String(value);
    tr.append(th, td);
    return tr;
  }

  function renderBundleResult(data) {
    if (data?.kind !== 'bundle' || !data.bundle) return;
    const manifest = data.bundle;
    const card = document.createElement('article');
    card.className = 'agent-reply autonomous-result-card';
    card.setAttribute('data-autonomous-real-result', manifest.bundle_id || 'bundle');

    const heading = document.createElement('h3');
    heading.textContent = 'Autonomous result';
    const state = document.createElement('p');
    state.className = 'autonomous-result-state';
    state.textContent = 'Verified real bundle record';

    const table = document.createElement('table');
    table.className = 'autonomous-result-table';
    table.append(
      row('Name', manifest.name),
      row('Type', manifest.bundle_type),
      row('Version', manifest.version),
      row('Bundle ID', manifest.bundle_id),
      row('Format', manifest.format),
      row('Source', manifest.source_root),
      row('Entrypoint', manifest.entrypoint),
      row('Files', Array.isArray(manifest.files) ? manifest.files.length : 0),
      row('Source bytes', manifest.source_bytes),
      row('Archive bytes', data.archive_size),
      row('Archive SHA-256', manifest.archive_sha256),
      row('Created', manifest.created_at),
    );

    const filesHeading = document.createElement('h4');
    filesHeading.textContent = 'Included files';
    const files = document.createElement('div');
    files.className = 'autonomous-result-files';
    (Array.isArray(manifest.files) ? manifest.files : []).slice(0, 100).forEach(item => {
      const line = document.createElement('code');
      line.textContent = `${item.path} — ${item.size} bytes — ${item.sha256}`;
      files.appendChild(line);
    });

    const download = document.createElement('a');
    download.className = 'btn-primary autonomous-result-download';
    download.href = data.download_url;
    download.textContent = 'Download verified .amosbundle';
    download.setAttribute('download', '');

    card.append(heading, state, table, filesHeading, files, download);
    replies.appendChild(card);
    replies.scrollTop = replies.scrollHeight;
  }

  window.addEventListener('amosclaud:agent-result', event => renderBundleResult(event.detail || {}));
})();
