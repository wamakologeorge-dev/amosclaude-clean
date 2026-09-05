# Amosclaud Crash Shield rule reference

| Rule | Severity | Detection |
| --- | --- | --- |
| PY000 | critical | Python syntax error |
| PY001 | high | Module-level `os.environ[...]` startup hazard |
| PY002 | critical | `raise SystemExit` |
| PY003 | high | `while True` with no visible `break` |
| PY004 | critical | Process exit calls such as `sys.exit()` or `os._exit()` |
| PY005 | high | Subprocess call without a timeout |
| PY006 | high | `requests` HTTP call without a timeout |
| PY007 | high | `httpx` HTTP call without a timeout |
| JS000 | critical | Node syntax failure |
| JS001 | critical | `process.exit()` |
| JS002 | high | `JSON.parse(process.env...)` startup/config hazard |
| JS003 | medium | `while(true)` loop requiring review |

Crash Shield findings identify code that deserves review; they do not prove that a crash will occur. The first rollout reports findings without failing the workflow so the existing codebase can be baselined safely.
