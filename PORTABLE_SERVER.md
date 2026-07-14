# Amosclaud Agent Server — Portable Folder

Amosclaud is distributed as a complete, self-hosted folder. It owns its virtual environment, configuration, repositories, storage, database, agent runtime, and server process.

## Requirements

- Python 3.11 or newer
- Git
- Internet access during the first dependency installation

## Start on Windows

1. Extract the ZIP archive to a permanent folder.
2. Double-click `start-windows.bat`.
3. Open `http://localhost:8000`.

## Start on Linux or macOS

```bash
chmod +x start-local.sh
./start-local.sh
```

Then open `http://localhost:8000`.

## Agent provider modes

Amosclaud remains the provider identity presented to clients.

### Self-hosted model runtime

Configure an OpenAI-compatible local endpoint in `.env`:

```env
AMOSCLAUD_MODEL_URL=http://127.0.0.1:11434
AMOSCLAUD_MODEL=qwen2.5-coder:3b
```

### Optional API-key adapters

External adapters are disabled by default. To enable one intentionally:

```env
AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS=true
ANTHROPIC_API_KEY=your-key
ANTHROPIC_MODEL=your-model
```

or:

```env
AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS=true
OPENAI_API_KEY=your-key
OPENAI_MODEL=your-model
```

Never commit the populated `.env` file or share a release folder containing private keys.

## Folder ownership

Runtime state remains inside the extracted folder under `data/`. Back up that directory before moving, updating, or deleting the server folder.

## Release verification

Every GitHub Release includes `SHA256SUMS.txt`. Verify the archive checksum before extracting it.
