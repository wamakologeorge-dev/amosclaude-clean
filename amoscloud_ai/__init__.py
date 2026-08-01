"""Public package metadata for Amosclaud.

Startup order contract — the following sequence must be preserved whenever
the runtime environment is initialised:

  mutating scripts are never executed at import time; environment loading
  always uses ``override=False`` so that existing process variables win.

  REPOSITORY_CONTROL = initialize_repository_control()
  load_dotenv(override=False)

The two lines above describe the required initialisation order: repository
control (`.amosclaud`) is loaded before the root ``.env`` so that operator
injected variables always take precedence over repository defaults.
Active startup code lives in ``amoscloud_ai.main``.
"""

PRODUCT_NAME = "Amosclaud"
RUNTIME_NAME = "Amosclaud Autonomous"
LEGACY_IMPORT_NAMESPACE = "amoscloud_ai"
__version__ = "1.0.0"

__all__ = [
    "LEGACY_IMPORT_NAMESPACE",
    "PRODUCT_NAME",
    "RUNTIME_NAME",
    "__version__",
]
