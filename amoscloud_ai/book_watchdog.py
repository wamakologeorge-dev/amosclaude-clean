"""Amosclaud Book watchdog and Slapface preflight gate.

This module is intentionally repository-scoped. It stores only redacted,
human-readable engineering metadata under ``.Amosclaud/book/.runtime`` and
never persists credential values. Secret classification is confidence-based so
normal examples, placeholders, hashes, UUIDs, and environment-variable
references do not become false leak reports.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable

_RUNTIME_LOCK = RLock()
_SAFE_ACTOR = re.compile(r"[^A-Za-z0-9_.:@-]+")

# Values in these contexts are much more likely to be credentials than an
# arbitrary high-entropy string in source code.
_STRONG_SECRET_NAMES = re.compile(
    r"(?i)(?:^|[^A-Z0-9])(?:OPENAI_API_KEY|API_KEY|ACCESS_TOKEN|AUTH_TOKEN|"
    r"REFRESH_TOKEN|CLIENT_SECRET|PASSWORD|PRIVATE_KEY|SECRET_KEY|BEARER_TOKEN|"
    r"GITHUB_TOKEN|AWS_SECRET_ACCESS_KEY)(?:$|[^A-Z0-9])"
)
_ASSIGNMENT = re.compile(
    r"(?i)(?P<name>[A-Z][A-Z0-9_.-]{2,80})\s*[=:]\s*[\"']?(?P<value>[^\s,\"'}]{8,})"
)
_BEARER = re.compile(r"(?i)\bBearer\s+(?P<value>[A-Za-z0-9._~+/=-]{16,})")
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_GITHUB_TOKEN = re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b")
_OPENAI_STYLE = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
_AWS_ACCESS_ID = re.compile(r"\bAKIA[0-9A-Z]{16}\b")

_PLACEHOLDER_WORDS = {
    "changeme",
    "dummy",
    "example",
    "fake",
    "placeholder",
    "replace-me",
    "replace_me",
    "sample",
    "test",
    "your-key",
    "your_key",
    "yourkey",
}
_REFERENCE_MARKERS = (
    "${",
    "{{",
    "os.environ[",
    "os.getenv(",
    "process.env.",
    "secrets.",
    "secretref:",
)


class BookWatchdogError(ValueError):
    """Raised when the Book refuses repository work."""


@dataclass(frozen=True)
class SecretFinding:
    classification: str
    confidence: float
    kind: str
    line: int
    variable: str | None
    fingerprint: str
    reasons: tuple[str, ...]

    def safe_dict(self) -> dict[str, Any]:
        """Return metadata that cannot reconstruct the candidate secret."""
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _actor(value: str) -> str:
    cleaned = _SAFE_ACTOR.sub("-", str(value or "agent").strip()).strip("-._")
    return (cleaned or "agent")[:128]


def _fingerprint(value: str) -> str:
    # A short one-way fingerprint supports deduplication without storing the key.
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _looks_placeholder(value: str, full_line: str) -> bool:
    lowered = value.lower().strip("<>[](){}'\"")
    if any(marker.lower() in full_line.lower() for marker in _REFERENCE_MARKERS):
        return True
    if any(word in lowered for word in _PLACEHOLDER_WORDS):
        return True
    if lowered.startswith(("<", "${", "{{")):
        return True
    compact = re.sub(r"[^A-Za-z0-9]", "", value)
    if compact and len(set(compact.lower())) <= 2:
        return True
    return False


def _finding(
    *,
    value: str,
    line_number: int,
    line: str,
    variable: str | None,
    base_score: float,
    kind: str,
    reasons: list[str],
) -> SecretFinding | None:
    if _looks_placeholder(value, line):
        return None

    score = base_score
    if variable and _STRONG_SECRET_NAMES.search(variable):
        score += 0.22
        reasons.append("credential-bearing variable name")
    if len(value) >= 20:
        score += 0.05
        reasons.append("credential-sized literal")
    entropy = _entropy(value)
    if len(value) >= 20 and entropy >= 3.5:
        score += 0.08
        reasons.append("high-entropy literal")

    score = round(min(score, 0.99), 2)
    if score >= 0.90:
        classification = "confirmed_secret"
    elif score >= 0.75:
        classification = "probable_secret"
    elif score >= 0.45:
        classification = "suspicious"
    else:
        return None

    return SecretFinding(
        classification=classification,
        confidence=score,
        kind=kind,
        line=line_number,
        variable=variable,
        fingerprint=_fingerprint(value),
        reasons=tuple(dict.fromkeys(reasons)),
    )


def detect_secrets(text: str) -> list[SecretFinding]:
    """Classify credential-like literals without returning their values.

    Blocking classifications require multiple signals or a highly specific
    credential structure. ``suspicious`` findings are warnings only.
    """

    findings: dict[tuple[int, str, str], SecretFinding] = {}
    for line_number, raw_line in enumerate(str(text or "").splitlines(), 1):
        line = raw_line[:20_000]
        stripped = line.strip()
        if not stripped:
            continue

        variable: str | None = None
        assigned_value: str | None = None
        assignment = _ASSIGNMENT.search(line)
        if assignment:
            variable = assignment.group("name")
            assigned_value = assignment.group("value")
            if _STRONG_SECRET_NAMES.search(variable):
                candidate = _finding(
                    value=assigned_value,
                    line_number=line_number,
                    line=line,
                    variable=variable,
                    base_score=0.58,
                    kind="credential_assignment",
                    reasons=["literal assigned to a credential-bearing name"],
                )
                if candidate:
                    findings[(line_number, candidate.kind, candidate.fingerprint)] = candidate

        if _PRIVATE_KEY.search(line):
            value = stripped
            candidate = _finding(
                value=value,
                line_number=line_number,
                line=line,
                variable=variable,
                base_score=0.96,
                kind="private_key_material",
                reasons=["private-key header"],
            )
            if candidate:
                findings[(line_number, candidate.kind, candidate.fingerprint)] = candidate

        for match in _BEARER.finditer(line):
            candidate = _finding(
                value=match.group("value"),
                line_number=line_number,
                line=line,
                variable="Authorization",
                base_score=0.78,
                kind="bearer_token",
                reasons=["Bearer authorization literal"],
            )
            if candidate:
                findings[(line_number, candidate.kind, candidate.fingerprint)] = candidate

        for pattern, kind, score, reason in (
            (_GITHUB_TOKEN, "provider_token", 0.91, "provider-specific token structure"),
            (_OPENAI_STYLE, "api_key_literal", 0.66, "API-key-style secret structure"),
            (_JWT, "jwt_token", 0.76, "three-part JWT structure"),
            (_AWS_ACCESS_ID, "cloud_access_identifier", 0.63, "cloud credential identifier structure"),
        ):
            for match in pattern.finditer(line):
                candidate = _finding(
                    value=match.group(0),
                    line_number=line_number,
                    line=line,
                    variable=variable,
                    base_score=score,
                    kind=kind,
                    reasons=[reason],
                )
                if candidate:
                    findings[(line_number, candidate.kind, candidate.fingerprint)] = candidate

    return sorted(findings.values(), key=lambda item: (-item.confidence, item.line, item.kind))


def secret_verdict(text: str) -> dict[str, Any]:
    findings = detect_secrets(text)
    blocking = [
        finding
        for finding in findings
        if finding.classification in {"confirmed_secret", "probable_secret"}
    ]
    warnings = [finding for finding in findings if finding.classification == "suspicious"]
    return {
        "allowed": not blocking,
        "blocking_count": len(blocking),
        "warning_count": len(warnings),
        "findings": [finding.safe_dict() for finding in findings],
        "rule": (
            "Confirmed/probable credential exposure blocks repository work; "
            "suspicious text warns without blocking. Raw candidate values are never returned."
        ),
    }


class RepositoryBookWatchdog:
    """Repository-local Slapface state and safe watchdog sentence collector."""

    def __init__(self, repository_root: str | Path) -> None:
        self.repository_root = Path(repository_root).expanduser().resolve()
        self.book_root = self.repository_root / ".Amosclaud" / "book"
        self.runtime_root = self.book_root / ".runtime"
        self.handoff_path = self.runtime_root / "slapface.json"
        self.events_path = self.runtime_root / "watchdog.jsonl"

    def _inside_repository(self) -> None:
        if not self.repository_root.exists() or not self.repository_root.is_dir():
            raise BookWatchdogError("Amosclaud repository is unavailable")

    def _ensure_runtime(self) -> None:
        self._inside_repository()
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        # Keep watchdog runtime evidence out of Git history. Canonical Book
        # chapters/change reports remain normal repository files.
        git_exclude = self.repository_root / ".git" / "info" / "exclude"
        if git_exclude.parent.is_dir():
            try:
                existing = git_exclude.read_text(encoding="utf-8") if git_exclude.exists() else ""
                marker = ".Amosclaud/book/.runtime/"
                if marker not in existing.splitlines():
                    git_exclude.write_text(existing.rstrip() + "\n" + marker + "\n", encoding="utf-8")
            except OSError:
                pass

    def _load_handoff(self) -> dict[str, Any] | None:
        if not self.handoff_path.exists():
            return None
        try:
            value = json.loads(self.handoff_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "status": "blocked",
                "handoff_id": "invalid-slapface-state",
                "summary": "Slapface state is unreadable and must be repaired before repository work.",
                "chapter_link": ".Amosclaud/book/",
                "missing_pieces": ["Repair the Book Slapface state."],
            }
        return value if isinstance(value, dict) else None

    def record_sentence(self, *, actor: str, action: str, sentence: str, status: str) -> None:
        safe_sentence, _ = redact_book_text(sentence)
        safe_action, _ = redact_book_text(action, limit=200)
        if "[REDACTED]" in safe_sentence or "[REDACTED]" in safe_action:
            raise BookWatchdogError("Book refused to store credential-like text")
        self._ensure_runtime()
        row = {
            "at": _now(),
            "actor": _actor(actor),
            "action": safe_action,
            "status": status[:32],
            "sentence": safe_sentence,
        }
        with _RUNTIME_LOCK, self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")

    def block_handoff(
        self,
        *,
        actor: str,
        summary: str,
        chapter_link: str,
        missing_pieces: Iterable[str],
        reason: str = "unfinished_work",
    ) -> dict[str, Any]:
        safe_summary, _ = redact_book_text(summary)
        safe_link, _ = redact_book_text(chapter_link, limit=500)
        safe_missing = [redact_book_text(str(item), limit=1000)[0] for item in missing_pieces]
        if any("[REDACTED]" in value for value in [safe_summary, safe_link, *safe_missing]):
            raise BookWatchdogError("Slapface handoff cannot contain credential-like text")
        handoff_id = hashlib.sha256(
            f"{_now()}:{_actor(actor)}:{safe_summary}".encode("utf-8")
        ).hexdigest()[:20]
        value = {
            "status": "blocked",
            "handoff_id": handoff_id,
            "reason": reason,
            "actor": _actor(actor),
            "summary": safe_summary,
            "chapter_link": safe_link,
            "missing_pieces": safe_missing,
            "created_at": _now(),
        }
        self._ensure_runtime()
        with _RUNTIME_LOCK:
            self.handoff_path.write_text(
                json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        self.record_sentence(
            actor=actor,
            action="slapface-block",
            sentence=f"Work stopped: {safe_summary}",
            status="blocked",
        )
        return value

    def resolve_handoff(self, *, actor: str, handoff_id: str, evidence: Iterable[str]) -> dict[str, Any]:
        current = self._load_handoff()
        if not current or current.get("status") != "blocked":
            raise BookWatchdogError("There is no blocking Slapface handoff to resolve")
        if str(current.get("handoff_id")) != str(handoff_id):
            raise BookWatchdogError("Slapface handoff id does not match the active blocker")
        safe_evidence = [redact_book_text(str(item), limit=1500)[0] for item in evidence]
        if not safe_evidence:
            raise BookWatchdogError("Verified repair evidence is required")
        if any("[REDACTED]" in item for item in safe_evidence):
            raise BookWatchdogError("Repair evidence cannot contain credential-like text")
        current = {
            **current,
            "status": "resolved",
            "resolved_by": _actor(actor),
            "resolved_at": _now(),
            "evidence": safe_evidence,
        }
        self._ensure_runtime()
        with _RUNTIME_LOCK:
            self.handoff_path.write_text(
                json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        self.record_sentence(
            actor=actor,
            action="slapface-resolve",
            sentence="The missing prerequisite was repaired and Slapface released repository work.",
            status="resolved",
        )
        return current

    def preflight(self, *, actor: str, action: str, proposed_text: str = "") -> dict[str, Any]:
        """Return the one verdict every Amosclaud repository action must consult."""
        self._ensure_runtime()
        handoff = self._load_handoff()
        if handoff and handoff.get("status") == "blocked":
            return {
                "work_allowed": False,
                "slapface": True,
                "reason": "unfinished_handoff",
                "handoff": handoff,
                "message": (
                    "SLAPFACE: repository work is blocked. Read the linked Book chapter, "
                    "repair the listed missing pieces, record evidence, then retry."
                ),
            }

        secrets = secret_verdict(proposed_text) if proposed_text else {
            "allowed": True,
            "blocking_count": 0,
            "warning_count": 0,
            "findings": [],
            "rule": "No proposed text supplied for secret classification.",
        }
        if not secrets["allowed"]:
            kinds = sorted({str(item["kind"]) for item in secrets["findings"] if item["classification"] != "suspicious"})
            handoff = self.block_handoff(
                actor=actor,
                summary="A high-confidence credential exposure was detected before repository work could continue.",
                chapter_link=".Amosclaud/book/chapters/00-slapface.md#secret-safety",
                missing_pieces=[
                    "Remove the credential literal from the proposed repository change.",
                    "Use an environment variable or secret-management reference instead.",
                    "Rotate the credential if it may have been exposed outside the local editor.",
                    "Re-run Slapface and record clean verification evidence.",
                ],
                reason="probable_secret_exposure",
            )
            return {
                "work_allowed": False,
                "slapface": True,
                "reason": "probable_secret_exposure",
                "handoff": handoff,
                "secret_findings": secrets["findings"],
                "detected_kinds": kinds,
                "message": (
                    "SLAPFACE: Book found high-confidence credential-like material. "
                    "The value was not stored or returned. Repository work is blocked until repaired."
                ),
            }

        self.record_sentence(
            actor=actor,
            action=action,
            sentence=(
                "Book read the repository request and allowed it."
                if not secrets["warning_count"]
                else "Book allowed the repository request with a non-blocking suspicious-text warning."
            ),
            status="allowed_with_warning" if secrets["warning_count"] else "allowed",
        )
        return {
            "work_allowed": True,
            "slapface": False,
            "reason": None,
            "secret_findings": secrets["findings"],
            "message": (
                "Book read the request and allowed repository work."
                if not secrets["warning_count"]
                else "Book allowed repository work, but suspicious text should be reviewed."
            ),
        }

    def status(self) -> dict[str, Any]:
        handoff = self._load_handoff()
        return {
            "product": "Amosclaud Book",
            "role": "repository-watchdog",
            "scope": "this Amosclaud repository only",
            "slapface": handoff,
            "work_allowed": not bool(handoff and handoff.get("status") == "blocked"),
            "secret_policy": (
                "Book never stores credential values. Confirmed/probable secrets block; "
                "suspicious text warns without blocking."
            ),
        }


def redact_book_text(value: str, *, limit: int = 4000) -> tuple[str, int]:
    """Redact high-confidence secret literals before Book storage/display."""
    text = str(value or "")[: max(1, limit)]
    findings = detect_secrets(text)
    blocking_fingerprints = {
        item.fingerprint
        for item in findings
        if item.classification in {"confirmed_secret", "probable_secret"}
    }
    if not blocking_fingerprints:
        return text, 0

    redactions = 0
    lines: list[str] = []
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line_findings = [
            item for item in findings
            if item.line == line_number and item.fingerprint in blocking_fingerprints
        ]
        if not line_findings:
            lines.append(raw_line)
            continue
        # Never attempt to preserve the literal-bearing fragment: replace the
        # whole line, which is safer and still useful to a human reader.
        lines.append("[REDACTED: credential-like material removed by Amosclaud Book]")
        redactions += 1
    return "\n".join(lines), redactions


def repository_root_from_request_path(path: str) -> Path | None:
    """Resolve an Amosclaud repository id from an API path without touching GitHub."""
    match = re.match(r"^/api/v1/repositories/(?P<repository_id>[1-9][0-9]*)(?:/|$)", path)
    if not match:
        return None
    root = Path(os.getenv("REPOSITORY_STORAGE_PATH", "data/repositories")).expanduser().resolve()
    candidate = (root / match.group("repository_id")).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate
