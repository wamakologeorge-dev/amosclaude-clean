# Amosclaud Pipeline Ecosystem

Amosclaud uses one control plane, one cooperation pipeline contract, and one PipeFail recovery trail. Existing services keep their specialized responsibilities, but they exchange tasks, events, artifacts, approvals, capacity, and failure evidence through the same ecosystem instead of replacing or disabling one another.

## Main-branch product policy

`main` remains the canonical product branch and deployment source. Feature branches exist only as temporary review and verification lanes. A pipeline change is not considered part of Amosclaud until its checks pass and it is merged into `main`; no parallel production branch or duplicate platform is created.

## Shared contract

Every cooperating component is attached to a pipeline ID and user scope:

1. The Agent or API creates a cooperation pipeline.
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
- `amoscloud_ai/api/routes/pipelines.py` mounts both contracts under one `/api/v1/pipelines` API family so they operate as one platform.
- `services/java-pod-runtime/Dockerfile` builds the reproducible non-root Java execution image.
- `services/java-pod-runtime/entrypoint.sh` executes Maven, Gradle-wrapper, or `javac` work and returns machine-readable success or PipeFail evidence.
- `web/control-plane.html`, `web/control-plane.js`, and `web/control-plane.css` expose the shared system to authenticated users without fabricating service health.
- The focused tests prove dependency release, approvals, resource return, and node-failure reassignment.

No file exists only to imitate a dashboard. A module may report `planned` or `foundation` until a real backend service and verification path are connected.
