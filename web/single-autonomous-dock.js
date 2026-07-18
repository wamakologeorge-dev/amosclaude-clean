(() => {
  const input = document.getElementById('agent-objective-input');
  const focusChat = document.getElementById('focus-chat');
  if (!input || !focusChat) return;

  focusChat.addEventListener('click', () => {
    input.focus();
    input.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
})();