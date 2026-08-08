# Amosclaud Java Pod Runtime

This directory contains the execution image used when an Amosclaud cooperation pipeline needs Java. It is not a second orchestration system: the Control Plane assigns the pod to a registered execution node, creates a bounded resource lease, and records lifecycle events in the pipeline's existing evidence trail.

## Why each file exists

- `Dockerfile` creates the reproducible, non-root Java 21 runtime used by execution nodes. Maven is included; Gradle projects use their repository-owned Gradle wrapper.
- `entrypoint.sh` selects Maven, Gradle, or `javac`, executes the build, copies JAR/WAR outputs into `/artifacts`, and writes either `result.json` or `pipefail.json` for the common pipeline evidence system.

## Runtime contract

The node mounts the selected pipeline workspace at `/workspace` and its artifact volume at `/artifacts`. The launch specification comes from:

`GET /api/v1/pipelines/cooperation/runtime/java-pods/{pod_id}/launch-spec`

The node reports start, completion, or failure to the same runtime API. Completion releases the resource lease. Retryable failure is handled by PipeFail, which can assign the pod to another healthy node without separating it from the original pipeline.

Production launchers must enforce the security fields in the launch specification: non-root execution, read-only root filesystem, dropped Linux capabilities, no-new-privileges, resource limits, and the requested network policy.
