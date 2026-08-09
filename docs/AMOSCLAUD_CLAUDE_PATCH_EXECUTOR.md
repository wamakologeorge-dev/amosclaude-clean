# Amosclaud Native Ollama Patch Routing

**Contract:** `AMOSCLAUD-OLLAMA-PATCH-CONTRACT:v2`

The historical Claude-named workflow files remain only as compatibility entry
points for existing commands. They no longer call Anthropic or any other external
model provider. Every accepted patch command is routed to the existing Amosclaud
Repair Control Plane, which selects the configured Ollama service first.

## Compatible commands

```text
@amosclaud patch <bounded engineering objective>
@amosclaud ai-fix <bounded engineering objective>
@amosclaud claude-fix <bounded engineering objective>
```

The last alias is retained only to avoid breaking old instructions. It does not
select Claude. An empty objective is rejected.

Normal `@amosclaud fix ...` commands and structured owner directives continue to
use the same native repair path.

## Ollama configuration

Repository secrets and variables used by the native Repair Control Plane:

```text
OLLAMA_API_KEY=<configured Ollama service key>
OLLAMA_URL=<configured Ollama endpoint>
OLLAMA_MODEL=<owner-selected Ollama model>
```

When `OLLAMA_API_KEY` is present, the control plane sets the repair provider to
`ollama-cloud`, uses `OLLAMA_URL`, and selects `OLLAMA_MODEL`. The Amosclaud
gateway remains a fallback only when the Ollama configuration is unavailable.

## Trusted routing boundary

1. The issue-comment dispatcher checks out trusted default-branch code.
2. The parser authenticates the author association and requires a nonempty,
   bounded objective.
3. The dispatcher resolves the exact open same-repository PR head.
4. Forks, moved heads, closed PRs, and PRs whose head is the protected default
   branch are rejected.
5. The dispatcher starts `amosclaud-repair-control-plane.yml` with the exact SHA,
   PR number, Ollama provider label, and bounded objective evidence.
6. The Repair Control Plane reproduces the failure, creates a candidate through
   the native Ollama-first model route, removes model credentials for verification,
   verifies the changed-file set, and publishes only a validated repair.
7. It never merges automatically and never force-pushes.

## Retired external executor

`.github/scripts/ai_patch_executor.py` is a fail-closed compatibility guard. It:

- has no model HTTP client;
- receives no external model key;
- reads no pull-request source or symlink targets;
- generates no patch;
- commits and pushes nothing;
- returns `NATIVE_OLLAMA_REPAIR_REQUIRED` when invoked directly.

This prevents the earlier Anthropic-specific path from being restored silently.
