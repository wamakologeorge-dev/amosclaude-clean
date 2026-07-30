"""Verified repair memory and bounded Level 1-5 capability progression."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

SCHEMA_VERSION = 1
MAX_LEVEL = 5
MAX_TECHNIQUES = 1000
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|private[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"\b(?:sk|gh[pousr]|github_pat|amos_[a-z]+)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)authorization:\s*bearer\s+\S+"),
)
_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z]:)?(?:[./\\][A-Za-z0-9_.-]+){2,}(?![A-Za-z0-9_])"
)
_SIGNAL_PATTERNS = (
    re.compile(r"\b(?:HTTP|status)\s*[=:]?\s*([1-5]\d\d)\b", re.I),
    re.compile(r"\b([A-Z]\d{3,4})\b"),
    re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Failure))\b"),
    re.compile(
        r"(?i)\b(redirect_uri_mismatch|startup_failure|permission denied|would reformat|"
        r"import order|missing final newline|trailing whitespace|yaml tabs|unpinned action|"
        r"json syntax|python syntax|shell syntax|timeout|timed out|authentication failed|"
        r"invalid or revoked|connection refused|module not found|assertion failed|test failed|"
        r"build failed|deploy failed|health check failed)\b"
    ),
)
_STOPWORDS = {
    "amosclaud",
    "candidate",
    "changed",
    "command",
    "error",
    "failed",
    "failure",
    "github",
    "issue",
    "output",
    "repair",
    "repository",
    "result",
    "status",
    "this",
    "using",
    "verification",
    "with",
    "would",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def sanitize(value: str, limit: int = 40_000) -> str:
    text = str(value or "").replace("\x00", " ")[:limit]
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return _PATH_PATTERN.sub(" <path> ", text)


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z][a-z0-9_-]{2,}", sanitize(value).lower())
        if token not in _STOPWORDS and not token.isdigit()
    }


def diagnostic_signals(value: str) -> list[str]:
    clean = sanitize(value)
    signals: set[str] = set()
    for pattern in _SIGNAL_PATTERNS:
        for match in pattern.findall(clean):
            if isinstance(match, tuple):
                match = next((item for item in match if item), "")
            item = re.sub(r"\s+", "-", str(match).strip().lower())
            if item:
                signals.add(item)
    if not signals:
        signals.update(sorted(_tokens(clean))[:16])
    return sorted(signals)[:32]


def _file_kinds(paths: Iterable[str]) -> list[str]:
    kinds: set[str] = set()
    for raw in paths:
        path = Path(str(raw))
        kinds.add(path.suffix.lower() or path.name.lower())
    return sorted(item for item in kinds if item)[:20]


def _verification_names(results: Iterable[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            sanitize(str(item.get("name") or ""), 120).strip().lower()
            for item in results
            if isinstance(item, dict) and item.get("name")
        }
    )[:30]


def _fingerprint(signals: Sequence[str], file_kinds: Sequence[str]) -> str:
    payload = json.dumps(
        {"signals": sorted(set(signals)), "file_kinds": sorted(set(file_kinds))},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _default_catalog() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _now(),
        "capability": {
            "level": 1,
            "max_level": MAX_LEVEL,
            "unique_techniques": 0,
            "successful_reuses": 0,
            "failed_attempts": 0,
            "last_unlock_at": None,
        },
        "techniques": [],
    }


def default_catalog_path(repository: Path | None = None) -> Path:
    if value := os.getenv("AMOSCLAUD_REPAIR_MEMORY_CATALOG", "").strip():
        return Path(value).expanduser()
    if value := os.getenv("AMOSCLAUD_REPAIR_MEMORY_HOME", "").strip():
        return Path(value).expanduser() / "catalog.json"
    if value := os.getenv("AMOSCLAUD_STORAGE_PATH", "").strip():
        return Path(value).expanduser() / "system" / "repair-memory" / "catalog.json"
    if value := os.getenv("DATA_DIR", "").strip():
        return (
            Path(value).expanduser()
            / "amosclaud-storage"
            / "system"
            / "repair-memory"
            / "catalog.json"
        )
    return (
        (repository or Path.cwd()).resolve()
        / ".amosclaud"
        / "storage"
        / "repair-memory"
        / "catalog.json"
    )


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a+") as handle:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        try:
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return _default_catalog()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Repair memory catalog is invalid: {path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported repair memory catalog schema")
    capability = value.setdefault("capability", {})
    for key, default in (
        ("level", 1),
        ("max_level", MAX_LEVEL),
        ("unique_techniques", 0),
        ("successful_reuses", 0),
        ("failed_attempts", 0),
        ("last_unlock_at", None),
    ):
        capability.setdefault(key, default)
    if not isinstance(value.setdefault("techniques", []), list):
        raise ValueError("Repair memory techniques must be a list")
    return value


def _save(path: Path, catalog: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    catalog["updated_at"] = _now()
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(json.dumps(catalog, indent=2, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    temporary.replace(path)


@dataclass(frozen=True)
class MemoryMatch:
    technique_id: str
    title: str
    signals: tuple[str, ...]
    file_kinds: tuple[str, ...]
    verification: tuple[str, ...]
    success_count: int
    score: float


class VerifiedRepairMemory:
    """Authoritative store for sanitized, declarative, verified techniques."""

    def __init__(self, catalog_path: Path):
        self.catalog_path = catalog_path.expanduser().resolve()

    @classmethod
    def for_repository(cls, repository: Path) -> "VerifiedRepairMemory":
        return cls(default_catalog_path(repository))

    def initialize(self) -> dict[str, Any]:
        with _locked(self.catalog_path):
            catalog = _load(self.catalog_path)
            _save(self.catalog_path, catalog)
        return catalog

    def status(self) -> dict[str, Any]:
        with _locked(self.catalog_path):
            catalog = _load(self.catalog_path)
        return {
            **catalog["capability"],
            "catalog": str(self.catalog_path),
            "updated_at": catalog.get("updated_at"),
        }

    def recall(
        self, query: str, *, changed_files: Sequence[str] = (), limit: int = 4
    ) -> list[MemoryMatch]:
        query_signals, query_tokens = set(diagnostic_signals(query)), _tokens(query)
        query_kinds = set(_file_kinds(changed_files))
        with _locked(self.catalog_path):
            catalog = _load(self.catalog_path)
        matches: list[MemoryMatch] = []
        for item in catalog["techniques"]:
            if not isinstance(item, dict) or item.get("status") != "verified":
                continue
            signals = tuple(str(value) for value in item.get("signals", []) if value)
            kinds = tuple(str(value) for value in item.get("file_kinds", []) if value)
            title = str(item.get("title") or "Verified repair technique")
            signal_overlap = len(query_signals.intersection(signals))
            token_overlap = len(query_tokens.intersection(_tokens(title + " " + " ".join(signals))))
            kind_overlap = len(query_kinds.intersection(kinds))
            if not (signal_overlap or token_overlap or kind_overlap):
                continue
            successes = int(item.get("success_count") or 0)
            matches.append(
                MemoryMatch(
                    str(item.get("id") or ""),
                    title,
                    signals,
                    kinds,
                    tuple(str(value) for value in item.get("verification", []) if value),
                    successes,
                    signal_overlap * 6
                    + token_overlap * 1.5
                    + kind_overlap * 2
                    + min(successes, 20) * 0.1,
                )
            )
        return sorted(matches, key=lambda item: (-item.score, item.technique_id))[
            : max(1, min(limit, 10))
        ]

    @staticmethod
    def prompt_context(matches: Sequence[MemoryMatch]) -> str:
        if not matches:
            return "No verified repair technique matched this failure."
        lines = [
            "Use these verified Amosclaud Storage techniques as bounded guidance.",
            "Do not copy old patches. Re-diagnose the current repository and verify every change.",
        ]
        for match in matches:
            lines += [
                f"- Technique `{match.technique_id}`: {match.title}",
                f"  Signals: {', '.join(match.signals) or 'none'}",
                f"  File kinds: {', '.join(match.file_kinds) or 'unknown'}",
                f"  Required verification: {', '.join(match.verification) or 'repository checks'}",
                f"  Prior verified successes: {match.success_count}",
            ]
        return "\n".join(lines)

    def learn_verified(
        self,
        *,
        failure_evidence: str,
        changed_files: Sequence[str],
        verification_results: Sequence[dict[str, Any]],
        source: str = "",
        source_run_id: str = "",
    ) -> dict[str, Any]:
        signals, kinds = diagnostic_signals(failure_evidence), _file_kinds(changed_files)
        verification = _verification_names(verification_results)
        fingerprint = _fingerprint(signals, kinds)
        technique_id, now = f"tech_{fingerprint[:20]}", _now()
        with _locked(self.catalog_path):
            catalog = _load(self.catalog_path)
            techniques = catalog["techniques"]
            existing = next(
                (item for item in techniques if item.get("fingerprint") == fingerprint), None
            )
            novel = existing is None
            if novel:
                if len(techniques) >= MAX_TECHNIQUES:
                    raise ValueError("Repair memory catalog reached its bounded technique limit")
                techniques.append(
                    {
                        "id": technique_id,
                        "fingerprint": fingerprint,
                        "title": sanitize(
                            "Verified technique: "
                            + ", ".join(signals[:3] or kinds[:3] or ["verified-repair"]),
                            240,
                        ),
                        "signals": signals,
                        "file_kinds": kinds,
                        "verification": verification,
                        "source": sanitize(source, 200),
                        "source_run_id": sanitize(source_run_id, 200),
                        "first_verified_at": now,
                        "last_verified_at": now,
                        "success_count": 1,
                        "reuse_count": 0,
                        "status": "verified",
                    }
                )
                capability = catalog["capability"]
                before, unique = int(capability["level"]), len(techniques)
                capability["unique_techniques"] = unique
                capability["level"] = min(MAX_LEVEL, 1 + unique)
                if capability["level"] > before:
                    capability["last_unlock_at"] = now
            else:
                existing["last_verified_at"] = now
                existing["success_count"] = int(existing.get("success_count") or 0) + 1
                existing["reuse_count"] = int(existing.get("reuse_count") or 0) + 1
                catalog["capability"]["successful_reuses"] = (
                    int(catalog["capability"]["successful_reuses"]) + 1
                )
            techniques.sort(key=lambda item: str(item.get("id") or ""))
            _save(self.catalog_path, catalog)
            capability = dict(catalog["capability"])
        return {
            "learned": True,
            "novel": novel,
            "technique_id": technique_id,
            "level": capability["level"],
            "max_level": MAX_LEVEL,
            "unique_techniques": capability["unique_techniques"],
            "successful_reuses": capability["successful_reuses"],
        }

    def record_failure(self, reason: str = "") -> dict[str, Any]:
        with _locked(self.catalog_path):
            catalog = _load(self.catalog_path)
            capability = catalog["capability"]
            capability["failed_attempts"] = int(capability["failed_attempts"]) + 1
            capability["last_failure"] = sanitize(reason, 500)
            _save(self.catalog_path, catalog)
            return dict(capability)

    def learn_from_reports(
        self,
        *,
        failure_log: Path,
        candidate_report: Path,
        verification_report: Path,
        source: str = "",
        source_run_id: str = "",
    ) -> dict[str, Any]:
        candidate = json.loads(candidate_report.read_text(encoding="utf-8"))
        verification = json.loads(verification_report.read_text(encoding="utf-8"))
        changed_files = [
            str(item)
            for item in candidate.get("changed_files", [])
            if isinstance(item, str) and item
        ]
        results = [item for item in verification.get("results", []) if isinstance(item, dict)]
        verified = (
            candidate.get("status") == "candidate_applied"
            and verification.get("status") == "passed"
            and verification.get("credential_free") is True
            and bool(changed_files)
            and bool(results)
            and all(int(item.get("returncode", 1)) == 0 for item in results)
        )
        if not verified:
            self.record_failure("candidate or credential-free verification did not pass")
            return {"learned": False, "novel": False, **self.status()}
        return self.learn_verified(
            failure_evidence=failure_log.read_text(encoding="utf-8", errors="replace"),
            changed_files=changed_files,
            verification_results=results,
            source=source,
            source_run_id=source_run_id,
        )

    def record_report(self, report: Any, *, source_run_id: str = "") -> dict[str, Any]:
        verdict = getattr(getattr(report, "final_verdict", None), "value", None)
        changed = [str(item) for item in getattr(report, "changed_files", []) if item]
        evidence = list(getattr(report, "evidence", []) or [])
        if not (
            verdict == "PASS"
            and changed
            and evidence
            and all(getattr(item, "passed", False) for item in evidence)
        ):
            return {"learned": False, "novel": False, **self.status()}
        problem = "; ".join(
            str(getattr(item, "description", ""))
            for item in getattr(report, "repairs", []) or []
            if getattr(item, "changed", False)
        )
        problem += "\n" + "; ".join(
            f"{getattr(item, 'name', '')}: {getattr(item, 'output', '')}" for item in evidence
        )
        results = [
            {"name": str(getattr(item, "name", "verification")), "returncode": 0}
            for item in evidence
        ]
        return self.learn_verified(
            failure_evidence=problem,
            changed_files=changed,
            verification_results=results,
            source="repair-engine",
            source_run_id=source_run_id,
        )


def write_summary(path: Path, status: dict[str, Any]) -> None:
    level, maximum = int(status.get("level") or 1), int(status.get("max_level") or MAX_LEVEL)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "## Amosclaud Capability Level\n\n"
        f"**Level {level}/{maximum}** `{'■' * level}{'□' * max(0, maximum - level)}`\n\n"
        f"- Unique verified techniques: `{status.get('unique_techniques', 0)}`\n"
        f"- Successful known-technique reuses: `{status.get('successful_reuses', 0)}`\n"
        f"- Failed attempts (no level awarded): `{status.get('failed_attempts', 0)}`\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "status"):
        commands.add_parser(name).add_argument("--summary", default="")
    recall = commands.add_parser("recall")
    recall.add_argument("--query", default="")
    recall.add_argument("--query-file", default="")
    recall.add_argument("--changed-file", action="append", default=[])
    recall.add_argument("--output", required=True)
    recall.add_argument("--limit", type=int, default=4)
    learn = commands.add_parser("learn")
    learn.add_argument("--failure-log", required=True)
    learn.add_argument("--candidate-report", required=True)
    learn.add_argument("--verification-report", required=True)
    learn.add_argument("--source", default="")
    learn.add_argument("--source-run-id", default="")
    learn.add_argument("--summary", default="")
    failed = commands.add_parser("failed")
    failed.add_argument("--reason", default="")
    failed.add_argument("--summary", default="")
    return parser


def main() -> int:
    args = _parser().parse_args()
    memory = VerifiedRepairMemory(
        Path(args.catalog).expanduser() if args.catalog else default_catalog_path()
    )
    if args.command == "init":
        memory.initialize()
        result = memory.status()
    elif args.command == "status":
        result = memory.status()
    elif args.command == "recall":
        query = args.query
        if args.query_file:
            query += "\n" + Path(args.query_file).read_text(encoding="utf-8", errors="replace")
        matches = memory.recall(query, changed_files=args.changed_file, limit=args.limit)
        Path(args.output).write_text(memory.prompt_context(matches) + "\n", encoding="utf-8")
        result = {
            "matches": [asdict(item) for item in matches],
            "output": args.output,
            **memory.status(),
        }
    elif args.command == "learn":
        result = memory.learn_from_reports(
            failure_log=Path(args.failure_log),
            candidate_report=Path(args.candidate_report),
            verification_report=Path(args.verification_report),
            source=args.source,
            source_run_id=args.source_run_id,
        )
    else:
        result = memory.record_failure(args.reason)
    if summary := getattr(args, "summary", ""):
        write_summary(Path(summary), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"AMOSCLAUD_CAPABILITY_LEVEL={result.get('level', 1)}")
    print(f"AMOSCLAUD_NEW_TECHNIQUE={'true' if result.get('novel') else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
