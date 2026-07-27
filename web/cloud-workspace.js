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

  const script = document.createElement('script');
  script.type = 'module';
  script.src = '/static/cloud-terminal/main.js';
  script.dataset.amosclaudCompleteTerminal = 'true';
  script.dataset.amosclaudTerminalContract = JSON.stringify(contract);
  document.body.appendChild(script);
})();
