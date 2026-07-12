# Amosclaud

Amosclaud is a self-hosted development platform with native accounts, `@amosclaud.com` mailboxes, repository hosting, source workspaces, storage, organizations, community tools, CI/CD pipelines, deployments, and an autonomous development agent.

Current version: **1.0.1**

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

Installable application metadata:

```text
web/manifest.webmanifest
web/service-worker.js
web/app-install.js
web/amosclaud-app-icon.svg
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
| `/feed` | Public feed |
| `/docs` | FastAPI documentation |
| `/health` | Server health check |

## Project structure

```text
amosclaude-clean/
├── amoscloud_ai/
│   ├── api/routes/          # Authentication, mail, repositories, licenses, storage, agent, and other APIs
│   ├── main.py              # FastAPI entry point and web routes
│   └── __init__.py          # Version and package metadata
├── web/                     # Website and installable app files
├── Infrastructure/          # Container files
├── Scripts/start.sh         # Railway and production startup script
├── tests/                   # Automated tests
├── pyproject.toml           # Python build and package metadata
├── requirements.txt         # Runtime dependencies
└── README.md
```

## Release notes: 1.0.1 patch

- Added installable app support for Android, iOS, Microsoft Windows, Ubuntu, and other Linux desktops.
- Added a web app manifest, service worker, app icon, and installation prompt.
- Added Python package metadata and the `amosclaud` command.
- Added repository license selection and automatic `LICENSE` creation.
- Added optional standard `.gitignore` initialization.
- Updated platform, deployment, mail, passkey, repository, and installation instructions.
