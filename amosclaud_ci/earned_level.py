"""An agent level you have to earn, instead of one you can simply declare.

AMOSCLAUD-TOOL-SOVEREIGNTY-POLICY:v1

Before this module, the agent's level was this, and only this::

    return _bounded_level(os.getenv("AMOSCLAUD_AUTONOMOUS_LEVEL", "1"))

The number came from an environment variable, was never written by anything,
was never checked against anything, and ranged up to 5000. Setting
``AMOSCLAUD_AUTONOMOUS_LEVEL=4999`` made the agent "level 4999" instantly. So
the honest answer to "can the agent raise its own level?" was yes -- and the
only available method was cheating, because no other method existed.

A level here is a count of capabilities that survived an outside check. Each
capability needs an *attestation* carrying a command that re-proves it. The
level is recomputed by running those commands. Nothing is taken on trust:
not the agent's word, not a stored number, not a previous run's result.

Rules that make the number hard to inflate:

* An attestation without a re-runnable oracle command does not count.
* A command that cannot fail -- ``true``, ``echo ...``, ``exit 0`` -- does not
  count. A check that always passes measures nothing.
* Verification runs the command now. Stored verdicts are never trusted.
* A declared level above the earned level is reported as an unearned gap
  rather than silently honoured.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Commands that pass no matter what the system does. An oracle must be able to
# fail, or it is decoration.
_VACUOUS = {"true", ":", "echo", "exit", "printf", "cat", "ls", "pwd"}


@dataclass(frozen=True)
class Attestation:
    """One claimed capability plus the command that re-proves it."""

    capability: str
    claim: str
    oracle: str
    evidence: str
    recorded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def is_vacuous(self) -> bool:
        """True when the oracle command cannot meaningfully fail."""
        try:
            parts = shlex.split(self.oracle)
        except ValueError:
            return True
        if not parts:
            return True
        head = Path(parts[0]).name
        if head in _VACUOUS:
            return True
        # `python -c "pass"` and friends assert nothing either.
        joined = " ".join(parts[1:])
        return head.startswith("python") and joined.strip() in {"-c pass", "-c ''", '-c ""'}


@dataclass(frozen=True)
class VerificationResult:
    attestation: Attestation
    passed: bool
    detail: str

    @property
    def counts(self) -> bool:
        return self.passed and not self.attestation.is_vacuous() and bool(self.attestation.oracle)


class LevelLedger:
    """Append-only record of capabilities, each re-checkable on demand."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, attestation: Attestation) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(attestation), sort_keys=True) + "\n")

    def attestations(self) -> list[Attestation]:
        if not self.path.exists():
            return []
        seen: dict[str, Attestation] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                attestation = Attestation(**data)
            except TypeError:
                continue
            seen[attestation.capability] = attestation  # newest claim wins
        return list(seen.values())

    def verify(self, cwd: Path | None = None, timeout: int = 900) -> list[VerificationResult]:
        """Re-run every oracle now. Stored verdicts are never trusted."""
        results: list[VerificationResult] = []
        for attestation in self.attestations():
            if not attestation.oracle.strip():
                results.append(VerificationResult(attestation, False, "no oracle command"))
                continue
            if attestation.is_vacuous():
                results.append(
                    VerificationResult(attestation, False, "oracle cannot fail; not counted")
                )
                continue
            try:
                completed = subprocess.run(
                    attestation.oracle,
                    shell=True,
                    cwd=str(cwd) if cwd else None,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                results.append(VerificationResult(attestation, False, "oracle timed out"))
                continue
            except OSError as exc:  # pragma: no cover - defensive
                results.append(VerificationResult(attestation, False, f"oracle error: {exc}"))
                continue
            passed = completed.returncode == 0
            detail = "oracle passed" if passed else f"oracle exited {completed.returncode}"
            results.append(VerificationResult(attestation, passed, detail))
        return results

    def earned_level(self, cwd: Path | None = None) -> int:
        """How many capabilities survive an outside check right now."""
        return sum(1 for result in self.verify(cwd=cwd) if result.counts)


def declared_level(default: int = 1) -> int:
    raw = os.getenv("AMOSCLAUD_AUTONOMOUS_LEVEL", str(default))
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default


def level_report(ledger: LevelLedger, cwd: Path | None = None) -> dict[str, object]:
    """Declared vs earned, with the gap named rather than hidden."""
    results = ledger.verify(cwd=cwd)
    earned = sum(1 for result in results if result.counts)
    declared = declared_level()
    return {
        "declared_level": declared,
        "earned_level": earned,
        "unearned_gap": max(0, declared - earned),
        "honest": declared <= earned,
        "capabilities": [
            {
                "capability": result.attestation.capability,
                "counts": result.counts,
                "detail": result.detail,
                "oracle": result.attestation.oracle,
            }
            for result in results
        ],
    }
