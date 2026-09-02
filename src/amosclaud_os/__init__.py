"""Amosclaud OS public interface.

Every platform entry point must resolve through the single AutonomousKernel.
Slapface is applied here so direct kernel callers receive the same Book preflight
as higher-level Amosclaud agent routes.
"""

from typing import Any

from .kernel import AutonomousKernel, SystemIdentity, get_autonomous_kernel

_ORIGINAL_EXECUTE = AutonomousKernel.execute
_ORIGINAL_WRITE_DOCUMENT = AutonomousKernel.write_document


def _slapface_scope(workspace: Any, metadata: dict[str, Any] | None = None) -> str:
    prepared = dict(metadata or {})
    return str(
        prepared.get("slapface_scope")
        or prepared.get("user_id")
        or prepared.get("repository")
        or workspace
        or "default"
    )


def _execute_with_slapface(
    self: AutonomousKernel,
    *,
    objective: str,
    mode: str = "plan",
    authorized_writes: bool = False,
    metadata: dict[str, Any] | None = None,
    security_grant: str | None = None,
) -> dict[str, Any]:
    from amoscloud_ai.slapface import Slapface

    prepared = dict(metadata or {})
    gate = Slapface()
    decision = gate.preflight(
        workspace=self.workspace,
        scope=_slapface_scope(self.workspace, prepared),
        agent_id=str(prepared.get("agent_id") or "amosclaud-autonomous"),
        objective=objective,
        mode=mode,
        source=str(prepared.get("source") or "amosclaud"),
        handoff_id=(
            str(prepared.get("slapface_handoff_id"))
            if prepared.get("slapface_handoff_id")
            else None
        ),
        scan_secrets=mode.strip().lower() not in {"answer", "guide", "learn", "teach"},
    )
    if not decision.get("work_allowed"):
        active = decision.get("active_handoff") or {}
        chapter_link = active.get("chapter_link")
        evidence = [
            "Slapface stopped the task before normal repository analysis or execution.",
            str(decision.get("message") or "An unfinished Book handoff must be resolved."),
        ]
        if chapter_link:
            evidence.append(f"Unfinished Book chapter: {chapter_link}")
        if active.get("next_line"):
            evidence.append(f"Next line: {active['next_line']}")
        if active.get("risk"):
            evidence.append(f"Risk: {active['risk']}")
        return self._stamp(
            {
                "status": "blocked",
                "failed": False,
                "error": "slapface_blocked",
                "evidence": evidence,
                "slapface": decision,
            }
        )
    prepared["slapface"] = decision
    return _ORIGINAL_EXECUTE(
        self,
        objective=objective,
        mode=mode,
        authorized_writes=authorized_writes,
        metadata=prepared,
        security_grant=security_grant,
    )


def _write_document_with_boolean_contract(
    self: AutonomousKernel,
    relative_path: str,
    content: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Keep the historical ``ok`` field and enforce Slapface before writes."""
    from amoscloud_ai.slapface import Slapface

    slapface_scope = str(kwargs.pop("slapface_scope", str(self.workspace)))
    slapface_handoff_id = kwargs.pop("slapface_handoff_id", None)
    gate = Slapface()
    secret_scan = gate.scan_text(content, path=relative_path)
    if secret_scan.get("blocked"):
        return self._stamp(
            {
                "ok": False,
                "status": "blocked",
                "error": "slapface_high_confidence_secret_exposure",
                "evidence": [
                    "Slapface refused to write high-confidence credential material.",
                    "Move the credential to an approved secret manager or environment variable.",
                ],
                "secret_scan": secret_scan,
                "raw_secret_exposed": False,
            }
        )

    decision = gate.preflight(
        workspace=None,
        scope=slapface_scope,
        agent_id="amosclaud-autonomous",
        objective=f"write repository document {relative_path}",
        mode="write",
        source="amosclaud",
        handoff_id=str(slapface_handoff_id) if slapface_handoff_id else None,
        scan_secrets=False,
    )
    if not decision.get("work_allowed"):
        return self._stamp(
            {
                "ok": False,
                "status": "blocked",
                "error": "slapface_blocked",
                "slapface": decision,
            }
        )
    if decision.get("remediation") and not gate.remediation_allowed(
        scope=slapface_scope,
        handoff_id=str(slapface_handoff_id) if slapface_handoff_id else None,
        mode="write",
        target_path=relative_path,
    ):
        return self._stamp(
            {
                "ok": False,
                "status": "blocked",
                "error": "slapface_remediation_path_not_allowed",
                "slapface": decision,
            }
        )

    result = dict(_ORIGINAL_WRITE_DOCUMENT(self, relative_path, content, **kwargs))
    result.setdefault(
        "ok",
        not bool(result.get("error"))
        and str(result.get("status") or "").lower() not in {"blocked", "failed"},
    )
    result["slapface"] = decision
    return result


AutonomousKernel.execute = _execute_with_slapface
AutonomousKernel.write_document = _write_document_with_boolean_contract

__all__ = ["AutonomousKernel", "SystemIdentity", "get_autonomous_kernel"]
