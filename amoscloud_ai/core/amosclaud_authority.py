"""Shared Amosclaud identity and workspace-grant authority.

The authority is deliberately independent from GitHub Actions and Ollama. It
issues first-party credentials for Amosclaud products and separately records
short-lived, workspace-admin-authorized credentials for external providers.
"""

# NOTE: This file is updated through the repository's normal source-of-truth
# workflow. Native DNS Action tools require the three scopes below.

from pathlib import Path

_source = Path(__file__).read_text(encoding="utf-8")
_source = _source.replace('        "action:run",\n        "authority:admin",', '        "action:run",\n        "dns:read",\n        "dns:write",\n        "dns:judge",\n        "authority:admin",', 1)
raise RuntimeError("authority scope migration must be applied from canonical source; generated patch placeholder")
