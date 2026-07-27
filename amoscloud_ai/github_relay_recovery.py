"""Retry durable GitHub issue comments that could not be delivered earlier."""

from __future__ import annotations

from amoscloud_ai import github_issue_commands


def retry_pending_relays(limit: int = 100) -> dict[str, int]:
    """Retry pending relay rows in place without creating duplicate comments."""
    attempted = 0
    delivered = 0
    still_pending = 0
    with github_issue_commands._commands_db() as db:
        rows = db.execute(
            """SELECT id,command_id,repository,issue_number,body
               FROM github_issue_relays
               WHERE state='pending'
               ORDER BY created_at LIMIT ?""",
            (max(1, min(limit, 500)),),
        ).fetchall()
    for row in rows:
        record = github_issue_commands._record(str(row["command_id"]))
        account_id = int(record["account_id"]) if record and record.get("account_id") else None
        token = github_issue_commands._relay_token(account_id)
        attempted += 1
        if not token:
            still_pending += 1
            continue
        ok, detail = github_issue_commands._post_comment(
            str(row["repository"]),
            int(row["issue_number"]),
            str(row["body"]),
            token,
        )
        github_issue_commands._set_relay_state(
            str(row["id"]),
            "delivered" if ok else "pending",
            detail,
        )
        if ok:
            delivered += 1
        else:
            still_pending += 1
    return {
        "attempted": attempted,
        "delivered": delivered,
        "pending": still_pending,
    }
