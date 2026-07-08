# 🚀 Amoscloud AI - Professional CI/CD & Deployment Automation

![Amosclaud-ai Status](https://img.shields.io/badge/Amosclaud--ai-%F0%9F%90%A6_Live_%26_Active-brightgreen)

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

```
amosclaude-clean/
├── src/                        # Python backend (CI/CD automation engine)
│   ├── amoscloud_ai/
│   │   ├── api/                # REST API (Flask) for web & Android apps
│   │   │   ├── __init__.py
│   │   │   └── chat_api.py     # /api/chat, /api/capabilities, /health
│   │   ├── main.py             # App entry point — serves API + web app
│   │   └── services/           # Deployment & database services
│   ├── ai/                     # AI agent contingency logic
│   ├── core/                   # CI orchestrator, code analyser, git manager
│   └── database/               # DB manager
├── web/                        # 🌐 Web App (runs in any browser)
│   ├── index.html              # SPA with AI Chat + Browser + Dashboard
│   ├── styles.css
│   └── app.js
├── android/                    # 📱 Android App (Kotlin)
│   ├── app/src/main/
│   │   ├── AndroidManifest.xml
│   │   ├── java/com/amosclaudai/
│   │   │   ├── MainActivity.kt        # Home screen
│   │   │   ├── AiChatActivity.kt      # AI chat
│   │   │   ├── BrowserActivity.kt     # WebView browser
│   │   │   ├── SettingsActivity.kt    # API URL configuration
│   │   │   ├── api/AmosclaudApiClient.kt
│   │   │   ├── adapter/ChatAdapter.kt
│   │   │   └── model/
│   │   └── res/                # Layouts, drawables, strings, themes
│   └── build.gradle.kts
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 🌐 Web App

The web app is served automatically by the Flask backend at `http://localhost:8000`.

Features:
- **AI Chat** — send messages and receive responses from Amosclaud-AI
- **Web Browser** — built-in iframe browser with bookmarks and address bar
- **Dashboard** — live stats and capabilities overview
- **Dark mode** — toggle in Settings

Open `http://localhost:8000` after starting the backend.

## 📱 Android App

A native Kotlin Android app with:
- **Home screen** — quick-launch tiles
- **AI Chat** — full conversation interface with the backend API
- **Web Browser** — full-featured WebView with bookmarks and navigation
- **Settings** — configure the backend API URL

### Building the Android App

**Requirements:** Android Studio Hedgehog or later, JDK 17, Android SDK 34.

```bash
cd android
./gradlew assembleDebug          # Build debug APK
./gradlew assembleRelease        # Build release APK
./gradlew installDebug           # Install on connected device/emulator
```

The APK is output to `android/app/build/outputs/apk/debug/app-debug.apk`.

**Default API URL:** `http://10.0.2.2:8000` (Android emulator → host machine).  
Change it in **Settings** for real devices (use your machine's local IP, e.g. `http://192.168.1.x:8000`).

