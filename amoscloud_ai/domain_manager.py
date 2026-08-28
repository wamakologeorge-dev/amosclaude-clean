"""Amosclaud Domain Manager.

Verifies that a public domain is attached to the expected Vercel project,
passes Vercel access verification, has a non-misconfigured DNS configuration,
and responds over HTTPS through the Vercel edge.

The manager deliberately keeps these signals separate so Amosclaud never turns
"domain exists" into a false claim that the domain is healthy end-to-end.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote

import dns.resolver
import httpx
from pydantic import BaseModel, Field

VERCEL_API = "https://api.vercel.com"
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
    re.IGNORECASE,
)


class DomainCheck(BaseModel):
    ok: bool
    detail: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class DomainVerification(BaseModel):
    domain: str
    provider_expected: Literal["vercel"] = "vercel"
    project: str
    team_id: str | None = None
    checked_at: datetime
    status: Literal["verified", "blocked", "misconfigured", "unreachable"]
    verified: bool
    project_domain: DomainCheck
    access_verification: DomainCheck
    dns_configuration: DomainCheck
    https_response: DomainCheck
    provider_edge: DomainCheck
    dns_records: dict[str, list[str]] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class DomainManagerError(RuntimeError):
    """Expected verification/configuration failure."""


class VercelDomainManager:
    """Independent Amosclaud verifier for a Vercel-backed public domain."""

    def __init__(
        self,
        *,
        token: str | None = None,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = (token or os.getenv("VERCEL_TOKEN", "")).strip()
        self.timeout = timeout
        self._client = client

    @staticmethod
    def normalize_domain(domain: str) -> str:
        value = domain.strip().lower().rstrip(".")
        if value.startswith("http://") or value.startswith("https://"):
            raise DomainManagerError("Provide a hostname, not a URL")
        if not _DOMAIN_RE.fullmatch(value):
            raise DomainManagerError("Domain is not a valid public DNS hostname")
        return value

    @staticmethod
    def _query(team_id: str | None) -> dict[str, str]:
        return {"teamId": team_id} if team_id else {}

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise DomainManagerError("VERCEL_TOKEN is not configured")
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    async def _request(self, path: str, *, team_id: str | None) -> dict[str, Any]:
        owned = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.get(
                f"{VERCEL_API}{path}",
                headers=self._headers(),
                params=self._query(team_id),
            )
            if response.status_code == 404:
                return {"_not_found": True, "_status_code": 404}
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise DomainManagerError("Vercel returned an unexpected response shape")
            return payload
        except httpx.HTTPStatusError as exc:
            raise DomainManagerError(
                f"Vercel API returned HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise DomainManagerError(f"Vercel API request failed: {exc}") from exc
        finally:
            if owned:
                await client.aclose()

    async def _get_project_domain(
        self, project: str, domain: str, team_id: str | None
    ) -> dict[str, Any]:
        return await self._request(
            f"/v9/projects/{quote(project, safe='')}/domains/{quote(domain, safe='')}",
            team_id=team_id,
        )

    async def _get_domain_config(self, domain: str, team_id: str | None) -> dict[str, Any]:
        return await self._request(
            f"/v6/domains/{quote(domain, safe='')}/config",
            team_id=team_id,
        )

    @staticmethod
    def _resolve_sync(domain: str) -> dict[str, list[str]]:
        records: dict[str, list[str]] = {}
        for record_type in ("A", "AAAA", "CNAME", "TXT", "NS"):
            try:
                answers = dns.resolver.resolve(domain, record_type, lifetime=5.0)
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout):
                continue
            values = sorted({str(answer).rstrip(".") for answer in answers})
            if values:
                records[record_type] = values
        return records

    async def _resolve_dns(self, domain: str) -> dict[str, list[str]]:
        return await asyncio.to_thread(self._resolve_sync, domain)

    @staticmethod
    def _reject_private_addresses(records: dict[str, list[str]]) -> None:
        for value in [*records.get("A", []), *records.get("AAAA", [])]:
            try:
                address = ipaddress.ip_address(value)
            except ValueError:
                continue
            if not address.is_global:
                raise DomainManagerError(
                    "HTTPS verification refused because DNS resolves to a non-public address"
                )

    async def _probe_https(self, domain: str) -> dict[str, Any]:
        owned = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
        )
        try:
            response = await client.get(
                f"https://{domain}/",
                headers={"User-Agent": "Amosclaud-Domain-Manager/1.0"},
            )
            return {
                "reachable": True,
                "status_code": response.status_code,
                "final_url": str(response.url),
                "server": response.headers.get("server"),
                "x_vercel_id": response.headers.get("x-vercel-id"),
                "x_vercel_cache": response.headers.get("x-vercel-cache"),
            }
        except httpx.HTTPError as exc:
            return {"reachable": False, "error": str(exc)}
        finally:
            if owned:
                await client.aclose()

    async def verify(
        self,
        *,
        domain: str,
        project: str,
        team_id: str | None = None,
    ) -> DomainVerification:
        hostname = self.normalize_domain(domain)
        project = project.strip()
        if not project:
            raise DomainManagerError("Vercel project ID or name is required")

        project_payload, config_payload, dns_records = await asyncio.gather(
            self._get_project_domain(project, hostname, team_id),
            self._get_domain_config(hostname, team_id),
            self._resolve_dns(hostname),
        )
        self._reject_private_addresses(dns_records)
        https_payload = await self._probe_https(hostname)

        exists = not bool(project_payload.get("_not_found"))
        access_verified = exists and bool(project_payload.get("verified", False))
        misconfigured = bool(config_payload.get("misconfigured", True))
        dns_ok = bool(dns_records) and not misconfigured
        https_ok = bool(https_payload.get("reachable")) and int(
            https_payload.get("status_code") or 0
        ) < 500
        server = str(https_payload.get("server") or "").lower()
        vercel_edge = bool(https_payload.get("x_vercel_id")) or "vercel" in server

        project_check = DomainCheck(
            ok=exists,
            detail=(
                "Domain exists on the expected Vercel project"
                if exists
                else "Domain was not found on the expected Vercel project"
            ),
            evidence={
                "name": project_payload.get("name"),
                "project_id": project_payload.get("projectId"),
            },
        )
        access_check = DomainCheck(
            ok=access_verified,
            detail=(
                "Vercel reports domain access verified"
                if access_verified
                else "Vercel domain access verification is not satisfied"
            ),
            evidence={"verified": project_payload.get("verified")},
        )
        dns_check = DomainCheck(
            ok=dns_ok,
            detail=(
                "Vercel reports the domain DNS configuration is valid"
                if dns_ok
                else "DNS is missing or Vercel reports it as misconfigured"
            ),
            evidence={"misconfigured": config_payload.get("misconfigured")},
        )
        https_check = DomainCheck(
            ok=https_ok,
            detail=(
                f"HTTPS responded with HTTP {https_payload.get('status_code')}"
                if https_ok
                else "The public HTTPS endpoint did not return a usable response"
            ),
            evidence=https_payload,
        )
        edge_check = DomainCheck(
            ok=vercel_edge,
            detail=(
                "Public response contains Vercel edge evidence"
                if vercel_edge
                else "Public response does not prove that traffic reached the Vercel edge"
            ),
            evidence={
                "server": https_payload.get("server"),
                "x_vercel_id": https_payload.get("x_vercel_id"),
                "x_vercel_cache": https_payload.get("x_vercel_cache"),
            },
        )

        checks = [project_check, access_check, dns_check, https_check, edge_check]
        verified = all(check.ok for check in checks)
        reasons = [check.detail for check in checks if not check.ok]
        if verified:
            status: Literal["verified", "blocked", "misconfigured", "unreachable"] = "verified"
        elif not exists or not access_verified:
            status = "blocked"
        elif not dns_ok or not vercel_edge:
            status = "misconfigured"
        else:
            status = "unreachable"

        return DomainVerification(
            domain=hostname,
            project=project,
            team_id=team_id,
            checked_at=datetime.now(timezone.utc),
            status=status,
            verified=verified,
            project_domain=project_check,
            access_verification=access_check,
            dns_configuration=dns_check,
            https_response=https_check,
            provider_edge=edge_check,
            dns_records=dns_records,
            reasons=reasons,
        )
