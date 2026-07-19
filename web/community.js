(() => {
  const feed = document.getElementById('community-feed');
  const input = document.getElementById('community-post-input');
  const postButton = document.getElementById('community-post-button');
  const count = document.getElementById('community-post-count');
  const blocked = document.getElementById('blocked-users');
  let followingOnly = false;

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      ...options,
      headers: {
        ...(options.body ? {'Content-Type':'application/json'} : {}),
        ...(options.headers || {}),
      },
    });
    if (response.status === 401) {
      location.assign('/login');
      throw new Error('Authentication required');
    }
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok) throw new Error(data?.detail || `Request failed (${response.status})`);
    return data;
  }

  function escapeHtml(value) {
    return String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function initials(name) {
    return String(name || 'A').trim().split(/\s+/).map(part => part[0]).join('').slice(0,2).toUpperCase();
  }

  function formatDate(value) {
    try { return new Date(value).toLocaleString(); } catch { return value; }
  }

  async function loadFeed() {
    feed.textContent = 'Loading community…';
    try {
      const posts = await api(`/api/v1/community/feed?following_only=${followingOnly ? 'true' : 'false'}`);
      if (!posts.length) {
        feed.innerHTML = '<div class="empty-community">No community posts yet.</div>';
        return;
      }
      feed.innerHTML = posts.map(post => `
        <article class="community-card" data-post-id="${post.id}" data-user-id="${post.user_id}">
          <div class="community-card-head">
            <div class="community-avatar">${escapeHtml(initials(post.name))}</div>
            <div class="community-user"><strong>${escapeHtml(post.name || post.email)}</strong><span>${escapeHtml(post.email)} · ${formatDate(post.created_at)}</span></div>
            <div class="community-card-menu">
              <button class="community-action" data-action="${post.following ? 'unfollow' : 'follow'}">${post.following ? 'Unfollow' : 'Follow'}</button>
              <button class="community-action" data-action="block">Block</button>
            </div>
          </div>
          <div class="community-content">${escapeHtml(post.content)}</div>
          <div class="community-meta"><span>${post.followers} followers</span><span>${post.comments} comments</span></div>
          <div class="community-comments">
            <button class="community-action" data-action="comments">Open comments</button>
            <div class="comment-list" hidden></div>
            <div class="comment-compose" hidden><input type="text" maxlength="2000" placeholder="Write a comment…" /><button class="comment-send" type="button">Send</button></div>
          </div>
        </article>
      `).join('');
    } catch (error) {
      feed.innerHTML = `<div class="empty-community">${escapeHtml(error.message)}</div>`;
    }
  }

  async function loadBlocked() {
    try {
      const users = await api('/api/v1/community/blocked');
      blocked.innerHTML = users.length ? users.map(user => `
        <div class="blocked-row" data-user-id="${user.id}"><span>${escapeHtml(user.name || user.email)}</span><button type="button">Unblock</button></div>
      `).join('') : 'None';
    } catch (error) {
      blocked.textContent = error.message;
    }
  }

  async function loadComments(card) {
    const postId = card.dataset.postId;
    const list = card.querySelector('.comment-list');
    const composer = card.querySelector('.comment-compose');
    const comments = await api(`/api/v1/community/posts/${postId}/comments`);
    list.innerHTML = comments.length ? comments.map(comment => `
      <div class="comment"><strong>${escapeHtml(comment.name || comment.email)}</strong><p>${escapeHtml(comment.content)}</p></div>
    `).join('') : '<div class="comment">No comments yet.</div>';
    list.hidden = false;
    composer.hidden = false;
  }

  input.addEventListener('input', () => { count.textContent = `${input.value.length} / 4000`; });

  postButton.addEventListener('click', async () => {
    const content = input.value.trim();
    if (!content) return;
    postButton.disabled = true;
    try {
      await api('/api/v1/community/posts', { method:'POST', body:JSON.stringify({content}) });
      input.value = '';
      count.textContent = '0 / 4000';
      await loadFeed();
    } catch (error) {
      alert(error.message);
    } finally {
      postButton.disabled = false;
    }
  });

  document.querySelectorAll('[data-feed]').forEach(button => {
    button.addEventListener('click', () => {
      document.querySelectorAll('[data-feed]').forEach(item => item.classList.remove('active'));
      button.classList.add('active');
      followingOnly = button.dataset.feed === 'following';
      loadFeed();
    });
  });

  feed.addEventListener('click', async event => {
    const card = event.target.closest('.community-card');
    if (!card) return;
    const action = event.target.closest('[data-action]')?.dataset.action;
    const userId = card.dataset.userId;
    try {
      if (action === 'follow') await api(`/api/v1/community/users/${userId}/follow`, {method:'POST'});
      if (action === 'unfollow') await api(`/api/v1/community/users/${userId}/follow`, {method:'DELETE'});
      if (action === 'block' && confirm('Block this user? You will no longer see each other in the community.')) {
        await api(`/api/v1/community/users/${userId}/block`, {method:'POST'});
        await loadBlocked();
      }
      if (action === 'comments') {
        await loadComments(card);
        return;
      }
      if (event.target.classList.contains('comment-send')) {
        const commentInput = card.querySelector('.comment-compose input');
        const content = commentInput.value.trim();
        if (!content) return;
        await api(`/api/v1/community/posts/${card.dataset.postId}/comments`, {method:'POST', body:JSON.stringify({content})});
        commentInput.value = '';
        await loadComments(card);
        return;
      }
      if (action) await loadFeed();
    } catch (error) {
      alert(error.message);
    }
  });

  blocked.addEventListener('click', async event => {
    const row = event.target.closest('[data-user-id]');
    if (!row || event.target.tagName !== 'BUTTON') return;
    try {
      await api(`/api/v1/community/users/${row.dataset.userId}/block`, {method:'DELETE'});
      await Promise.all([loadBlocked(), loadFeed()]);
    } catch (error) {
      alert(error.message);
    }
  });

  Promise.all([loadFeed(), loadBlocked()]);
})();
