"""Repository-wide pytest configuration.

Keep test runs from generating Python bytecode inside the source tree.

The Amosclaud namespace contract
(tests/test_amosclaud_namespace_contract.py) requires that no ``*.pyc``
files or ``__pycache__`` directories exist under ``Amosclaud/``. Importing
the compatibility package during the test session would otherwise write
bytecode there mid-run. CircleCI already exports
``PYTHONDONTWRITEBYTECODE=1``; this conftest applies the same guarantee to
every environment that runs pytest.
"""

import sys

sys.dont_write_bytecode = True
