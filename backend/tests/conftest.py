"""Shared pytest fixtures.

Every test runs against a temporary data directory and a fresh SQLite file, so
tests never touch the developer's real ``data/`` zones or database.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point every storage zone at a per-test temporary directory.

    ``get_settings`` is an ``lru_cache`` singleton and the cipher helpers cache
    their keys, so all of them are cleared before and after each test. Without
    that, the first test's configuration would leak into the rest of the suite.
    """
    for zone in ("raw", "masked", "output", "tmp", "vector"):
        (tmp_path / zone).mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RAW_ZONE_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("MASKED_ZONE_DIR", str(tmp_path / "masked"))
    monkeypatch.setenv("OUTPUT_ZONE_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("TMP_ZONE_DIR", str(tmp_path / "tmp"))
    monkeypatch.setenv("VECTOR_STORE_DIR", str(tmp_path / "vector"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("GEMINI_ENABLED", "false")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    # No test makes a network call: the Industry Updates feed stays off, and
    # tests that exercise it inject a fake fetcher.
    monkeypatch.setenv("NEWS_ENABLED", "false")
    # Pinned so a developer's .env cannot move every year-dependent test.
    monkeypatch.setenv("DEFAULT_TAX_YEAR", "2026")

    _clear_caches()
    yield
    _clear_caches()


def _clear_caches() -> None:
    from app.core import db, security
    from app.core.config import get_settings

    get_settings.cache_clear()
    security.file_cipher.cache_clear()
    security.vault_cipher.cache_clear()
    db.reset_engine()

    from app.services import news_service

    news_service.reset_news_service()

    # The assistant's answer cache is per process; one test's answer must
    # never be replayed into another.
    from app.services.assistant import assistant_service

    assistant_service._SHARED_CACHE = None


@pytest.fixture()
def session() -> Iterator[object]:
    """A transactional database session against the temporary schema."""
    from app.core.db import init_database, session_scope

    init_database()
    with session_scope() as db_session:
        yield db_session


@pytest.fixture()
def client() -> Iterator[object]:
    """A TestClient with lifespan startup run (schema + bootstrap seeding)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
