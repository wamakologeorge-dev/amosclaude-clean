// SPDX-License-Identifier: LicenseRef-Amosclaud-Book-Proprietary-1.0
(() => {
  const api = '/api/v1/book';

  function chapterId() {
    const active = document.querySelector('.chapter.active, .chapter-link.active');
    if (!active) return null;
    const match = String(active.textContent || '').trim().match(/^(\d{1,3})\b/);
    return match ? match[1].padStart(2, '0') : null;
  }

  function setStatus(message) {
    const save = document.getElementById('saveState');
    if (save) save.textContent = message;
    const copyResult = document.getElementById('copy-result');
    if (copyResult) copyResult.textContent = message;
  }

  async function official(action) {
    const body = { action, chapter_id: chapterId() };
    const response = await fetch(`${api}/license/official-export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = payload.detail || {};
      const message = typeof detail === 'string'
        ? detail
        : (detail.message || 'An Amosclaud Book license is required for this action.');
      throw new Error(message);
    }
    if (payload.provenance) {
      sessionStorage.setItem('amosclaud-book-last-provenance', JSON.stringify(payload.provenance));
    }
    return payload;
  }

  async function licensedPrint() {
    try {
      setStatus('Checking Book export license…');
      const payload = await official('export');
      setStatus(`Licensed export • ${payload.provenance?.license_id || 'authorized'}`);
      window.print();
    } catch (error) {
      setStatus('Book export blocked');
      alert(error.message);
    }
  }

  async function licensedCopy() {
    try {
      setStatus('Checking Book copy license…');
      const payload = await official('copy');
      const portable = JSON.stringify(
        { document: payload.document, provenance: payload.provenance },
        null,
        2,
      );
      await navigator.clipboard.writeText(portable);
      setStatus(`Licensed copy • ${payload.provenance?.license_id || 'authorized'}`);
    } catch (error) {
      setStatus('Book copy blocked');
      alert(error.message);
    }
  }

  function addLicenseControls() {
    const topActions = document.querySelector('.top-actions');
    if (topActions && !document.getElementById('bookLicenseBtn')) {
      const license = document.createElement('button');
      license.id = 'bookLicenseBtn';
      license.textContent = 'Book license';
      license.onclick = () => window.open(`${api}/license/text`, '_blank', 'noopener');
      const copy = document.createElement('button');
      copy.id = 'licensedCopyBtn';
      copy.textContent = 'Licensed Copy';
      copy.onclick = licensedCopy;
      topActions.insertBefore(copy, topActions.lastElementChild || null);
      topActions.insertBefore(license, copy);
    }

    const header = document.querySelector('header');
    if (header && !document.getElementById('bookLicenseBadge')) {
      const badge = document.createElement('span');
      badge.id = 'bookLicenseBadge';
      badge.textContent = 'Book • Proprietary v1.0';
      badge.title = 'Root repository MIT remains unchanged. Amosclaud Book has separate proprietary scope.';
      badge.style.cssText = 'font-size:11px;padding:5px 8px;border:1px solid #ffffff55;border-radius:999px;white-space:nowrap';
      header.appendChild(badge);
    }

    const right = document.querySelector('aside.right, aside');
    if (right && !document.getElementById('bookLicenseNotice')) {
      const box = document.createElement('div');
      box.id = 'bookLicenseNotice';
      box.className = 'status';
      box.innerHTML = '<strong>License boundary</strong><br>MIT stays on the repository wall. Amosclaud Book uses LicenseRef-Amosclaud-Book-Proprietary-1.0. Public reading is allowed; official copy/export uses an Amosclaud grant and signed provenance.';
      right.insertBefore(box, right.firstChild);
    }
  }

  function protectOrdinaryCopy() {
    document.addEventListener('copy', event => {
      const selection = window.getSelection();
      const node = selection && selection.anchorNode;
      const element = node && (node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement);
      if (!element || !element.closest('.page, #chapter, #editor')) return;
      event.preventDefault();
      setStatus('Use Licensed Copy for Book content');
    });
  }

  addLicenseControls();
  protectOrdinaryCopy();

  const print = document.getElementById('printBtn');
  if (print) print.onclick = licensedPrint;

  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'p') {
      event.preventDefault();
      licensedPrint();
    }
  });
})();
