(() => {
  const topbarLeft = document.querySelector('.topbar-left');
  const content = document.getElementById('content');
  if (!topbarLeft || !content) return;

  const menuButton = document.createElement('button');
  menuButton.type = 'button';
  menuButton.className = 'app-menu-button';
  menuButton.setAttribute('aria-label', 'Open Amosclaud menu');
  menuButton.setAttribute('aria-expanded', 'false');
  menuButton.textContent = '☰';
  topbarLeft.prepend(menuButton);

  const backdrop = document.createElement('div');
  backdrop.className = 'app-drawer-backdrop';
  const drawer = document.createElement('aside');
  drawer.className = 'app-drawer';
  drawer.setAttribute('aria-hidden', 'true');
  drawer.innerHTML = `
    <div class="app-drawer-head"><div class="app-drawer-brand"><span class="app-drawer-logo">A</span><span class="app-drawer-title">Amosclaud</span></div><button class="app-drawer-close" type="button" aria-label="Close menu">×</button></div>
    <div class="app-drawer-scroll">
      <nav>
        <button class="drawer-link active" data-target="content"><span class="drawer-icon">💬</span>Agent Chat</button>
        <a class="drawer-link" href="/repositories"><span class="drawer-icon">📁</span>Repositories</a>
        <button class="drawer-link" data-target="pipelines-table"><span class="drawer-icon">🔁</span>Pipelines</button>
        <button class="drawer-link" data-target="deployments-table"><span class="drawer-icon">🚀</span>Deployments</button>
        <a class="drawer-link" href="/admin/wifi"><span class="drawer-icon">📶</span>Wi-Fi Management</a>
        <a class="drawer-link" href="/feed"><span class="drawer-icon">🌐</span>Public Results Feed</a>
      </nav>
      <div class="drawer-section-title">Recent Agent Work</div>
      <div id="drawer-recents"><div class="drawer-recent"><span class="drawer-recent-dot"></span><div class="drawer-recent-copy"><strong>No recent work yet</strong><span>Agent runs will appear here</span></div></div></div>
    </div>
    <div class="app-drawer-footer"><div class="drawer-profile"><span id="drawer-avatar" class="drawer-avatar">A</span><div class="drawer-profile-copy"><strong id="drawer-user-name">Amosclaud user</strong><span>Developer workspace</span></div></div><button id="drawer-new-task" class="drawer-new-task" type="button">＋ New Agent Task</button></div>
  `;
  document.body.append(backdrop, drawer);

  const closeButton = drawer.querySelector('.app-drawer-close');
  const recentContainer = drawer.querySelector('#drawer-recents');
  const userName = drawer.querySelector('#drawer-user-name');
  const avatar = drawer.querySelector('#drawer-avatar');
  const newTask = drawer.querySelector('#drawer-new-task');
  let lastRecentText = '';

  function openDrawer(){drawer.classList.add('open');backdrop.classList.add('open');drawer.setAttribute('aria-hidden','false');menuButton.setAttribute('aria-expanded','true');document.body.style.overflow='hidden'}
  function closeDrawer(){drawer.classList.remove('open');backdrop.classList.remove('open');drawer.setAttribute('aria-hidden','true');menuButton.setAttribute('aria-expanded','false');document.body.style.overflow=''}
  function scrollToTarget(id){const target=document.getElementById(id);if(!target)return;closeDrawer();setTimeout(()=>target.scrollIntoView({behavior:'smooth',block:'start'}),60)}
  function escapeHtml(value){return String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;')}

  menuButton.addEventListener('click',openDrawer);closeButton.addEventListener('click',closeDrawer);backdrop.addEventListener('click',closeDrawer);
  document.addEventListener('keydown',event=>{if(event.key==='Escape')closeDrawer()});
  drawer.querySelectorAll('[data-target]').forEach(link=>link.addEventListener('click',()=>scrollToTarget(link.dataset.target)));
  newTask.addEventListener('click',()=>{closeDrawer();document.querySelector('.agent-section')?.scrollIntoView({behavior:'smooth',block:'start'});setTimeout(()=>document.getElementById('agent-objective-input')?.focus(),350)});

  async function hydrateUser(){try{const response=await fetch('/api/v1/auth/me',{credentials:'same-origin'});if(!response.ok)return;const data=await response.json();const name=data.name||data.email||'Amosclaud user';userName.textContent=name;avatar.textContent=name.trim().split(/\s+/).map(part=>part[0]).join('').slice(0,2).toUpperCase()||'A'}catch(_){}}
  function refreshRecents(){
    const replies=[...document.querySelectorAll('#agent-replies .agent-reply:not(.muted)')];
    const latest=replies.at(-1);
    if(!latest)return;
    const text=String(latest.textContent||'Latest agent result').replace(/\s+/g,' ').trim();
    if(!text||text===lastRecentText)return;
    lastRecentText=text;
    const failed=/failed|could not|error/i.test(text);
    recentContainer.innerHTML=`<div class="drawer-recent"><span class="drawer-recent-dot"></span><div class="drawer-recent-copy"><strong>${escapeHtml(text)}</strong><span>${failed?'Failed':'Latest'} agent task</span></div></div>`;
    recentContainer.querySelector('.drawer-recent')?.addEventListener('click',()=>scrollToTarget('agent-replies'));
  }
  hydrateUser();refreshRecents();setInterval(refreshRecents,3000);
})();
