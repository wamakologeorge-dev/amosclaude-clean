# Amosclaud Pipeline Ecosystem

Amosclaud uses one control plane, one cooperation pipeline contract, and one PipeFail recovery trail. Existing services keep their specialized responsibilities, but they exchange tasks, events, artifacts, approvals, capacity, telemetry, and failure evidence through the same ecosystem instead of replacing or disabling one another.

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

## Telemetry data layouts

The runtime exposes stable, machine-readable layouts rather than dashboard-only calculations.

### `node_proposer`

`POST /api/v1/pipelines/cooperation/runtime/telemetry/node-proposer`

The request declares the optional pipeline ID, JDK, build tool, CPU, memory, disk, GPU, and heartbeat freshness window. The response uses the `amosclaud.telemetry.node-proposer.v1` layout and includes:

- every registered node, not only eligible nodes;
- rank, score, eligibility, and selected proposal;
- heartbeat age and freshness;
- required, available, and missing capabilities;
- requested capacity, available capacity, remaining headroom, fit, and projected utilization for every resource;
- explicit reasons when a node is not eligible.

The proposal is advisory. Java pod creation remains authoritative and revalidates node state and capacity inside the resource-lease transaction.

### All PipeFail telemetry

`GET /api/v1/pipelines/cooperation/runtime/telemetry/pipefail`

The `amosclaud.telemetry.pipefail.v1` layout contains all PipeFail records for the authenticated Amosclaud owner, with optional pipeline filtering. It includes summary totals, failure kinds, recovery actions, nodes, hourly timeline buckets, affected pipelines, metadata, and the latest evidence records.

### PipeFail / pipeline graphics

`GET /api/v1/pipelines/cooperation/runtime/pipelines/{pipeline_id}/telemetry`

Each response includes an `amosclaud.graphics.pipefail-pipeline.v1` graph. Its nodes represent the pipeline, Java pods, PipeFail events, reassigned work, waiting work, and terminal failures. Its edges carry the real counts between those stages. The Control Plane renders these layouts using local HTML and CSS; it does not fabricate events or depend on an external chart provider.

## Shared contract

Every cooperating component is attached to a pipeline ID and user scope:

1. The Agent, API, or GitHub-native trigger creates a cooperation pipeline.
2. Pipeline tasks declare dependencies and capabilities.
3. Workers and execution nodes advertise real capacity.
4. The node proposer explains current fit; the scheduler revalidates and assigns work through bounded resource leases.
5. Runtime pods use the selected repository workspace and artifact volume.
6. Every stage emits ordered events and evidence artifacts.
7. Protected repository writes and deployments remain behind approval gates.
8. PipeFail records failures, releases resources, retries bounded work, and can reassign a pod to another healthy node.
9. Telemetry converts the same durable records into all-pipeline and per-pipeline graphics layouts.
10. The final verification stage reports one result for the original pipeline.

## Why the new files exist

### Runtime and pipeline implementation

- `amoscloud_ai/api/routes/pipeline_cooperation.py` owns the durable pipeline, task, worker, approval, event, and artifact contract.
- `amoscloud_ai/api/routes/execution_nodes.py` adds node capacity, resource leases, Java pod lifecycle, and PipeFail while reusing the cooperation contract.
- `amoscloud_ai/api/routes/runtime_telemetry.py` computes read-only node proposals, all-PipeFail telemetry, and per-pipeline graphics directly from durable runtime records.
- `amoscloud_ai/api/routes/github_native_triggers.py` authenticates, deduplicates, and maps GitHub events into the same cooperation pipeline without bypassing approval policy.
- `amoscloud_ai/api/routes/pipelines.py` mounts the cooperation, runtime, telemetry, and GitHub-native contracts under one `/api/v1/pipelines` API family.
- `scripts/ci/amosclaud_github_native_trigger.py` inventories every tracked path, classifies current, legacy, and GitHub-native surfaces, creates trigger evidence, and sends the event to the control plane when configured.
- `.github/workflows/amosclaud-native-pipeline.yml` declares the repository events that activate the bridge while preserving all existing workflows.
- `services/java-pod-runtime/Dockerfile` builds the reproducible non-root Java execution image.
- `services/java-pod-runtime/entrypoint.sh` executes Maven, Gradle-wrapper, or `javac` work and returns machine-readable success or PipeFail evidence.
- `web/control-plane.html`, `web/control-plane.js`, and `web/control-plane-runtime.js` expose pipelines and runtime operations.
- `web/control-plane-telemetry.js` renders only the telemetry returned by the backend, including ranked node proposals, all-PipeFail dimensions, timelines, and per-pipeline flow graphics.
- `web/control-plane-telemetry.css` gives those layouts a responsive visual structure without adding a chart framework or external dependency.

### Repository storefront and onboarding

- `README.md` is the five-second product storefront, architecture overview, status boundary, and path into deeper documentation.
- `docs/QUICKSTART.md` gives copyable local, self-hosted, execution-node, Java-pod, GitHub-trigger, and verification instructions.
- `docs/examples/pipeline-runtime.example.json` provides secret-free node-registration and Java-pod request bodies without pretending they are active resources.
- `docs/GITHUB_ACTIONS.md` explains workflow responsibilities, triggers, permissions, deduplication, evidence, and approval boundaries.
- `docs/DEMO.md` provides reproducible tests and runtime commands so visual proof can be regenerated for the current commit.
- `docs/assets/amosclaud-pipeline-architecture.svg` visualizes the shared control-plane, pipeline, node, Java-pod, evidence, and PipeFail architecture.
- `docs/assets/amosclaud-pipeline-demo.svg` illustrates the implemented evidence flow and is explicitly identified as an architectural demo rather than a live deployment screenshot.

### Contribution and maintenance controls

- `CONTRIBUTING.md` defines issue evidence, local setup, ecosystem-preserving changes, pipeline responsibilities, workflow safety, and review requirements.
- `.github/PULL_REQUEST_TEMPLATE.md` requires contributors to state ecosystem integration, verification, security, approvals, migration, and file purpose.
- `.github/ISSUE_TEMPLATE/bug_report.yml` collects reproducible, sanitized failure evidence using the canonical bug and triage labels.
- `.github/ISSUE_TEMPLATE/feature_request.yml` requires feature proposals to describe a user problem, shared ecosystem integration, verification, recovery, and approvals.
- `.github/ISSUE_TEMPLATE/config.yml` directs security reports away from public issues and points users to documentation.
- `.github/labels.yml` is the canonical area, type, size, priority, status, community, and compatibility taxonomy.
- `docs/LABELS.md` explains how maintainers and contributors apply that taxonomy consistently.
- `scripts/ci/sync_github_labels.py` validates and additively creates or updates canonical labels without deleting unrelated labels.
- `.github/workflows/sync-labels.yml` provides an explicit manual, dry-run-first label synchronization path with minimum GitHub permissions.
- `tests/test_repository_labels.py` protects label uniqueness, required taxonomy, template alignment, and the no-delete synchronization boundary.
- `pyproject.toml` declares the same MIT source license represented by `LICENSE`; separate commercial terms remain limited to separately provided managed offerings.

### Verification

The focused tests prove dependency release, approvals, resource return, node-failure reassignment, GitHub-event deduplication, full-repository scope, automatic-trigger safety, node-proposal explanations, all-PipeFail aggregation, zero-failure graphics, and repository-label controls.

No file exists only to imitate a dashboard. A module may report `planned` or `foundation` until a real backend service and verification path are connected.
