"""Public Amosclaud runtime package metadata and startup ordering."""

from __future__ import annotations

from dotenv import load_dotenv

from .domain_policy import enforce_platform_domain_policy
from .repository_control import initialize_repository_control

# Repository-local control configuration must load before the ordinary root
# dotenv file. The control loader reads configuration only; mutating scripts are never
# executed during package import.
REPOSITORY_CONTROL = initialize_repository_control()
load_dotenv(override=False)
enforce_platform_domain_policy()

PRODUCT_NAME = "Amosclaud"
RUNTIME_NAME = "Amosclaud Autonomous"
LEGACY_IMPORT_NAMESPACE = "amoscloud_ai"
__version__ = "1.0.0"
