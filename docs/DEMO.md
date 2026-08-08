# Amosclaud Pipeline Demo

This demo produces real local evidence for the cooperation pipeline, execution-node scheduler, Java pod resource lease, telemetry layouts, and PipeFail recovery.

The visual in the README is an architectural rendering of this contract. It is not presented as a live production screenshot.

![Amosclaud pipeline demo](assets/amosclaud-pipeline-demo.svg)

## Demo 1: Run the focused cooperation tests

Install development dependencies first:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -e .
```

Run the focused tests:

```bash
pytest -q \
  tests/test_pipeline_cooperation.py \
  tests/test_execution_nodes.py \
  tests/test_runtime_telemetry.py \
  tests/test_github_native_triggers.py
```

These tests verify:

- dependency-ready tasks are released in order;
- protected repository-write stages wait for approval;
- workers claim only compatible queued tasks;
- Java pods consume and release bounded resource leases;
- a node going offline can reassign retryable work to another node;
- the node proposer ranks eligible nodes and explains rejected nodes;
- all-PipeFail telemetry and per-pipeline graphics use durable runtime records;
- duplicate GitHub deliveries map to one pipeline;
- legacy, GitHub-native, and unclassified paths remain in repository scope;
- automatic GitHub triggers never authorize writes.

A passing run is the authoritative demonstration. Do not copy an old terminal screenshot as proof for a newer commit.

## Demo 2: Build and run the Java pod image

Build the runtime:

```bash
docker build -t amosclaud-java-pod:21 services/java-pod-runtime
```

Create a temporary Java workspace:

```bash
rm -rf /tmp/amosclaud-java-demo
mkdir -p /tmp/amosclaud-java-demo/workspace /tmp/amosclaud-java-demo/artifacts

cat > /tmp/amosclaud-java-demo/workspace/HelloAmosclaud.java <<'JAVA'
public final class HelloAmosclaud {
    public static void main(String[] args) {
        System.out.println("Amosclaud Java pod verified");
    }
}
JAVA
```

Run the pod with the security boundaries represented by the launch specification:

```bash
docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --cpus 1 \
  --memory 512m \
  --pids-limit 128 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
  -e AMOSCLAUD_PIPELINE_ID=pipe_demo_local \
  -e AMOSCLAUD_JAVA_POD_ID=javapod_demo_local \
  -e AMOSCLAUD_BUILD_TOOL=javac \
  -e AMOSCLAUD_JDK=21 \
  -v /tmp/amosclaud-java-demo/workspace:/workspace \
  -v /tmp/amosclaud-java-demo/artifacts:/artifacts \
  amosclaud-java-pod:21
```

Inspect the machine-readable evidence:

```bash
cat /tmp/amosclaud-java-demo/artifacts/result.json
find /tmp/amosclaud-java-demo/artifacts -maxdepth 2 -type f -print
```

The result contains these fields with run-specific values:

```json
{
  "status": "completed",
  "pipeline_id": "pipe_demo_local",
  "java_pod_id": "javapod_demo_local",
  "build_tool": "javac",
  "jdk": "21",
  "started_at": "<UTC timestamp>",
  "finished_at": "<UTC timestamp>"
}
```

A failing Java command writes `/artifacts/pipefail.json` instead. The container evidence alone does not decide retry or reassignment; the authenticated runtime API records that policy decision against the original pipeline.

## Demo 3: Inspect the live API contract

Start the development server:

```bash
ENVIRONMENT=development python -m amoscloud_ai.main
```

Verify health and open the API documentation:

```bash
curl --fail http://127.0.0.1:8000/health
```

Open `http://127.0.0.1:8000/docs` and inspect these API families:

```text
/api/v1/pipelines/cooperation
/api/v1/pipelines/cooperation/runtime
```

Important runtime endpoints:

```text
POST /runtime/nodes
GET  /runtime/nodes
POST /runtime/telemetry/node-proposer
POST /runtime/pipelines/{pipeline_id}/java-pods
GET  /runtime/java-pods/{pod_id}/launch-spec
POST /runtime/java-pods/{pod_id}/start
POST /runtime/java-pods/{pod_id}/complete
POST /runtime/java-pods/{pod_id}/fail
GET  /runtime/telemetry/pipefail
GET  /runtime/pipelines/{pipeline_id}/telemetry
```

These routes require an authenticated Amosclaud session. Use the web application to register and sign in; do not weaken authentication for a demo.

## Demo 4: Exercise PipeFail in the Control Plane

This demo needs two registered Java-capable nodes.

1. Start Amosclaud and sign in.
2. Open `/control-plane`.
3. Register `java-node-primary` and `java-node-secondary` with `java-pod,maven,gradle,javac` capabilities.
4. Create an inspect or build pipeline.
5. Create a Java pod for that pipeline.
6. Mark the assigned node offline.
7. Refresh the runtime and telemetry sections.

For retryable active work, the expected evidence path is:

```text
node_unreachable
→ original resource lease released
→ PipeFail event recorded
→ compatible node selected
→ new bounded lease created
→ same Java pod scheduled at the next attempt
```

The all-PipeFail section should show a `retry_reassigned` action. The per-pipeline graphic should keep the failure and recovery attached to the same pipeline ID.

## Demo 5: Generate GitHub-native trigger evidence locally

The bridge script can create evidence without sending it to a server. GitHub normally supplies the event file and environment variables, but a small local fixture demonstrates the output shape:

```bash
cat > /tmp/amosclaud-event.json <<'JSON'
{
  "action": "opened",
  "repository": {"full_name": "example/amosclaud-demo"},
  "pull_request": {"number": 1, "head": {"sha": "1111111111111111111111111111111111111111"}}
}
JSON

GITHUB_EVENT_NAME=pull_request \
GITHUB_REPOSITORY=example/amosclaud-demo \
GITHUB_SHA=1111111111111111111111111111111111111111 \
GITHUB_HEAD_REF=demo-branch \
GITHUB_BASE_REF=main \
GITHUB_RUN_ID=1 \
GITHUB_RUN_ATTEMPT=1 \
python scripts/ci/amosclaud_github_native_trigger.py \
  --event-path /tmp/amosclaud-event.json \
  --output /tmp/amosclaud-native-evidence.json
```

Because no server URL or bridge token is supplied, the evidence reports `evidence_only`. That is the truthful result: the event was mapped and recorded locally, but no remote pipeline was created.

## Recording screenshots or a GIF

For release documentation:

1. use a clean local account and non-sensitive demo repository;
2. hide email addresses, tokens, private repository names, internal domains, and machine addresses;
3. show the commit SHA or release version represented by the recording;
4. capture pipeline creation, node selection, Java pod evidence, and the final verified state;
5. keep the original recording outside the repository until it has been reviewed for sensitive information;
6. add only optimized media with a documented source and purpose.

Never use a staged success screen to hide a failing test, missing model, unavailable node, or blocked approval.
