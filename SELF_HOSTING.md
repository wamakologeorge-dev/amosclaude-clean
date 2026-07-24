# Run Amosclaud on your own Windows computer

This setup is designed for a GitHub ZIP download, Docker Desktop, and Chrome. GitHub Codespaces and Railway are not required.

## 1. Download

1. Open the repository in Chrome.
2. Select **Code** then **Download ZIP**.
3. Extract the ZIP to a normal folder such as `C:\Amosclaud`.

Do not run Amosclaud from inside the compressed ZIP preview.

## 2. Install Docker Desktop

Install Docker Desktop for Windows and start it. Wait until Docker reports that the engine is running.

## 3. Start Amosclaud

Double-click `start-amosclaud.bat`.

The first run creates a local `.env`, starts the backend and local model runtime, downloads the selected model, preserves data in Docker volumes, and opens Chrome at `http://localhost:8000`.

The initial model download may take several minutes and uses several gigabytes of disk space.

## 4. Manual browser entry

You may double-click the root `index.html`. It checks `http://localhost:8000/health` and redirects Chrome when the server is available. It cannot replace the local server because Chrome blocks important authentication, API, cookie, and service-worker features under `file://`.

## 5. Configure ownership

Open `.env` in Notepad before public use and replace:

```text
AMOSCLAUD_ADMIN_EMAIL=owner@example.com
```

Keep `AMOSCLAUD_MASTER_KEY` private. Losing that key makes encrypted Vault values unrecoverable.

## 6. Stop without deleting data

Double-click `stop-amosclaud.bat`. This stops containers but keeps the database, repositories, Vault, and downloaded models.

To remove all persistent local data intentionally, run:

```powershell
docker compose -f docker-compose.selfhost.yml down -v
```

## 7. Troubleshooting

View live logs:

```powershell
docker compose -f docker-compose.selfhost.yml logs -f
```

Check containers:

```powershell
docker compose -f docker-compose.selfhost.yml ps
```

Open the dashboard manually:

```text
http://localhost:8000
```

## Optional system profile

Preview changes:

```powershell
.\system-profile\install-profile.ps1
```

Apply after reviewing:

```powershell
.\system-profile\install-profile.ps1 -Apply
```

Remove the link later:

```powershell
.\system-profile\install-profile.ps1 -Remove
```

The profile is optional. Amosclaud runs without modifying your PowerShell configuration.
