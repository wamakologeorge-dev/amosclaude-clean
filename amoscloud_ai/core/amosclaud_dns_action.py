"""Amosclaud Action contracts for judging independent DNS operations."""
from __future__ import annotations
from amoscloud_ai.core.amosclaud_action import ActionTool

DNS_ACTION_TOOLS: tuple[ActionTool, ...] = (
    ActionTool("dns.zone.create", "Create DNS zone", "Create an Amosclaud-managed desired DNS zone.", "dns:write", "write", "POST /api/v1/dns/zones"),
    ActionTool("dns.zone.read", "Read DNS zone", "Read Amosclaud-managed DNS desired state.", "dns:read", "read", "GET /api/v1/dns/zones/{domain}"),
    ActionTool("dns.record.upsert", "Manage DNS record", "Create or replace a record in an Amosclaud-managed zone.", "dns:write", "write", "POST /api/v1/dns/zones/{domain}/records"),
    ActionTool("dns.record.delete", "Delete DNS record", "Remove a record from an Amosclaud-managed zone.", "dns:write", "write", "DELETE /api/v1/dns/zones/{domain}/records"),
    ActionTool("dns.judge", "Judge DNS state", "Run the independent deterministic DNS verification gate; only a passing judge is healthy.", "dns:judge", "read", "POST /api/v1/dns/zones/{domain}/judge"),
    ActionTool("dns.export", "Export DNS desired state", "Export provider-neutral DNS state for an authoritative adapter.", "dns:read", "read", "GET /api/v1/dns/zones/{domain}/export"),
)

__all__ = ["DNS_ACTION_TOOLS"]
