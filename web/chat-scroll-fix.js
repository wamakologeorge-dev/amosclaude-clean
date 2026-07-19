(() => {
  const replies = document.getElementById('agent-replies');
  const controls = document.querySelector('.agent-controls-stack');
  if (!replies || !controls) return;

  let userIsReadingHistory = false;
  let internalMove = false;

  function nearBottom() {
    return replies.scrollHeight - replies.scrollTop - replies.clientHeight < 90;
  }

  function updateReadingState() {
    userIsReadingHistory = !nearBottom();
  }

  replies.addEventListener('scroll', updateReadingState, { passive: true });
  replies.addEventListener('touchstart', updateReadingState, { passive: true });
  replies.addEventListener('wheel', updateReadingState, { passive: true });

  function placeWorkPanelInsideChat() {
    const mirror = controls.querySelector('.agent-mirror');
    if (mirror && mirror.parentElement !== replies) {
      internalMove = true;
      replies.appendChild(mirror);
      internalMove = false;
    }
  }

  function placeNewMessagesInConversationOrder() {
    const messages = [...replies.querySelectorAll(':scope > .agent-reply')];
    if (messages.length < 2) return;

    const newest = messages[0];
    const laterMessages = messages.slice(1);
    if (!laterMessages.some(message => message.compareDocumentPosition(newest) & Node.DOCUMENT_POSITION_PRECEDING)) return;

    internalMove = true;
    replies.appendChild(newest);
    internalMove = false;
  }

  function revealLatestOnlyWhenAppropriate() {
    if (!userIsReadingHistory || nearBottom()) {
      replies.scrollTo({ top: replies.scrollHeight, behavior: 'smooth' });
      userIsReadingHistory = false;
    }
  }

  const observer = new MutationObserver(() => {
    if (internalMove) return;
    const wasNearBottom = nearBottom();
    placeWorkPanelInsideChat();
    placeNewMessagesInConversationOrder();
    if (wasNearBottom && !userIsReadingHistory) revealLatestOnlyWhenAppropriate();
  });

  observer.observe(controls, { childList: true, subtree: true });
  placeWorkPanelInsideChat();

  const jumpButton = document.createElement('button');
  jumpButton.type = 'button';
  jumpButton.className = 'chat-jump-latest';
  jumpButton.textContent = 'Jump to latest';
  jumpButton.hidden = true;
  controls.appendChild(jumpButton);

  replies.addEventListener('scroll', () => {
    jumpButton.hidden = nearBottom();
  }, { passive: true });

  jumpButton.addEventListener('click', () => {
    replies.scrollTo({ top: replies.scrollHeight, behavior: 'smooth' });
    userIsReadingHistory = false;
    jumpButton.hidden = true;
  });
})();
