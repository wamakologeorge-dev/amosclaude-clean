# Amosclaud Pipeline Ecosystem

Amosclaud uses one control plane, one cooperation pipeline contract, and one PipeFail recovery trail. Existing services keep their specialized responsibilities, but they exchange tasks, events, artifacts, approvals, capacity, and failure evidence through the same ecosystem instead of replacing or disabling one another.

## Main-branch product policy

`main` remains the canonical product branch and deployment source. Feature branches exist only as temporary review and verification lanes. A pipeline change is not considered part of Amosclaud until its checks pass and it is merged into `main`; no parallel production branch or duplicate platform is created.

## All-repository scope

The cooperation system does not exclude an application because it is old, differently structured, or implemented with another framework. GitHub-native applications, current platform services, root-level tools, archived or legacy applications, documentation, infrastructure, packages, tests, and unclassified tracked paths remain visible to the same pipeline.

Push and pull-request events carry every changed tracked path. Scheduled, manual, and repository-dispatch events cover every tracked file through a complete inventory count, surface classification, and manifest digest. The trigger evidence always reports `excluded_paths: []`.

## GitHub-native triggers

`.github/workflows/amosclaud-native-pipeline.yml` starts the same cooperation pipeline from these GitHub events:

- every repository push;
- pull requests that are opened, reopened, synchronized, or marked ready for review;
- issues that are opened, reopened, or labeled;
- the daily scheduled repository inspection;
- manual `workflow_dispatch` requests with an optional mode and objective;
- `repository_dispatch` requests for inspect, build, fix, deploy, monitor, or a general Amosclaud pipeline.

The workflow does not replace existing CI workflows. It translates the GitHub event into the shared Amosclaud pipeline and leaves the specialized workflows operating normally.

To send events to a deployed Amosclaud control plane, configure these GitHub Actions secrets:

- `AMOSCLAUD_PIPELINE_URL`: the Amosclaud public base URL, such as `https://www.amosclaud.com`;
- `AMOSCLAUD_GITHUB_PIPELINE_TOKEN`: the same secret configured on the server as `AMOSCLAUD_GITHUB_PIPELINE_TOKEN`.

The server also needs an automation owner. Configure `AMOSCLAUD_GITHUB_AUTOMATION_USER_ID` or `AMOSCLAUD_GITHUB_AUTOMATION_EMAIL`. If neither is configured, the integration uses the first existing Amosclaud administrator. When endpoint secrets are unavailable, such as on an untrusted fork pull request, the workflow records truthful local evidence and does not pretend that a remote pipeline was created.

Automatic triggers never authorize repository writes or deployments. A requested `fix` or `deploy` pipeline is created with `allow_writes=false` and stays behind the normal approval gate.

## Shared contract

Every cooperating component is attached to a pipeline ID and user scope:

1. The Agent, API, or GitHub-native trigger creates a cooperation pipeline.
2. Pipeline tasks declare dependencies and capabilities.
3. Workers and execution nodes advertise real capacity.
4. The scheduler assigns work through bounded resource leases.
5. Runtime pods use the selected repository workspace and artifact volume.
6. Every stage emits ordered events and evidence artifacts.
7. Protected repository writes and deployments remain behind approval gates.
8. PipeFail records failures, releases resources, retries bounded work, and can reassign a pod to another healthy node.
9. The final verification stage reports one result for the original pipeline.

## Why the new files exist

- `amoscloud_ai/api/routes/pipeline_cooperation.py` owns the durable pipeline, task, worker, approval, event, and artifact contract.
- `amoscloud_ai/api/routes/execution_nodes.py` adds node capacity, resource leases, Java pod lifecycle, and PipeFail while reusing the cooperation contract.
- `amoscloud_ai/api/routes/github_native_triggers.py` authenticates, deduplicates, and maps GitHub events into the same cooperation pipeline without bypassing approval policy.
- `amoscloud_ai/api/routes/pipelines.py` mounts the cooperation, runtime, and GitHub-native contracts under one `/api/v1/pipelines` API family.
- `scripts/ci/amosclaud_github_native_trigger.py` inventories every tracked path, classifies current, legacy, and GitHub-native surfaces, creates trigger evidence, and sends the event to the control plane when configured.
- `.github/workflows/amosclaud-native-pipeline.yml` declares the repository events that activate the bridge while preserving all existing workflows.
- `services/java-pod-runtime/Dockerfile` builds the reproducible non-root Java execution image.
- `services/java-pod-runtime/entrypoint.sh` executes Maven, Gradle-wrapper, or `javac` work and returns machine-readable success or PipeFail evidence.
- `web/control-plane.html`, `web/control-plane.js`, `web/control-plane-runtime.js`, and their styles expose the shared system to authenticated users without fabricating service health.
- The focused tests prove dependency release, approvals, resource return, node-failure reassignment, GitHub-event deduplication, full-repository scope, and automatic-trigger safety.

No file exists only to imitate a dashboard. A module may report `planned` or `foundation` until a real backend service and verification path are connected.
