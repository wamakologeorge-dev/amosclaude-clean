(() => {
  const script = document.createElement('script');
  script.type = 'module';
  script.src = '/static/cloud-terminal/main.js';
  script.dataset.amosclaudCompleteTerminal = 'true';
  document.body.appendChild(script);
})();
