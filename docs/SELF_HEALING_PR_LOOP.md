# Amosclaud same-PR self-healing loop

The self-healing workflow closes the gap between a locally verified repair and the
complete GitHub Actions matrix that runs after the repair commit is pushed.

## Behavior

1. A trusted same-repository pull-request workflow completes with `failure`.
2. The trusted default-branch callback workflow reads the failed run and captures
   its failed-log tail.
3. One deduplicated `@amosclaud fix` command is posted for that exact head SHA.
4. Amosclaud checks out the existing pull-request branch, diagnoses the evidence,
   edits the responsible files, runs focused verification, and commits only a
   verified correction.
5. The new commit starts the complete Actions matrix again.
6. A later failed head can trigger another callback in the same pull request.

## Safety boundaries

- Fork pull requests and untrusted author associations cannot trigger the
  privileged callback.
- A head SHA receives at most one callback even when several workflows fail.
- A pull request receives no more than five automated callback attempts.
- Reaching the limit produces a human-action blocker rather than an infinite
  loop or a false success claim.
- The callback never merges a pull request and never removes required checks.
- The broad `AMOSCLAUD_GITHUB_TOKEN` is required only after the callback policy
  tests pass and the workflow has confirmed a same-repository pull-request run.
