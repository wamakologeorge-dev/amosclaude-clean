# Amosclaud Model Station agent

This is the client half of the Amosclaud model station network. It runs on your
hardware, connects **outbound only** to Amosclaud, proves that a local
inference backend answers, claims queued inference requests and returns the
replies.

* Standard library only. No dependencies, nothing added to `requirements.txt`.
* Python 3.11 or newer.
* Any Ollama-compatible backend (`/api/tags`, `/api/chat`).

## What crosses the wire

| Direction | Content |
| --- | --- |
| Station to Amosclaud | Heartbeat: agent version, capabilities, OS/CPU/Python facts, the configured model name, the backend URL and whether the model is ready. |
| Amosclaud to station | A claimed request: its id, the chat `messages`, the requested model name, `max_tokens`, `temperature`. Amosclaud stores these encrypted and hands them out only to a station holding a valid credential. |
| Station to Amosclaud | The completion: `completed` with the reply text, or `failed` with a short error string. |

**Inference happens on your hardware.** The model weights, the backend process
and every token generated stay on the machine running this agent. Amosclaud
never receives your model, and the agent never opens an inbound port.

The agent never writes the station token, the prompt or the reply into its
logs. It logs request ids, message counts and character counts instead.

## 1. Register the station

Registration is a one-time, human step authenticated with your Amosclaud
browser session.

```bash
python -m station.register --email you@example.com --name "Studio station"
# or, if you already have the amos_session cookie value:
python -m station.register --session "$AMOS_SESSION" --name "Studio station"
```

It prints the environment block to copy, including the `amos_station_...`
credential. **The credential is shown once**; Amosclaud stores only its hash.
If you lose it, rotate it from the Server Stations page.

## 2a. Run it next to Ollama on your own machine

```bash
# Serve a model locally.
ollama pull qwen2.5-coder:1.5b
ollama serve   # listens on http://127.0.0.1:11434

# Run the agent (from a checkout of this repository).
export AMOSCLAUD_URL=https://www.amosclaud.com
export AMOSCLAUD_STATION_ID=station_xxxxxxxxxxxxxxxx
export AMOSCLAUD_STATION_TOKEN=amos_station_xxxxxxxxxxxxxxxx
export AMOSCLAUD_STATION_BACKEND=http://127.0.0.1:11434
export AMOSCLAUD_STATION_MODEL=qwen2.5-coder:1.5b
python -m station
```

Expected first lines on stderr:

```
station agent starting {'station_id': 'station_...', 'base_url': 'https://www.amosclaud.com', ...}
backend readiness changed: ready=True detail=model qwen2.5-coder:1.5b is installed
```

The station now shows as **online** on the Server Stations page and counts as a
ready inference station.

## 2b. Run it as a container

```bash
docker build -f station/Dockerfile -t amosclaud-station .

docker run -d --name amosclaud-station --restart unless-stopped \
  -e AMOSCLAUD_URL=https://www.amosclaud.com \
  -e AMOSCLAUD_STATION_ID=station_xxxxxxxxxxxxxxxx \
  -e AMOSCLAUD_STATION_TOKEN=amos_station_xxxxxxxxxxxxxxxx \
  -e AMOSCLAUD_STATION_BACKEND=http://host.docker.internal:11434 \
  -e AMOSCLAUD_STATION_MODEL=qwen2.5-coder:1.5b \
  amosclaud-station
```

On Linux, either add `--add-host=host.docker.internal:host-gateway` or point
`AMOSCLAUD_STATION_BACKEND` at the Ollama container on a shared Docker network
(for example `http://ollama:11434`).

The image runs as the non-root user `station` (uid 10001) and installs nothing
beyond the Python base image.

### Private network backend (for example Railway)

```bash
docker run -d --name amosclaud-station --restart unless-stopped \
  -e AMOSCLAUD_URL=https://www.amosclaud.com \
  -e AMOSCLAUD_STATION_ID=station_xxxxxxxxxxxxxxxx \
  -e AMOSCLAUD_STATION_TOKEN=amos_station_xxxxxxxxxxxxxxxx \
  -e AMOSCLAUD_STATION_BACKEND=http://amosclaud-model.railway.internal:11434 \
  -e AMOSCLAUD_STATION_MODEL=qwen2.5-coder:1.5b \
  amosclaud-station
```

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `AMOSCLAUD_URL` | `https://www.amosclaud.com` | Amosclaud platform base URL. |
| `AMOSCLAUD_STATION_ID` | *required* | `station_...` id returned at registration. |
| `AMOSCLAUD_STATION_TOKEN` | *required* | `amos_station_...` credential, shown once. |
| `AMOSCLAUD_STATION_BACKEND` | `http://127.0.0.1:11434` | Ollama-compatible backend base URL. |
| `AMOSCLAUD_STATION_MODEL` | `qwen2.5-coder:1.5b` | Model tag that must be installed on the backend. |
| `AMOSCLAUD_STATION_NAME` | host name based | Station name used by `station.register`. |
| `AMOSCLAUD_STATION_CAPABILITIES` | `model.inference` | Comma separated; `model.inference` is always included. |
| `AMOSCLAUD_STATION_POLL_INTERVAL` | `2` | Seconds between claim attempts when busy. |
| `AMOSCLAUD_STATION_POLL_MAX_INTERVAL` | `15` | Backoff ceiling while idle or erroring. |
| `AMOSCLAUD_STATION_HEARTBEAT_INTERVAL` | `30` | Seconds between heartbeats; clamped to 30 max so the 90s online window can never lapse. |
| `AMOSCLAUD_STATION_HTTP_TIMEOUT` | `15` | Timeout for every Amosclaud call. |
| `AMOSCLAUD_STATION_PROBE_TIMEOUT` | `10` | Timeout for the backend readiness probe. |
| `AMOSCLAUD_STATION_INFERENCE_TIMEOUT` | `120` | Timeout for one local completion. |
| `AMOSCLAUD_STATION_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

Registration-only variables: `AMOSCLAUD_SESSION`, `AMOSCLAUD_EMAIL`,
`AMOSCLAUD_PASSWORD` (all optional; the password is prompted if omitted).

## How it behaves

* **Readiness is never assumed.** Every heartbeat is preceded by a
  `GET {backend}/api/tags` probe that must list the configured model. If the
  probe fails, the agent still heartbeats but with `system.model.ready = false`,
  so Amosclaud reports the station as degraded rather than routing work to it.
* **Heartbeat cadence.** Default 30s against the platform's 90s online window,
  on a dedicated thread so a long completion cannot let the station lapse.
* **One request at a time.** The agent claims, runs and reports before claiming
  again, and backs off from 2s toward 15s while the queue is empty.
* **Always reports.** A backend error, timeout or empty reply is reported as
  `failed` with a short error string, so a request is never left hanging until
  it expires.
* **Never crashes on a transient error.** HTTP 5xx, connection refused and
  timeouts are logged and retried with backoff.
* **Clean shutdown.** `SIGINT` and `SIGTERM` stop the loops and join the
  heartbeat thread.

## Endpoints used

| Call | Auth |
| --- | --- |
| `POST /api/v1/server-stations` | `amos_session` cookie (registration only) |
| `POST /api/v1/server-stations/{station_id}/heartbeat` | `Authorization: Bearer amos_station_...` |
| `POST /api/v1/model-network/stations/{station_id}/claim` | same bearer credential |
| `POST /api/v1/model-network/stations/{station_id}/requests/{request_id}/complete` | same bearer credential |

## Tests

```bash
python -m pytest tests/test_station_agent.py tests/test_station_end_to_end.py -q
```

`tests/test_station_end_to_end.py` starts the real Amosclaud FastAPI
application together with a stub Ollama backend and drives the whole loop:
register, heartbeat, queue work with `model_network.request_inference`, claim,
infer, complete.
