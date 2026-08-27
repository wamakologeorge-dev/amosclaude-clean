"""Amosclaud-owned control plane primitives."""

from . import amosclaud_authority
from .authority_verifier import install as _install_authority_verifier
from .registry import ServiceRegistry
from .vault import AmosclaudVault

# Authority secrets are PBKDF2-salted. Install the prefix-narrowed verifier as
# soon as the core package loads so every API, agent, and connector shares the
# same credential validation behavior.
_install_authority_verifier(amosclaud_authority)

__all__ = ["AmosclaudVault", "ServiceRegistry", "amosclaud_authority"]
