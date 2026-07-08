# 🚀 Amoscloud AI - Professional CI/CD & Deployment Automation

![Amosclaud-ai Status](https://img.shields.io/badge/Amosclaud--ai-%F0%9F%90%A6_Live_%26_Active-brightgreen)

**Amoscloud AI** is an intelligent, autonomous CI/CD automation system designed for developers. It acts first, reports later, and handles everything from integration testing to database management.

## ✨ Features

- ✅ **Automated Integration Testing** - Run tests automatically on every commit
- ✅ **Smart Database Management** - Auto-migrate, backup, and optimize databases
- ✅ **Intelligent File Editing** - Analyze and modify code automatically
- ✅ **Code Deployment** - One-click deployment with rollback capabilities
- ✅ **Repository Management** - Clone, branch, commit operations
- ✅ **Real-time Reporting** - Comprehensive logs and status updates
- ✅ **Build Automation** - Compile and build projects automatically
- ✅ **Environment Management** - Auto-configure dev, staging, production

---

## 🚀 Render Auto-Deploy (Production)

This repository is configured for Render using `render.yaml`.

### Service settings

- **Type:** Web Service
- **Environment:** Python
- **Build command:** `pip install -r requirements.txt`
- **Start command:** `uvicorn src.amoscloud_ai.main:app --host 0.0.0.0 --port $PORT`
- **Health check:** `/health`

### Required environment variables

- `ANTHROPIC_API_KEY` (required)
- `LOG_LEVEL=INFO` (recommended)
- `ENVIRONMENT=production` (recommended)

### Deploy steps

1. Connect Render service to repository `wamakologeorge-dev/amosclaude-clean`
2. Select branch `main`
3. Enable **Auto-Deploy**
4. Set the environment variables above
5. Trigger first deploy: **Manual Deploy → Deploy latest commit**

### Troubleshooting checklist

- If build fails:
  - verify `requirements.txt` installs without conflicts
  - confirm Python environment is selected in Render
- If start fails:
  - verify import path in start command is exactly `src.amoscloud_ai.main:app`
  - ensure `uvicorn` is present in `requirements.txt`
- If health check fails:
  - open `/health` route and ensure it returns HTTP 200
  - verify app binds to `0.0.0.0` and `$PORT`

---

## 🛠️ Amosclaud Platform

The **Amosclaud Platform** is a developer-focused layer built on top of Amoscloud AI that accelerates software creation, provides unified developer tooling, and exposes AI-powered assistance through APIs and CLI.

### Platform Features

| Feature | Description |
|---|---|
| 🏗️ **Software Creator** | Scaffold new projects from built-in templates (Web API, CLI, Library, Microservice, Full-Stack, Data Pipeline) |
| 🔨 **Build Engine** | Multi-language build automation (Python, Node.js, Go, Java, Docker) with artifact management |
| 🔍 **Developer Tools** | Unified linting (flake8, pylint, mypy, bandit), formatting (black, isort), and testing (pytest) |
| 🤖 **AI Assistant** | Amosclaud-AI powered code review, function/class/test/docs generation, and refactoring suggestions |
| 🌐 **Platform API** | FastAPI REST endpoints at `/platform/*` |
| 💻 **Platform CLI** | `amosclaud-platform` command-line interface |

### Quick Start — CLI

```bash
pip install -e .

# Scaffold a new web API project
amosclaud-platform create my-api --type web_api --description "My awesome API"

# Build a project
amosclaud-platform build ./my-api --language python

# Run quality checks
amosclaud-platform check ./my-api

# AI code review
amosclaud-platform review ./my-api/main.py

# Generate a function stub
amosclaud-platform generate function parse_payload "Parse a JSON payload and return a dict" --language python

# Generate unit tests
amosclaud-platform generate tests ./my-api/main.py --output tests/test_main.py

# Generate Markdown docs
amosclaud-platform generate docs ./my-api/main.py --output docs/main.md

# Start the platform API server
amosclaud-platform serve --port 8001
```

### Quick Start — Docker Compose

```bash
docker-compose up amosclaud_platform
# Platform API: http://localhost:8001
# Swagger docs: http://localhost:8001/docs
```

## 📋 Project Structure

```text
amosclaude-clean/
├── src/
│   ├── amoscloud_ai/
│   │   ├── api/
│   │   ├── main.py
│   │   └── services/
│   ├── ai/
│   ├── core/
│   └── database/
├── web/
├── android/
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
