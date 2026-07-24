"""Integrated intelligence components for the one Amosclaud Autonomous kernel.

These modules do not create a second Autonomous runtime. They are capabilities
owned and composed by :class:`src.amosclaud_os.kernel.AutonomousKernel`.
"""

from .model_engine import ModelEngine
from .autonomous_connectors import AutonomousConnectorHub

__all__ = ["ModelEngine", "AutonomousConnectorHub"]
