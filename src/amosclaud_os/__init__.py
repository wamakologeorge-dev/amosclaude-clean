"""Amosclaud OS public interface.

Every platform entry point must resolve through the single AutonomousKernel.
"""

from .kernel import AutonomousKernel, SystemIdentity, get_autonomous_kernel

__all__ = ["AutonomousKernel", "SystemIdentity", "get_autonomous_kernel"]
