# PR #1224 re-validation

Main was broken by a circular import (#1205) when this PR's CI first ran.
Fix merged in #1231 (commit 3f13796). This commit re-triggers CI against healed main.

- Date: 2026-08-28
- Evidence: `python -c "import amoscloud_ai.api.routes"` passes on main @ 3f13796
