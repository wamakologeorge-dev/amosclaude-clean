# 🚀 Amoscloud AI - Professional CI/CD & Deployment Automation

**Amoscloud AI** is an intelligent, autonomous CI/CD automation system designed for developers. It acts first, reports later, and handles everything from integration testing to database management and intelligent deployment.

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

## 🛠️ Amosclaud Platform

The **Amosclaud Platform** is a developer-focused layer built on top of Amoscloud AI that accelerates software creation, provides unified developer tooling, and exposes AI-powered assistance through both a REST API and a CLI.

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

### Platform API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/platform/` | Platform info |
| `GET` | `/platform/projects/templates` | List project templates |
| `POST` | `/platform/projects/create` | Create a new project |
| `POST` | `/platform/build` | Build a project |
| `POST` | `/platform/tools/quality-check` | Run quality checks |
| `GET` | `/platform/tools/available` | List available tools |
| `POST` | `/platform/ai/review` | AI code review |
| `POST` | `/platform/ai/generate/function` | Generate function stub |
| `POST` | `/platform/ai/generate/class` | Generate class stub |
| `POST` | `/platform/ai/generate/tests` | Generate unit tests |
| `POST` | `/platform/ai/generate/docs` | Generate Markdown docs |
| `POST` | `/platform/ai/refactor` | Get refactoring suggestions |

---

## 📋 Project Structure

