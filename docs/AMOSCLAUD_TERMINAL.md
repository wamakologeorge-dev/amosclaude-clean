# Amosclaud Terminal and Markdown

Amosclaud gives every authorized repository user a browser workspace. The
workspace page provides the file editor, safe Markdown preview, Xterm.js
terminal, project commands, tests, debugger entry points, port/problem
diagnostics, and repository tools. The same terminal can be opened from the
Amosclaud VS Code companion.

## What runs on the VM

The dedicated execution host runs `services/workspace_runtime` and creates one
bounded Docker container per repository workspace. The public Amosclaud service
keeps the database and GitHub credentials; it never receives the Docker socket.
The container is non-root, capped at 2 CPUs, 4096 MB RAM, and 512 processes,
uses a read-only root filesystem, drops Linux capabilities, disables privilege
escalation, and has no network by default. The selected repository is the only
durable writable mount for developer sessions.

The image includes:

- Bash, `sh`, tmux, nano, and Vim;
- Git and Git LFS;
- Python, Node.js/npm, C/C++, CMake, GDB, and strace;
- run, test, build, lint, debug, port, problem, connector, and network helpers;
- `amosclaud-markdown` plus the `amos markdown` shortcut.

## Deploy the execution host

On a dedicated VM with Docker and persistent storage:

1. Check out this repository on the VM.
2. Put a high-entropy value in `AMOSCLAUD_WORKSPACE_RUNTIME_TOKEN`; do not
   commit the environment file.
3. Mount the same repository storage used by the control plane at
   `AMOSCLAUD_REPOSITORY_STORAGE_ROOT`.
4. Build and start the runtime:

   ```sh
   docker compose -f docker-compose.workspace-runtime.yml \
     --profile build up -d --build workspace-base workspace-runtime
   ```

5. Keep the runtime control API private. Put an HTTPS/WSS reverse proxy in front
   of the terminal route and set `AMOSCLAUD_WORKSPACE_PUBLIC_URL` on the control
   plane to that public origin. Set `AMOSCLAUD_WORKSPACE_RUNTIME_URL` to the
   private control-plane URL and use the same token on both sides.
6. Set the allowed browser origins in
   `AMOSCLAUD_WORKSPACE_ALLOWED_ORIGINS`, then verify the authenticated
   `/health` endpoint and the unauthenticated `/live` endpoint.

The compose file binds to loopback by default. A public bind is only appropriate
when a firewall and TLS/WSS proxy protect the VM. Do not expose the Docker socket
or inject `DATABASE_URL`, GitHub tokens, model credentials, or platform secrets
into a workspace container.

## Use it without local setup

In a browser, open `/workspace/<repository-id>#terminal`, choose **Start
workspace**, and create a Bash, POSIX shell, or Python terminal. Use **Markdown
check** or run:

```sh
amosclaud-markdown check README.md
amos markdown toc README.md
amos markdown render README.md --output /tmp/readme.html
```

`check`, `toc`, and `render` accept only workspace-relative Markdown files and
reject traversal, external symlink targets, oversized files, invalid UTF-8, and
unsafe links or images.

For VS Code desktop or VS Code Web, install the Amosclaud companion, configure
the user’s own Amosclaud Autonomous key in Secret Storage, and run **Amosclaud:
Open Self Terminal**. The extension lists repositories the account can inspect or
develop, starts the isolated workspace, and opens a one-time WebSocket ticket.
Viewer sessions are read-only; developers and owners can edit, commit, and use
the governed GitHub actions.

## Screenshot troubleshooting

If the page says **Write access required**, the repository status/tool endpoints
are now read-accessible, but the selected account is still a viewer for write
actions. If it says **Connection needs retry**, check the runtime health result,
the private runtime URL/token, the VM firewall, and the public WSS URL. A viewer
cannot fall back to the same-service writable terminal; an isolated read-only
Docker runtime is required for viewer terminal access.
