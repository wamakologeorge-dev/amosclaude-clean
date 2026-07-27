# Autonomous Engineering Workforce Delivery Checklist

Keep the workforce disabled for production write traffic until each applicable item is verified.

## Control plane

- [ ] Database volume is durable and backed up.
- [ ] Redis/Celery broker, worker, and worker recovery are operational.
- [ ] Connected GitHub OAuth tokens are encrypted with the production key.
- [ ] Required GitHub scopes and organization approval are verified.
- [ ] Model runtime is configured for write-capable engineering tasks.
- [ ] Global Task Router credits, ownership checks, and audit events are operational.

## Execution

- [ ] Deterministic `RuntimeExecutor` uses the locked-down runner image.
- [ ] Repository commands do not execute in the public API process.
- [ ] Project processes receive no platform database, billing, auth, model, or GitHub credentials.
- [ ] CPU, memory, PID, capability, filesystem, timeout, and network limits are enforced.
- [ ] Work branches cannot resolve to protected branch names.
- [ ] Base-branch movement blocks publication.
- [ ] Verification evidence and verification IDs are required.

## GitHub delivery

- [ ] Branch protection and required checks are enabled.
- [ ] Draft pull requests are created successfully.
- [ ] Force push remains disabled.
- [ ] Automatic merge remains disabled.
- [ ] Human final sign-off is documented.
- [ ] A failed pull-request creation leaves protected branches unchanged.

## Edge runners

- [ ] Runner implements the repository task claim/completion contract.
- [ ] Runner advertises `engineering_workforce_v1` only after isolation review.
- [ ] Runner advertises only modes it can execute.
- [ ] Runner credentials can be rotated and revoked.
- [ ] Offline and revoked runners are not scheduled.
- [ ] Edge failure cannot downgrade to arbitrary host execution.

## Software assets

- [ ] Telemetry tokens are stored in an external secret manager.
- [ ] Telemetry is delivered only over HTTPS.
- [ ] No customer records or secrets are included in telemetry.
- [ ] Token rotation is tested.
- [ ] Stale, degraded, and offline states are tested.
- [ ] Portable manifests contain no credentials.

## Incident readiness

- [ ] Emergency pause procedure exists.
- [ ] Audit events can be correlated by delegation, task, bucket, branch, commit, and verification ID.
- [ ] Rollback checkpoint is present in every write task.
- [ ] Failure evidence is retained without secret values.
- [ ] A human can cancel every unstarted delegated task.
