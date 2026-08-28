from unittest.mock import AsyncMock

import pytest

from amoscloud_ai.domain_manager import DomainManagerError, VercelDomainManager


@pytest.mark.asyncio
async def test_domain_manager_requires_every_signal_for_verified_status():
    manager = VercelDomainManager(token="test-token")
    manager._get_project_domain = AsyncMock(
        return_value={"name": "amosclauds.com", "projectId": "prj_amos", "verified": True}
    )
    manager._get_domain_config = AsyncMock(return_value={"misconfigured": False})
    manager._resolve_dns = AsyncMock(return_value={"A": ["76.76.21.21"]})
    manager._probe_https = AsyncMock(
        return_value={
            "reachable": True,
            "status_code": 200,
            "final_url": "https://amosclauds.com/",
            "server": "Vercel",
            "x_vercel_id": "iad1::example",
            "x_vercel_cache": "HIT",
        }
    )

    result = await manager.verify(domain="amosclauds.com", project="amosclaud")

    assert result.status == "verified"
    assert result.verified is True
    assert result.project_domain.ok is True
    assert result.access_verification.ok is True
    assert result.dns_configuration.ok is True
    assert result.https_response.ok is True
    assert result.provider_edge.ok is True
    assert result.reasons == []


@pytest.mark.asyncio
async def test_domain_manager_reports_dns_or_wrong_edge_as_misconfigured():
    manager = VercelDomainManager(token="test-token")
    manager._get_project_domain = AsyncMock(
        return_value={"name": "amosclauds.com", "projectId": "prj_amos", "verified": True}
    )
    manager._get_domain_config = AsyncMock(return_value={"misconfigured": True})
    manager._resolve_dns = AsyncMock(return_value={"A": ["76.76.21.21"]})
    manager._probe_https = AsyncMock(
        return_value={
            "reachable": True,
            "status_code": 200,
            "final_url": "https://amosclauds.com/",
            "server": "other-provider",
            "x_vercel_id": None,
            "x_vercel_cache": None,
        }
    )

    result = await manager.verify(domain="amosclauds.com", project="amosclaud")

    assert result.status == "misconfigured"
    assert result.verified is False
    assert result.dns_configuration.ok is False
    assert result.provider_edge.ok is False
    assert result.reasons


@pytest.mark.asyncio
async def test_domain_manager_reports_missing_project_attachment_as_blocked():
    manager = VercelDomainManager(token="test-token")
    manager._get_project_domain = AsyncMock(return_value={"_not_found": True, "_status_code": 404})
    manager._get_domain_config = AsyncMock(return_value={"misconfigured": False})
    manager._resolve_dns = AsyncMock(return_value={"A": ["76.76.21.21"]})
    manager._probe_https = AsyncMock(
        return_value={
            "reachable": True,
            "status_code": 200,
            "server": "Vercel",
            "x_vercel_id": "iad1::example",
        }
    )

    result = await manager.verify(domain="amosclauds.com", project="wrong-project")

    assert result.status == "blocked"
    assert result.verified is False
    assert result.project_domain.ok is False
    assert result.access_verification.ok is False


def test_domain_manager_rejects_urls_and_non_public_hostnames():
    with pytest.raises(DomainManagerError):
        VercelDomainManager.normalize_domain("https://amosclauds.com")
    with pytest.raises(DomainManagerError):
        VercelDomainManager.normalize_domain("localhost")
