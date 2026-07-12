const feed = document.getElementById('public-feed');
const total = document.getElementById('feed-total');
const success = document.getElementById('feed-success');
const failed = document.getElementById('feed-failed');
const running = document.getElementById('feed-running');

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDate(value) {
  if (!value) return 'In progress';
  try { return new Date(value).toLocaleString(); } catch { return value; }
}

async function loadFeed() {
  try {
    const response = await fetch('/api/v1/feed', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const items = await response.json();

    total.textContent = items.length;
    success.textContent = items.filter(item => item.status === 'success').length;
    failed.textContent = items.filter(item => item.status === 'failed').length;
    running.textContent = items.filter(item => ['running', 'pending'].includes(item.status)).length;

    if (!items.length) {
      feed.innerHTML = '<div class="feed-empty">No public Agent results yet. Completed Agent runs will appear here.</div>';
      return;
    }

    feed.innerHTML = items.map(item => `
      <article class="feed-card">
        <div class="feed-card-top">
          <div>
            <h3>${escapeHtml(item.title)}</h3>
            <div>${escapeHtml(item.summary)}</div>
          </div>
          <span class="feed-status status-${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
        </div>
        <div class="feed-team">${escapeHtml((item.team || []).join(' · '))}</div>
        <div class="feed-meta">
          <span>${escapeHtml(item.agent)}</span>
          <span>Branch: ${escapeHtml(item.branch || 'main')}</span>
          <span>${escapeHtml(formatDate(item.finished_at || item.started_at))}</span>
        </div>
      </article>
    `).join('');
  } catch (error) {
    console.error('[Public feed]', error);
    feed.innerHTML = '<div class="feed-empty">The public feed is temporarily unavailable.</div>';
  }
}

document.getElementById('refresh-feed').addEventListener('click', loadFeed);
loadFeed();
setInterval(loadFeed, 10000);
