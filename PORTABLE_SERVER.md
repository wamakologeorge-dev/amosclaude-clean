# Amosclaud Agent Server — Portable Folder

Amosclaud is distributed as a complete, self-hosted folder. It owns its virtual environment, configuration, repositories, storage, database, workspace, and server process.

## Requirements

- Python 3.11 or newer
- Git
- Internet access during the first dependency installation

## Start on Windows

1. Extract the ZIP archive to a permanent folder.
2. Open `START_HERE.html`.
3. Double-click `start-windows.bat`.
4. Open `http://localhost:8000`.

## Start on Linux or macOS

```bash
chmod +x start-local.sh
./start-local.sh
```

Then open `http://localhost:8000`.

## Activate the Amosclaud agent

The local platform starts without a secret. The AI agent requires a customer Amosclaud API key with purchased agent-credit balance.

1. Sign in at `https://amosclaud.com/api-access`.
2. Purchase an agent-credit pack.
3. Create an installation API key.
4. Copy the key into this folder's `.env`:

```env
AMOSCLAUD_API_URL=https://amosclaud.com
AMOSCLAUD_API_KEY=amos_live_your_customer_key
```

The complete key is displayed once. Do not commit it or share the configured folder.

## Owner provider infrastructure

Private self-hosted model credentials and third-party provider keys belong only on Amosclaud-controlled provider infrastructure. They are never embedded in customer archives.

## Folder ownership

Runtime state remains inside the extracted folder under `data/`. Back up that directory before moving, updating, or deleting the server folder.

## Release verification

Every GitHub Release includes `SHA256SUMS.txt`. Verify the archive checksum before extracting it.
