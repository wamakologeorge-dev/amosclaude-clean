from __future__ import annotations


MAX_PUBLIC_COMMENT = 700
KEY_MARKERS = (
    "**status:**",
    "**runtime status:**",
    "**autonomous status:**",
    "**result:**",
    "**compilation:**",
    "**risk:**",
    "**error:**",
    "**files changed:**",
    "**changed files:**",
    "**tests:**",
    "**pull request:**",
    "**commit:**",
    "**high:**",
    "**medium:**",
    "**low:**",
    "approval issue:",
    "decision:",
)
RECOMMENDATIONS = {"**APPROVE**", "**CHANGES REQUESTED**", "**NEEDS HUMAN REVIEW**"}


def compact_public_comment(body: str) -> str:
    """Keep routine GitHub issue comments short while preserving decisive evidence.

    Full execution evidence remains available in Actions logs, PR checks, and artifacts.
    Security/privacy notices that are already short are left unchanged. On-demand workflow
    boards and autonomous plans are intentionally compact and must retain their hidden
    issue-memory marker, so they are preserved as-is.
    """
    text = (body or "").strip()
    if text.startswith("### Amosclaud — Workflow Status"):
        return text[:1800]
    if text.startswith("### Amosclaud — Autonomous Plan"):
        return text[:2400]
    if not text or len(text) <= MAX_PUBLIC_COMMENT:
        return text

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return text[:MAX_PUBLIC_COMMENT]

    selected: list[str] = [lines[0]]
    for line in lines[1:]:
        lowered = line.lower()
        if any(marker in lowered for marker in KEY_MARKERS) or line in RECOMMENDATIONS:
            if line not in selected:
                selected.append(line)
        if len(selected) >= 7:
            break

    if len(selected) == 1:
        selected.extend(lines[1:4])

    selected.append("Details: see GitHub Actions / PR checks.")
    compact = "\n\n".join(selected)
    return compact[:MAX_PUBLIC_COMMENT]
