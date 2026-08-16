# Amosclaud Agent Levels

`AMOSCLAUD-TOOL-SOVEREIGNTY-POLICY:v1`

## The problem this fixes

The agent's level used to be one line:

```python
return _bounded_level(os.getenv("AMOSCLAUD_AUTONOMOUS_LEVEL", "1"))
```

`AMOSCLAUD_AUTONOMOUS_LEVEL` appeared in exactly two places in the repository:
that read, and a test that set it to `3200`. Nothing ever wrote it, nothing ever
checked it, and the ceiling was 5000. The level changed the agent's behaviour —
it selects the curriculum lesson — but it was never connected to anything the
agent could actually do.

So "can the agent raise its own level?" had an uncomfortable answer: yes,
instantly, by setting a variable. That was the only method available, because no
other method existed.

## What a level means now

**A level is a count of capabilities that survived an outside check.**

Each capability is recorded as an *attestation*: a claim, plus a command that
re-proves it. The level is produced by running those commands. Not by reading a
stored number, and not by asking the agent.

```bash
python scripts/ci/agent_level_report.py
```

## Rules that make the number hard to fake

| Rule | Why |
|---|---|
| No oracle command, no credit | A claim with no way to check it is a wish |
| An oracle that cannot fail earns nothing | `true`, `echo ok`, `exit 0` measure nothing |
| Verdicts are never remembered | A capability that regressed is not a capability |
| The same claim twice is still one capability | Repetition is not progress |
| A declared level above the earned one is reported as an unearned gap | The lie is shown, not honoured |

The last rule matters most. Setting `AMOSCLAUD_AUTONOMOUS_LEVEL=4999` no longer
produces a level-4999 agent. It produces a report saying `declared 4999, earned
3, unearned gap 4996, honest false`.

## What counts as cheating

Written down before the work started, so the definition could not be adjusted to
fit the result. The full pre-registration lists ten failure modes; the ones that
bite most often:

- **Editing the scorer** in the same change that claims the gain.
- **Weakening tests** — deletions, `skip`, `xfail`, loosened assertions.
- **Hardcoding the benchmark** instead of solving the general case.
- **Tautological tests** that mock the thing under test and assert the mock ran.
- **False green from a fat environment** — passing only because the developer's
  machine has dependencies the real target lacks.
- **Suppressing the signal** — `continue-on-error`, `|| true`, ignore lists.

## The current ledger

Recorded in `amosclaud_ci/agent_level_ledger.jsonl`. Re-verified on demand;
today's outcome:

| Capability | Earned |
|---|---|
| `github-workflow-rejection-detection` | yes |
| `thin-environment-import-safety` | yes |
| `earned-level-integrity` | yes |
| `repository-workflows-load-on-github` | **no** — nine files still unloadable |

Three earned. The fourth is honestly refused: repairing it needs a `workflows:
write` permission the agent does not hold. A ledger that reported four would be
the exact thing this system exists to prevent.

## Adding a capability

1. Write down the claim and the command that proves it.
2. Make sure the command can fail. Break the capability on purpose and watch it
   go red.
3. Prefer an oracle the agent cannot author — a real interpreter, a real
   environment, an outside service's verdict — over a test you wrote yourself.
4. Record it, then re-verify.
