"""
Amosclaude-AI Issue Bot
-----------------------
Responds to GitHub Issue comments automatically using the Claude API.

Behaviour
~~~~~~~~~
1. Reads the triggering issue comment from environment variables injected by
   the GitHub Actions workflow.
2. If the comment asks for help / a fix and no filename is mentioned, it replies
   asking the user to provide the filename.
3. If a filename is mentioned (or was provided in a previous bot comment), it
   reads that file from the repository, sends it to Claude together with the
   user's request, and posts the suggested fix as a new issue comment.
4. If Claude returns an actual code fix, it creates a new branch, commits the
   fix, and opens a pull request – all via the GitHub REST API using the
   built-in GITHUB_TOKEN (no extra permissions required).

Required environment variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
GITHUB_TOKEN          – provided automatically by GitHub Actions
ANTHROPIC_API_KEY     – your Anthropic / Claude key (repository secret)
GITHUB_REPOSITORY     – owner/repo, e.g. "wamakologeorge-dev/amosclaude-clean"
ISSUE_NUMBER          – integer issue number
COMMENT_BODY          – full text of the triggering comment
COMMENT_AUTHOR        – login of the person who wrote the comment
"""

from __future__ import annotations

import os
import re
import sys
import textwrap
import time
from pathlib import Path
from typing import Optional

import anthropic
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GITHUB_REPOSITORY = os.environ["GITHUB_REPOSITORY"]
ISSUE_NUMBER = int(os.environ["ISSUE_NUMBER"])
COMMENT_BODY = os.environ.get("COMMENT_BODY", "")
COMMENT_AUTHOR = os.environ.get("COMMENT_AUTHOR", "")

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")
BOT_SIGNATURE = "\n\n---\n*\U0001f916 Amosclaude-AI \u2013 automated response*"

# Truncation limits for issue comment output
MAX_CODE_PREVIEW_LENGTH = 3000
MAX_RESPONSE_LENGTH = 2000

# Directories to skip during file search
_SKIP_DIRS = {".git", "__pycache__", "node_modules", "venv", ".venv", ".tox", "dist", "build"}

GH_API = "https://api.github.com"
GH_HEADERS = {
    "Authorization": "Bearer " + GITHUB_TOKEN,
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Keywords that signal a request for a code fix / review
FIX_KEYWORDS = re.compile(
    r"\b(fix|bug|error|broken|crash|fail|issue|problem|help|repair|debug|wrong|incorrect)\b",
    re.IGNORECASE,
)

# Pattern to extract a filename from a comment, e.g. "fix src/foo.py" or
# "the file is tests/bar.py" or just "bar.py"
FILENAME_PATTERN = re.compile(
    r"(?:file(?:\s+is)?[:\s]+)?([a-zA-Z0-9_./\\-]+\.[a-zA-Z0-9]+)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------


def gh_post_comment(body: str) -> dict:
    """Post a comment on the issue."""
    url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/issues/{ISSUE_NUMBER}/comments"
    resp = requests.post(url, headers=GH_HEADERS, json={"body": body}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def gh_get_issue() -> dict:
    """Return issue metadata."""
    url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/issues/{ISSUE_NUMBER}"
    resp = requests.get(url, headers=GH_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def gh_get_issue_comments() -> list:
    """Return all comments on the issue (oldest first), handling pagination."""
    url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/issues/{ISSUE_NUMBER}/comments"
    all_comments: list = []
    page = 1
    while True:
        resp = requests.get(
            url,
            headers=GH_HEADERS,
            params={"per_page": 100, "page": page},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        all_comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return all_comments


def gh_get_default_branch() -> str:
    url = f"{GH_API}/repos/{GITHUB_REPOSITORY}"
    resp = requests.get(url, headers=GH_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()["default_branch"]


def gh_get_ref_sha(ref: str) -> str:
    """Return the SHA of a branch ref."""
    url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/git/ref/heads/{ref}"
    resp = requests.get(url, headers=GH_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()["object"]["sha"]


def gh_create_branch(branch: str, sha: str) -> None:
    url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/git/refs"
    resp = requests.post(
        url,
        headers=GH_HEADERS,
        json={"ref": f"refs/heads/{branch}", "sha": sha},
        timeout=30,
    )
    resp.raise_for_status()


def gh_get_file(path: str, branch: str) -> tuple:
    """Return (decoded_content, sha) for a file on a branch."""
    import base64

    url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/contents/{path}"
    resp = requests.get(url, headers=GH_HEADERS, params={"ref": branch}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return content, data["sha"]


def gh_update_file(path: str, branch: str, sha: str, content: str, message: str) -> None:
    import base64

    url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/contents/{path}"
    encoded = base64.b64encode(content.encode()).decode()
    resp = requests.put(
        url,
        headers=GH_HEADERS,
        json={
            "message": message,
            "content": encoded,
            "sha": sha,
            "branch": branch,
        },
        timeout=30,
    )
    resp.raise_for_status()


def gh_create_pr(head: str, base: str, title: str, body: str) -> str:
    """Create a PR and return its HTML URL."""
    url = f"{GH_API}/repos/{GITHUB_REPOSITORY}/pulls"
    resp = requests.post(
        url,
        headers=GH_HEADERS,
        json={"title": title, "body": body, "head": head, "base": base},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["html_url"]


# ---------------------------------------------------------------------------
# File resolution helpers
# ---------------------------------------------------------------------------


def find_file_in_repo(name: str) -> Optional[str]:
    """
    Search the local checkout for *name* (exact path or basename match).
    Returns the relative path from the repo root, or None.
    Skips common noise directories (.git, __pycache__, node_modules, etc.).
    """
    repo_root = Path(__file__).resolve().parent.parent
    # Exact path first
    candidate = repo_root / name
    if candidate.is_file():
        return str(candidate.relative_to(repo_root))
    # Basename search, skipping noise directories
    for path in repo_root.rglob(name):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.is_file():
            return str(path.relative_to(repo_root))
    return None


def extract_filenames(text: str) -> list:
    """Extract plausible filenames from arbitrary text."""
    raw = FILENAME_PATTERN.findall(text)
    # Filter out things like "e.g." or lone extensions
    return [f for f in raw if "." in f and len(f) > 3]


# ---------------------------------------------------------------------------
# Claude helpers
# ---------------------------------------------------------------------------

_SYSTEM_FIX = textwrap.dedent("""\
    You are Amosclaude-AI, an expert software engineer and automated assistant
    embedded in a GitHub repository.

    When given a file and a bug report / request, you must:
    1. Analyse the problem.
    2. Produce a corrected version of the **entire file** (no truncation).
    3. After the corrected file, add a section headed "## Explanation" that
       briefly explains what you changed and why.

    Wrap the corrected file content in a fenced code block whose language tag
    matches the file type (e.g. ```python ... ```).
    Do not add any text before the code block - start immediately with ```.
""")

_SYSTEM_TRIAGE = textwrap.dedent("""\
    You are Amosclaude-AI, a helpful GitHub bot.
    Analyse the issue and comment below, then write a concise, friendly reply
    that either:
    - Answers a question directly, or
    - Explains what information you still need (e.g. which file to fix).
    Keep the reply under 300 words and use GitHub-flavoured Markdown.
""")


def claude_fix_file(file_path: str, file_content: str, request: str) -> str:
    """Ask Claude to fix *file_content* based on *request*."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    user_msg = (
        f"**File:** `{file_path}`\n\n"
        f"**Request:** {request}\n\n"
        f"**Current file content:**\n```\n{file_content}\n```"
    )
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=_SYSTEM_FIX,
        messages=[{"role": "user", "content": user_msg}],
    )
    return resp.content[0].text


def claude_triage(issue_title: str, issue_body: str, comment: str) -> str:
    """Ask Claude to write a helpful triage reply."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    user_msg = (
        f"**Issue title:** {issue_title}\n\n"
        f"**Issue body:**\n{issue_body}\n\n"
        f"**Comment to respond to:**\n{comment}"
    )
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=512,
        system=_SYSTEM_TRIAGE,
        messages=[{"role": "user", "content": user_msg}],
    )
    return resp.content[0].text


# ---------------------------------------------------------------------------
# Fix extraction
# ---------------------------------------------------------------------------

FENCED_CODE_BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def extract_fixed_code(claude_response: str) -> Optional[str]:
    """Return the first fenced code block from Claude's response, or None."""
    match = FENCED_CODE_BLOCK.search(claude_response)
    return match.group(1) if match else None


def extract_explanation(claude_response: str) -> str:
    """Return the explanation section from Claude's response."""
    idx = claude_response.find("## Explanation")
    if idx != -1:
        return claude_response[idx:]
    # Fallback: everything after the code block
    match = FENCED_CODE_BLOCK.search(claude_response)
    if match:
        return claude_response[match.end():].strip()
    return ""


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------


def already_asked_for_filename() -> bool:
    """Return True if the bot already asked for a filename on this issue."""
    for comment in gh_get_issue_comments():
        body = comment.get("body", "")
        if BOT_SIGNATURE in body and "filename" in body.lower():
            return True
    return False


def find_previously_mentioned_file() -> Optional[str]:
    """
    Scan all previous comments for a filename that exists in the repo.
    Returns the repo-relative path or None.
    """
    for comment in gh_get_issue_comments():
        body = comment.get("body", "")
        for fname in extract_filenames(body):
            resolved = find_file_in_repo(fname)
            if resolved:
                return resolved
    return None


def run() -> None:
    print(f"[issue-bot] Processing issue #{ISSUE_NUMBER}, comment by @{COMMENT_AUTHOR}")
    print(f"[issue-bot] Comment: {COMMENT_BODY[:200]}")

    # Ignore comments from bots (including ourselves)
    if COMMENT_AUTHOR.endswith("[bot]") or COMMENT_AUTHOR == "github-actions":
        print("[issue-bot] Ignoring bot comment.")
        return

    issue = gh_get_issue()
    issue_title = issue.get("title", "")
    issue_body = issue.get("body", "") or ""

    # -----------------------------------------------------------------------
    # Step 1 - Determine if there is a fix request in this comment
    # -----------------------------------------------------------------------
    is_fix_request = bool(FIX_KEYWORDS.search(COMMENT_BODY))

    # Extract filenames from the current comment
    mentioned_files = extract_filenames(COMMENT_BODY)
    resolved_file: Optional[str] = None
    for fname in mentioned_files:
        resolved_file = find_file_in_repo(fname)
        if resolved_file:
            break

    # -----------------------------------------------------------------------
    # Step 2 - If no file mentioned, check previous comments
    # -----------------------------------------------------------------------
    if resolved_file is None and is_fix_request:
        resolved_file = find_previously_mentioned_file()

    # -----------------------------------------------------------------------
    # Step 3a - No file found: ask for it (once)
    # -----------------------------------------------------------------------
    if resolved_file is None and is_fix_request:
        if not already_asked_for_filename():
            reply = (
                f"Hi @{COMMENT_AUTHOR}! \U0001f44b\n\n"
                "I'd love to help fix this. Could you please tell me **which file** "
                "you'd like me to look at?\n\n"
                "Just mention the filename in your next comment, for example:\n"
                "> `src/amoscloud_ai/builder.py`\n\n"
                "I'll analyse it and propose a fix automatically."
                + BOT_SIGNATURE
            )
            gh_post_comment(reply)
            print("[issue-bot] Asked for filename.")
        else:
            print("[issue-bot] Already asked for filename, skipping duplicate.")
        return

    # -----------------------------------------------------------------------
    # Step 3b - No fix request: general triage / answer
    # -----------------------------------------------------------------------
    if not is_fix_request:
        if not ANTHROPIC_API_KEY:
            print("[issue-bot] No ANTHROPIC_API_KEY set; skipping triage reply.")
            return
        triage_reply = claude_triage(issue_title, issue_body, COMMENT_BODY)
        gh_post_comment(triage_reply + BOT_SIGNATURE)
        print("[issue-bot] Posted triage reply.")
        return

    # -----------------------------------------------------------------------
    # Step 4 - We have a file: ask Claude to fix it
    # -----------------------------------------------------------------------
    print(f"[issue-bot] Will attempt fix for file: {resolved_file}")

    if not ANTHROPIC_API_KEY:
        gh_post_comment(
            f"Hi @{COMMENT_AUTHOR}! I found the file `{resolved_file}` but "
            "the `ANTHROPIC_API_KEY` secret is not configured in this repository, "
            "so I cannot generate a fix right now. Please add it in "
            "**Settings \u2192 Secrets \u2192 Actions**." + BOT_SIGNATURE
        )
        return

    default_branch = gh_get_default_branch()
    try:
        file_content, file_sha = gh_get_file(resolved_file, default_branch)
    except requests.HTTPError as exc:
        gh_post_comment(
            f"Hi @{COMMENT_AUTHOR}! I tried to read `{resolved_file}` but got "
            f"an error: `{exc}`. Please double-check the filename." + BOT_SIGNATURE
        )
        return

    combined_request = f"{issue_title}\n\n{issue_body}\n\nComment: {COMMENT_BODY}"
    claude_response = claude_fix_file(resolved_file, file_content, combined_request)

    fixed_code = extract_fixed_code(claude_response)
    explanation = extract_explanation(claude_response)

    # -----------------------------------------------------------------------
    # Step 5 - If Claude produced a code fix, commit it to a new branch + PR
    # -----------------------------------------------------------------------
    pr_url: Optional[str] = None
    if fixed_code and fixed_code.strip() != file_content.strip():
        try:
            branch_name = (
                f"amosclaude-fix/issue-{ISSUE_NUMBER}-{int(time.time())}"
            )
            base_sha = gh_get_ref_sha(default_branch)
            gh_create_branch(branch_name, base_sha)

            _, new_sha = gh_get_file(resolved_file, branch_name)
            commit_msg = f"fix: auto-fix for issue #{ISSUE_NUMBER} - {issue_title[:60]}"
            gh_update_file(resolved_file, branch_name, new_sha, fixed_code, commit_msg)

            pr_body = (
                f"Automated fix generated by **Amosclaude-AI** for "
                f"[#{ISSUE_NUMBER}](../../issues/{ISSUE_NUMBER}).\n\n"
                f"{explanation}"
            )
            pr_url = gh_create_pr(
                head=branch_name,
                base=default_branch,
                title=f"[Amosclaude-AI] Fix for issue #{ISSUE_NUMBER}",
                body=pr_body,
            )
            print(f"[issue-bot] Created PR: {pr_url}")
        except Exception as exc:
            print(f"[issue-bot] WARNING: Could not create PR: {exc}")

    # -----------------------------------------------------------------------
    # Step 6 - Post the summary comment on the issue
    # -----------------------------------------------------------------------
    lines = [f"Hi @{COMMENT_AUTHOR}! Here's my analysis of `{resolved_file}`:\n"]
    if fixed_code:
        truncated_code = fixed_code[:MAX_CODE_PREVIEW_LENGTH]
        if len(fixed_code) > MAX_CODE_PREVIEW_LENGTH:
            truncated_code += "\n... (truncated – see the PR for the full diff)"
        lines.append(f"```\n{truncated_code}\n```")
        if explanation:
            lines.append(f"\n{explanation}")
        if pr_url:
            lines.append(f"\n\u2705 I've opened a pull request with this fix: {pr_url}")
        else:
            lines.append(
                "\n\u26a0\ufe0f I generated a fix but could not open a PR automatically. "
                "You can apply the code above manually."
            )
    else:
        truncated_response = claude_response[:MAX_RESPONSE_LENGTH]
        if len(claude_response) > MAX_RESPONSE_LENGTH:
            truncated_response += "\n... (response truncated)"
        lines.append(truncated_response)

    gh_post_comment("\n".join(lines) + BOT_SIGNATURE)
    print("[issue-bot] Done.")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"[issue-bot] FATAL: {exc}", file=sys.stderr)
        # Try to post a graceful error comment so the issue is not silent
        try:
            gh_post_comment(
                "\u26a0\ufe0f **Amosclaude-AI encountered an unexpected error** while processing "
                f"this comment:\n```\n{exc}\n```\nPlease check the workflow logs."
                + BOT_SIGNATURE
            )
        except Exception:
            pass
        sys.exit(1)
