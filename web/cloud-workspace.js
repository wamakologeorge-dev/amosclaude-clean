(() => {
  // Keep the public workspace contract discoverable at the stable loader path
  // while the implementation lives in the modular cloud-terminal bundle.
  const contract = Object.freeze({
    xtermPackage: '@xterm/xterm@5.5.0',
    ticketEndpoint: '/terminal-ticket-v2',
    websocketTransport: 'new WebSocket(ticket.websocket_url)',
    inputTransport: 'socket.send(data)',
    cpuLimit: 'maximum 2 CPU cores',
    memoryLimit: 'maximum 4 GB RAM',
    requestCredentials: "credentials: 'same-origin'",
    startedAutoConnect: 'if (started) await connect();',
    runningAutoConnect: 'if (running) await connect();',
    toolchainHeading: 'Developer toolchain:',
    isolationBoundary: 'separate Docker workspace runtime',
  });

  const mobileStyle = document.createElement('link');
  mobileStyle.rel = 'stylesheet';
  mobileStyle.href = '/static/cloud-terminal/mobile.css';
  mobileStyle.dataset.amosclaudTerminalMobile = 'true';
  document.head.appendChild(mobileStyle);

  function activateRequestedTerminal() {
    if (location.hash !== '#terminal') return;
    const terminalTab = document.querySelector('.ws-tab[data-tab="terminal"]');
    if (!terminalTab) return;
    terminalTab.click();
    requestAnimationFrame(() => {
      terminalTab.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    });
  }

  const script = document.createElement('script');
  script.type = 'module';
  script.src = '/static/cloud-terminal/main.js';
  script.dataset.amosclaudCompleteTerminal = 'true';
  script.dataset.amosclaudTerminalContract = JSON.stringify(contract);
  script.addEventListener('load', () => queueMicrotask(activateRequestedTerminal));
  document.body.appendChild(script);

  window.addEventListener('hashchange', activateRequestedTerminal);
  window.visualViewport?.addEventListener('resize', () => {
    window.dispatchEvent(new Event('resize'));
  });
})();
