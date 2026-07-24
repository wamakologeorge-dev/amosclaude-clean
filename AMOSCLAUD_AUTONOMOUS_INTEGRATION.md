# Amosclaud Autonomous Conversation Engine

## Purpose

This package adds a single conversational autonomous agent to Amosclaud.

The agent opens with a simple question:

> Welcome George, I’m Amosclaud Autonomous. What can I do for you today?

The user can select **Create**, **Fix**, **Deploy**, or **Monitor**, or type a normal request such as:

> I want to learn how to create a business website.

The agent then asks only the questions required to understand the objective, summarizes its plan, waits for **Proceed**, starts the job, verifies the result, and reports exact evidence or blocking checks.

## Files

- `amosclaud_autonomous_conversation.py` — FastAPI conversation service.
- `requirements.txt` — Python dependencies.
- `.env.example` — environment configuration example.

## Conversation lifecycle

1. **Intake**  
   Accept a quick action or free-form request.

2. **Objective detection**  
   Classify the request as Create, Fix, Deploy, Monitor, or Unknown.

3. **Clarifying questions**  
   Ask one useful question at a time.

4. **Plan ready**  
   Summarize the objective and implementation plan.

5. **Approval gate**  
   Do not execute until the user replies `Proceed`.

6. **Controlled execution**  
   Send the plan to the appropriate repository, coding, deployment, or monitoring adapter.

7. **Verification**  
   Run tests, health checks, build checks, or endpoint checks.

8. **Evidence response**  
   Return successful evidence and any blocking checks.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

## Run locally

```bash
uvicorn amosclaud_autonomous_conversation:app --host 0.0.0.0 --port 8000 --reload
```

Health check:

```bash
curl http://localhost:8000/health
```

## API request

```http
POST /api/autonomous/chat
Content-Type: application/json
```

```json
{
  "user_name": "George",
  "message": "I want to create a business website"
}
```

The first response includes a `conversation_id`. Send it with later messages:

```json
{
  "conversation_id": "returned-conversation-id",
  "user_name": "George",
  "message": "A cleaning and property maintenance business"
}
```

When the plan is ready:

```json
{
  "conversation_id": "returned-conversation-id",
  "user_name": "George",
  "message": "Proceed"
}
```

## Frontend integration

Connect the existing Send button to the API.

```javascript
let conversationId = null;

async function sendToAmosclaud(message) {
  const response = await fetch("/api/autonomous/chat", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      conversation_id: conversationId,
      user_name: "George",
      message
    })
  });

  if (!response.ok) {
    throw new Error(`Chat request failed: ${response.status}`);
  }

  const result = await response.json();
  conversationId = result.conversation_id;

  addAssistantMessage(result.message);

  if (result.blocking_checks?.length) {
    showBlockingChecks(result.blocking_checks);
  }

  if (result.evidence?.length) {
    showEvidence(result.evidence);
  }
}
```

Quick-action buttons should send plain text:

```javascript
createButton.onclick = () => sendToAmosclaud("Create");
fixButton.onclick = () => sendToAmosclaud("Fix");
deployButton.onclick = () => sendToAmosclaud("Deploy");
monitorButton.onclick = () => sendToAmosclaud("Monitor");
proceedButton.onclick = () => sendToAmosclaud("Proceed");
```

## Integrating real autonomous tools

`JobExecutor.execute()` is the integration boundary. Replace its placeholder logic with service adapters.

Recommended adapters:

```text
JobExecutor
├── RepositoryAdapter
│   ├── inspect repository
│   ├── create branch
│   ├── edit files
│   ├── commit changes
│   └── open pull request
├── VerificationAdapter
│   ├── run pytest
│   ├── run lint
│   ├── run build
│   └── collect logs
├── DeploymentAdapter
│   ├── deploy
│   ├── read deployment status
│   └── verify public URL
└── MonitoringAdapter
    ├── health checks
    ├── uptime
    ├── logs
    └── alert conditions
```

Each adapter should return structured evidence instead of only text:

```python
{
    "status": "passed",
    "check": "pytest",
    "command": "pytest -q",
    "exit_code": 0,
    "summary": "42 tests passed"
}
```

## Fixing the model endpoint error shown in Amosclaud

The screen reports:

```text
Amosclaud model endpoint did not answer after 2 attempt(s):
ConnectError: [Errno -2] Name or service not known
```

This means the backend cannot resolve the hostname configured for the model service.

Check these items:

1. Confirm `AMOSCLAUD_MODEL_URL` contains a valid hostname.
2. Do not use a Docker-only hostname from a process running outside Docker.
3. Inside Docker Compose, use the model service name, for example:
   `http://ollama:11434/v1/chat/completions`.
4. From a local process, use:
   `http://localhost:11434/v1/chat/completions`.
5. Confirm both containers use the same Docker network.
6. Test DNS and connectivity from the backend container:

```bash
getent hosts ollama
curl http://ollama:11434/api/tags
```

7. Confirm the model is installed:

```bash
ollama list
ollama pull qwen2.5-coder:3b
```

Example Docker Compose configuration:

```yaml
services:
  backend:
    build: .
    environment:
      AMOSCLAUD_MODEL_URL: http://ollama:11434/v1/chat/completions
      AMOSCLAUD_MODEL_NAME: qwen2.5-coder:3b
      AMOSCLAUD_MODEL_ATTEMPTS: "2"
    depends_on:
      - ollama
    networks:
      - amosclaud

  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_data:/root/.ollama
    networks:
      - amosclaud

networks:
  amosclaud:

volumes:
  ollama_data:
```

## Production requirements

Before enabling automatic code changes or deployment:

- Require explicit user approval before execution.
- Limit filesystem access to the selected workspace.
- Keep secrets out of prompts and logs.
- Add command allowlists.
- Use per-job timeouts.
- Store an audit log of actions and evidence.
- Run changes on a branch, not directly on the default branch.
- Require passing verification before merge or deployment.
- Return exact failures rather than claiming success.

## Suggested next integration step

Connect `JobExecutor` to the existing Amosclaud repository scanner and controlled action engine. The conversation engine should decide **what** is required; existing backend services should control **how** repository changes, tests, deployment, and monitoring are executed.
