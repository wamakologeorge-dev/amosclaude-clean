const feed = document.getElementById('public-feed');
const total = document.getElementById('feed-total');
const success = document.getElementById('feed-success');
const failed = document.getElementById('feed-failed');
const running = document.getElementById('feed-running');

const reviewKindLabels = {
  comment: 'Comment',
  solution: 'Solution',
  feedback: 'Feedback',
  error: 'Code error',
  suggestion: 'Suggestion',
  approval: 'Approval',
};

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

async function request(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers: {
      ...(options.body ? {'Content-Type': 'application/json'} : {}),
      ...(options.headers || {})
    }
  });
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = {detail: text}; }
  if (!response.ok) throw new Error(data?.detail || `Request failed (${response.status})`);
  return data;
}

function renderLogs(item) {
  const logs = item.recent_logs || [];
  if (!logs.length) return '<div class="feed-no-logs">No detailed logs were recorded.</div>';
  return `<details class="feed-logs"><summary>Build, test, and review logs</summary><pre>${logs.map(escapeHtml).join('\n')}</pre></details>`;
}

function hasUnsavedReview() {
  return [...document.querySelectorAll('[data-review-form]')].some(form => {
    const data = new FormData(form);
    return String(data.get('body') || '').trim() || String(data.get('file_path') || '').trim() || String(data.get('line_number') || '').trim();
  });
}

async function loadReviews(pipelineId) {
  const container = document.querySelector(`[data-review-list="${pipelineId}"]`);
  if (!container) return;
  try {
    const reviews = await request(`/api/v1/reviews/${pipelineId}`);
    container.innerHTML = reviews.length ? reviews.map(review => `
      <article class="review-comment review-${escapeHtml(review.kind)}">
        <div class="review-comment-head"><strong>${escapeHtml(review.author_name)}</strong><span>${escapeHtml(reviewKindLabels[review.kind] || review.kind)}</span></div>
        ${review.file_path ? `<div class="review-location">${escapeHtml(review.file_path)}${review.line_number ? `:${review.line_number}` : ''}</div>` : ''}
        <p>${escapeHtml(review.body)}</p>
        <time>${escapeHtml(formatDate(review.created_at))}</time>
      </article>`).join('') : '<div class="feed-no-reviews">No comments, solutions, or feedback yet.</div>';
  } catch (error) {
    container.innerHTML = `<div class="feed-no-reviews">${escapeHtml(error.message)}</div>`;
  }
}

async function loadFeed({force = false} = {}) {
  if (!force && hasUnsavedReview()) return;
  try {
    const items = await request('/api/v1/feed', {cache: 'no-store'});

    total.textContent = items.length;
    success.textContent = items.filter(item => item.status === 'success').length;
    failed.textContent = items.filter(item => item.status === 'failed').length;
    running.textContent = items.filter(item => ['running', 'pending'].includes(item.status)).length;

    if (!items.length) {
      feed.innerHTML = '<div class="feed-empty">No public Agent results yet. Completed Agent runs will appear here.</div>';
      return;
    }

    feed.innerHTML = items.map(item => `
      <article class="feed-card" data-pipeline-id="${escapeHtml(item.id)}">
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
        ${renderLogs(item)}
        <section class="review-panel">
          <div class="review-panel-head"><h4>Community comments and solutions</h4><span>Share feedback, explain an error, or propose a working solution.</span></div>
          <div class="review-list" data-review-list="${escapeHtml(item.id)}"><div class="feed-no-reviews">Loading responses…</div></div>
          <form class="review-form" data-review-form="${escapeHtml(item.id)}">
            <div class="review-form-row">
              <select name="kind" aria-label="Response type">
                <option value="comment">Comment</option>
                <option value="solution">Solution</option>
                <option value="feedback">Feedback</option>
                <option value="error">Code error</option>
                <option value="suggestion">Suggestion</option>
                <option value="approval">Approval</option>
              </select>
              <input name="file_path" placeholder="File path (optional)" />
              <input name="line_number" type="number" min="1" placeholder="Line" />
            </div>
            <textarea name="body" required maxlength="5000" placeholder="Leave a comment, share a solution, or give feedback on this Agent result..."></textarea>
            <div class="review-actions">
              <button type="submit">Post response</button>
              ${item.can_request_fix ? `<button type="button" class="agent-fix-button" data-fix-pipeline="${escapeHtml(item.id)}">Ask Amosclaud to investigate</button>` : ''}
            </div>
            <p class="review-message" data-review-message="${escapeHtml(item.id)}"></p>
          </form>
        </section>
      </article>
    `).join('');

    items.forEach(item => loadReviews(item.id));
  } catch (error) {
    console.error('[Public feed]', error);
    feed.innerHTML = '<div class="feed-empty">The public feed is temporarily unavailable.</div>';
  }
}

feed.addEventListener('submit', async event => {
  const form = event.target.closest('[data-review-form]');
  if (!form) return;
  event.preventDefault();
  const pipelineId = form.dataset.reviewForm;
  const message = document.querySelector(`[data-review-message="${pipelineId}"]`);
  const data = new FormData(form);
  const line = data.get('line_number');
  const submitButton = form.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  try {
    await request(`/api/v1/reviews/${pipelineId}`, {
      method: 'POST',
      body: JSON.stringify({
        kind: data.get('kind'),
        body: data.get('body'),
        file_path: data.get('file_path') || null,
        line_number: line ? Number(line) : null
      })
    });
    form.reset();
    message.textContent = 'Your response was posted.';
    await loadReviews(pipelineId);
  } catch (error) {
    message.innerHTML = error.message === 'Sign in to review work'
      ? 'Please <a href="/login">sign in</a> to post comments, solutions, or feedback.'
      : escapeHtml(error.message);
  } finally {
    submitButton.disabled = false;
  }
});

feed.addEventListener('click', async event => {
  const button = event.target.closest('[data-fix-pipeline]');
  if (!button) return;
  const pipelineId = button.dataset.fixPipeline;
  const card = button.closest('.feed-card');
  const form = card.querySelector('[data-review-form]');
  const data = new FormData(form);
  const instruction = data.get('body') || 'Diagnose the failed pipeline, identify the blocking code errors, run verification checks again, and report the result.';
  const line = data.get('line_number');
  const message = card.querySelector(`[data-review-message="${pipelineId}"]`);
  button.disabled = true;
  button.textContent = 'Amosclaud is investigating…';
  try {
    const result = await request(`/api/v1/reviews/${pipelineId}/fix`, {
      method: 'POST',
      body: JSON.stringify({
        instruction,
        file_path: data.get('file_path') || null,
        line_number: line ? Number(line) : null
      })
    });
    message.textContent = `Investigation run ${result.repair_pipeline_id} finished with status: ${result.status}.`;
    await loadFeed({force: true});
  } catch (error) {
    message.textContent = error.message;
    button.disabled = false;
    button.textContent = 'Ask Amosclaud to investigate';
  }
});

document.getElementById('refresh-feed').addEventListener('click', () => loadFeed({force: true}));
loadFeed({force: true});
setInterval(() => loadFeed(), 10000);
