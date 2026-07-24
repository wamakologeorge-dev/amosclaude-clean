// public/script.js
document.addEventListener('DOMContentLoaded', () => {
    const fetchStatus = async () => {
        try {
            const response = await fetch('/status');
            const data = await response.json();

            // Update Agent Status
            document.getElementById('ci-clone-status').textContent = data.cmood_agent_status.ci_clone;
            document.getElementById('cloud-clone-status').textContent = data.cmood_agent_status.cloud_clone;
            document.getElementById('mood-agent-status').textContent = data.cmood_agent_status.mood_agent;
            document.getElementById('wait-arguments-status').textContent = data.cmood_agent_status.wait_arguments_with_agent;

            // Update File System Watcher
            document.getElementById('watched-directory').textContent = data.file_system_watcher.watching_directory;
            document.getElementById('last-event-type').textContent = data.file_system_watcher.last_event;
            document.getElementById('last-event-path').textContent = data.file_system_watcher.last_event_path;
            document.getElementById('last-event-timestamp').textContent = data.file_system_watcher.timestamp;

            // Update FastAPI Endpoints
            const endpointsDiv = document.getElementById('fastapi-endpoints');
            endpointsDiv.innerHTML = ''; // Clear previous
            data.fastapi_endpoints.forEach(endpoint => {
                const item = document.createElement('div');
                item.className = 'endpoint-item';
                item.innerHTML = `
                    <span class="endpoint-method">${endpoint.method}</span>
                    <span class="endpoint-path">${endpoint.path}</span>
                `;
                endpointsDiv.appendChild(item);
            });

            // Update Logs
            const logsOutput = document.getElementById('logs-output');
            const currentScrollPos = logsOutput.scrollTop;
            const maxScrollPos = logsOutput.scrollHeight - logsOutput.clientHeight;

            logsOutput.textContent = data.logs.join('\n');

            // Auto-scroll to bottom if already near bottom
            if (maxScrollPos - currentScrollPos < 20 || logsOutput.scrollTop === 0) { // Also scroll if it's the first load
                logsOutput.scrollTop = logsOutput.scrollHeight;
            }

        } catch (error) {
            console.error('Error fetching status:', error);
            document.getElementById('ci-clone-status').textContent = 'Error';
            document.getElementById('cloud-clone-status').textContent = 'Error';
            document.getElementById('mood-agent-status').textContent = 'Error';
            document.getElementById('wait-arguments-status').textContent = 'Error';
            document.getElementById('logs-output').textContent = 'Failed to load logs: ' + error.message;
        }
    };

    // Fetch status immediately and then every 2 seconds
    fetchStatus();
    setInterval(fetchStatus, 2000); // Refresh every 2 seconds
});
