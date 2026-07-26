"""Shared pytest fixtures for isolated Amosclaud test storage."""

from pathlib import Path

import pytest

from amoscloud_ai.api.routes import auth, repositories


@pytest.fixture
def isolated_repository_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Give one test its own authentication database and repository storage.

    ``tmp_path`` is unique for each pytest test invocation, including tests run
    concurrently by separate GitHub Actions jobs or pytest-xdist workers. No
    test using this fixture can read from or write to the production ``data``
    directory in the checked-out repository.
    """

    data_root = tmp_path / "data"
    repository_root = data_root / "repositories"
    database_path = data_root / "auth.db"
    repository_root.mkdir(parents=True)

    # Keep environment-driven code and already-imported module constants aligned.
    monkeypatch.setenv("AUTH_DB_PATH", str(database_path))
    monkeypatch.setenv("REPOSITORY_STORAGE_PATH", str(repository_root))
    monkeypatch.setattr(auth, "DB_PATH", database_path)
    monkeypatch.setattr(repositories, "DB_PATH", database_path)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", repository_root)

    return data_root
