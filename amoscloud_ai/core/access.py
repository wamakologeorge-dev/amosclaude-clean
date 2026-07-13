from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from enum import Enum


class AccessMode(str, Enum):
    LOCAL = "local"
    LAN = "lan"
    PUBLIC = "public"


@dataclass(frozen=True)
class AccessPolicy:
    mode: AccessMode
    owner_email: str

    @classmethod
    def from_environment(cls) -> "AccessPolicy":
        raw_mode = os.getenv("AMOSCLAUD_ACCESS_MODE", AccessMode.LOCAL.value).strip().lower()
        try:
            mode = AccessMode(raw_mode)
        except ValueError as exc:
            raise ValueError("AMOSCLAUD_ACCESS_MODE must be local, lan, or public") from exc
        return cls(
            mode=mode,
            owner_email=os.getenv("AMOSCLAUD_ADMIN_EMAIL", "").strip().lower(),
        )

    def allows_client(self, host: str | None) -> bool:
        if self.mode is AccessMode.PUBLIC:
            return True
        if not host:
            return False
        normalized = host.strip().split("%", 1)[0]
        if normalized in {"localhost", "::1"}:
            return True
        try:
            address = ipaddress.ip_address(normalized)
        except ValueError:
            return False
        if self.mode is AccessMode.LOCAL:
            return address.is_loopback
        return address.is_loopback or address.is_private

    def role_for(self, user: dict | None) -> str:
        if not user:
            return "visitor"
        email = str(user.get("email", "")).strip().lower()
        if self.owner_email and email == self.owner_email:
            return "owner"
        if bool(user.get("is_admin")):
            return "administrator"
        return "member"

    def public_summary(self) -> dict:
        return {
            "mode": self.mode.value,
            "public_signup": self.mode is AccessMode.PUBLIC,
            "lan_access": self.mode in {AccessMode.LAN, AccessMode.PUBLIC},
            "public_access": self.mode is AccessMode.PUBLIC,
        }
