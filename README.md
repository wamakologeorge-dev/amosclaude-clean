# Amosclaud

Amosclaud is a self-hosted development platform with native accounts, `@amosclaud.com` mailboxes, repository hosting, source workspaces, storage, organizations, community tools, CI/CD pipelines, deployments, and an autonomous development agent.

Current version: **1.0.1**

## Install the server package

GitHub server releases are app-style archives with one top-level `Amosclaud` folder, not a deeply nested repository checkout. Download the ZIP on Windows or the tarball on Linux/macOS, extract it, and run the installer once:

- Windows: right-click `install-amosclaud.ps1`, then run it with PowerShell.
- Linux/macOS: run `./install-amosclaud.sh` from a terminal.

The installer creates private local configuration, starts restartable Docker services, and can pair the computer with the Amosclaud Task Router using a one-time private-runner credential. Paired runners connect outbound to `amosclaud.com`; downloads never execute silently and the service does not open an inbound remote-control port.

A `server-v*` tag builds `Amosclaud-Server.zip`, `Amosclaud-Server.tar.gz`, and `SHA256SUMS.txt` through `.github/workflows/server-release.yml`.

The downloaded package is an automated workspace with this stable layout:

```text
Amosclaud/
├── app/                 # managed application internals
├── config/              # configuration templates
├── data/                # durable application data
├── logs/                # local operational logs
├── workspace/projects/  # developer-controlled projects
├── PACKAGE_MANIFEST.json
└── amosclaud-workspace.*
```

Use `amosclaud-workspace doctor`, `start`, `stop`, `status`, or `logs` instead of navigating through application source folders. The installer creates missing workspace directories automatically and preserves the existing `AmosclaudWorkspace` location for source-based installations.

### Build and dependency management

- `pyproject.toml` defines the installable Amosclaud package, console commands, and build backend.
- `requirements.txt` declares supported runtime dependencies.
- `requirements-dev.txt` declares reproducible test, lint, security, and release tooling.
- `Makefile` provides short Unix developer commands.
- `python scripts/workspace_task.py <task>` provides the same core automation on Windows, Linux, and macOS.

```bash
make setup
make build
make test
make quality
make package
```

On Windows, the equivalent complete build is:

```powershell
python scripts/workspace_task.py setup
python scripts/workspace_task.py package
```

`.github/workflows/workspace-ci.yml` moves the same validation into GitHub Actions. Every pull request and protected branch update runs the complete test suite on Python 3.11 and 3.12, validates workspace automation, performs a security scan, builds the installable distribution, and stores the resulting wheel and source archive as workflow artifacts.

### Amosclaud Memory Guard

`amosclaud-memory status` reports physical RAM, existing swap/pagefile capacity, and a bounded server recommendation. It never changes the host by default. Linux administrators can apply the recommendation with `sudo amosclaud-memory apply --yes`; Windows packages include `install-virtual-memory.ps1`, which requires both `-Apply` and an elevated Administrator terminal. macOS swap remains under automatic operating-system control.

## Sign in from any device

Amosclaud accounts work across phones, tablets, laptops, and desktop computers.

Returning users can sign in with:

- fingerprint, Face ID, Touch ID, Windows Hello, device PIN, or screen lock through passkeys
- Amosclaud username and password as a fallback

Users may enter either their full address, such as `username@amosclaud.com`, or only the username. The same account is used on every supported device.

## Install Amosclaud as an app

Amosclaud is an installable Progressive Web App. It runs from `https://amosclaud.com`, opens in its own app window, keeps the Amosclaud icon on the device, and uses the same account and server as the website.

### Android

1. Open `https://amosclaud.com` in Chrome.
2. Sign in or create an Amosclaud account.
3. Tap **Install Amosclaud app** when the button appears.
4. If the button is not shown, open Chrome's menu and tap **Install app** or **Add to Home screen**.

### iPhone and iPad

1. Open `https://amosclaud.com` in Safari.
2. Tap the **Share** button.
3. Tap **Add to Home Screen**.
4. Confirm the name **Amosclaud**, then tap **Add**.

Apple devices complete installation through Safari's Share menu.

### Microsoft Windows

1. Open `https://amosclaud.com` in Microsoft Edge or Google Chrome.
2. Open the browser menu.
3. Choose **Apps → Install Amosclaud** in Edge, or **Install Amosclaud** in Chrome.
4. Amosclaud will appear in the Start menu and can be pinned to the taskbar.

### Ubuntu and other Linux desktops

1. Open `https://amosclaud.com` in Chrome, Chromium, or Microsoft Edge.
2. Open the browser menu.
3. Choose **Install Amosclaud**.
4. Launch it from the desktop application menu.

The installable app requires HTTPS in production. Local development works on `localhost`.

## Native desktop packages

Amosclaud also includes a desktop packaging foundation in the `desktop/` directory.

Supported package targets:

- Windows `.exe` installer for x64 and ARM64
- macOS `.dmg` for Intel and Apple Silicon
- Linux `.AppImage`
- Debian/Ubuntu `.deb`

The desktop shell uses Electron with context isolation, sandboxing, disabled Node.js integration in the web page, external-link protection, and automatic update checks.

Desktop release builds are created by `.github/workflows/desktop-release.yml`. A tag in this format starts the release workflow:

```text
desktop-v1.0.0
```

The workflow builds platform-specific artifacts and attaches them to a GitHub Release. Code signing and Apple notarization credentials should be configured before distributing trusted production installers.

### Run the desktop shell locally

Requirements:

- Node.js 22 or newer
- npm

```bash
git clone https://github.com/wamakologeorge-dev/amosclaude-clean.git
cd amosclaude-clean/desktop
npm install
npm start
```

Build local packages:

```bash
npm run dist
```

The desktop application connects to `https://amosclaud.com` by default. For development, set `AMOSCLAUD_URL` before starting it.

macOS or Linux:

```bash
AMOSCLAUD_URL=http://localhost:8000 npm start
```

Windows PowerShell:

```powershell
$env:AMOSCLAUD_URL="http://localhost:8000"
npm start
```

## Repository creation and licenses

The **New repository** form supports private or public repositories, optional README initialization, an optional standard `.gitignore`, and these license choices:

- No license
- MIT License
- Apache License 2.0
- GNU GPLv3
- GNU AGPLv3
- GNU LGPLv3
- Mozilla Public License 2.0
- BSD 2-Clause
- BSD 3-Clause
- ISC License
- The Unlicense
- Eclipse Public License 2.0
- Boost Software License 1.0
- Creative Commons Zero v1.0

When selected, Amosclaud creates and commits the `LICENSE` file automatically. The template service is implemented in `amoscloud_ai/api/routes/repository_templates.py`.

## Run locally with Python

Requirements:

- Python 3.11 or newer
- Git

```bash
git clone https://github.com/wamakologeorge-dev/amosclaude-clean.git
cd amosclaude-clean
python -m venv .venv
```

Activate the virtual environment.

macOS, Ubuntu, or other Linux:

```bash
source .venv/bin/activate
```

Microsoft Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Install and run:

```bash
python -m pip install --upgrade pip
pip install -e .
amosclaud
```

Open:

- Amosclaud: `http://localhost:8000`
- API documentation: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

A direct start also works:

```bash
python -m amoscloud_ai.main
```

## Run with Docker

```bash
git clone https://github.com/wamakologeorge-dev/amosclaude-clean.git
cd amosclaude-clean
docker compose -f Infrastructure/docker-compose.yml up --build
```

Open `http://localhost:8000`.

## Railway production deployment

Railway should start Amosclaud with:

```bash
bash Scripts/start.sh
```

Attach a persistent Railway volume and mount it at:

```text
/data
```

Recommended production variables:

```env
AUTH_DB_PATH=/data/auth.db
AUTH_COOKIE_SECURE=true
AUTH_SESSION_DAYS=7
AMOS_MAIL_DOMAIN=amosclaud.com
PASSKEY_RP_ID=amosclaud.com
PASSKEY_ORIGIN=https://amosclaud.com
PASSKEY_RP_NAME=Amosclaud
PASSKEY_SETUP_MINUTES=10
```

The persistent `/data` volume is required so user accounts, passkeys, sessions, mail, and other SQLite-backed records survive restarts and deployments.

Optional GitHub repository linking:

```env
GITHUB_CLIENT_ID=your-client-id
GITHUB_CLIENT_SECRET=your-client-secret
GITHUB_CALLBACK_URL=https://amosclaud.com/api/v1/auth/github/callback
```

Optional internet mail delivery:

```env
MAIL_SMTP_HOST=your-smtp-host
MAIL_SMTP_PORT=587
MAIL_SMTP_USERNAME=your-smtp-username
MAIL_SMTP_PASSWORD=your-smtp-password
MAIL_SMTP_FROM=verified-sender@amosclaud.com
MAIL_SMTP_TLS=true
```

Internal messages between Amosclaud mailboxes work through the Amosclaud database. Trusted public-internet mail also requires correct MX, SPF, DKIM, and DMARC records for `amosclaud.com`, plus an approved mail provider.

## App and package metadata

Installable web application metadata:

```text
web/manifest.webmanifest
web/service-worker.js
web/app-install.js
web/amosclaud-app-icon.svg
```

Desktop package metadata:

```text
desktop/package.json
desktop/main.js
desktop/preload.js
.github/workflows/desktop-release.yml
```

Python package and patch-version metadata:

```text
pyproject.toml
amoscloud_ai/__init__.py
```

The `amosclaud` console command starts `amoscloud_ai.main:main`.

## Main product routes

| Route | Purpose |
|---|---|
| `/` | Amosclaud Agent workspace |
| `/login` | Native Amosclaud sign-in and account creation |
| `/repositories` | Native repository list and creation |
| `/workspace/{repository_id}` | Repository source workspace |
| `/mail` | Amos Mail inbox and compose interface |
| `/community` | Developer community |
| `/feed` | Public pipeline and review feed |
| `/docs` | FastAPI documentation |
| `/health` | Server health check |

## Project structure

```text
amosclaude-clean/
├── amoscloud_ai/
│   ├── api/routes/          # Authentication, mail, repositories, storage, agent, and other APIs
│   ├── main.py              # FastAPI entry point and web routes
│   └── __init__.py          # Version and package metadata
├── web/                     # Website and installable PWA files
├── desktop/                 # Electron desktop application and packaging metadata
├── .github/workflows/       # CI and desktop release automation
├── Infrastructure/          # Container files
├── Scripts/start.sh         # Railway and production startup script
├── tests/                   # Automated tests
├── pyproject.toml           # Python build and package metadata
├── requirements.txt         # Runtime dependencies
└── README.md
```

## Release notes: 1.0.1 patch

- Added installable app support for Android, iOS, Microsoft Windows, Ubuntu, and other Linux desktops.
- Added passkey sign-in using fingerprint, Face ID, Touch ID, Windows Hello, device PIN, or screen lock.
- Kept username and password login as a cross-device fallback.
- Added the Electron desktop packaging foundation for Windows, macOS, and Linux.
- Added a GitHub Actions desktop release workflow.
- Added a web app manifest, service worker, app icon, and installation prompt.
- Added Python package metadata and the `amosclaud` command.
- Added repository license selection and automatic `LICENSE` creation.
- Added optional standard `.gitignore` initialization.
- Updated platform, deployment, mail, passkey, repository, and installation instructions.
