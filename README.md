# Amosclaud Quick v1.0.0

Amosclaud Quick is the first scoped Amosclaud release: a local repository inspection tool that works before account creation or cloud setup.

## What it does

- Selects compact source context for an engineering objective.
- Checks Python, JSON, YAML and TOML syntax.
- Detects unresolved merge markers.
- Reports sensitive paths such as `.env` without reading their contents.
- Produces human-readable or JSON evidence.

## Install

Requires Python 3.11 or newer.

```bash
python -m pip install -r requirements.txt
```

Linux or macOS:

```bash
./run-amosclaud-quick.sh /path/to/repository --objective "Find the login error"
```

Windows:

```bat
run-amosclaud-quick.bat C:\path\to\repository --objective "Find the login error"
```

Install as a command:

```bash
python -m pip install .
amosclaud-quick . --objective "Inspect this repository"
```

Run the included release verification:

```bash
python verify_release.py
```

## Trust boundary

This tool runs locally. It requires no Amosclaud account, API key, hosted model or network connection. This release does not claim that the complete Amosclaud cloud platform is finished.
