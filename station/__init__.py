"""Amosclaud Model Station agent.

The station agent is the client half of the Amosclaud model station network.
It runs on hardware owned by the operator, proves that a local inference
backend answers, heartbeats into Amosclaud so the platform can see it, claims
queued inference requests and returns the replies.

The package depends only on the Python standard library so it can run on any
machine with Python 3.11 or newer.
"""

from __future__ import annotations

__all__ = ["__version__", "AGENT_NAME", "USER_AGENT"]

__version__ = "1.0.1"
AGENT_NAME = "amosclaud-station"
USER_AGENT = f"{AGENT_NAME}/{__version__}"
