"""Database engine, session factory, and FastAPI session dependency."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None

#: How long a statement waits for the write lock before giving up.
_SQLITE_BUSY_TIMEOUT_SECONDS = 30.0


def _build_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url
    kwargs: dict[str, Any] = {
        "echo": settings.database_echo,
        "future": True,
        "pool_pre_ping": True,
    }

    if url.startswith("sqlite"):
        # check_same_thread=False is required because FastAPI runs sync
        # dependencies in a threadpool; each request still gets its own Session.
        #
        # The timeout is deliberately far shorter than a pipeline run. SQLite
        # serialises writers even under WAL, and the orchestrator holds its
        # transaction for the whole run, so a competing upload cannot wait it
        # out. Failing fast with a retryable 503 beats hanging the request for
        # minutes; see errors.DatabaseBusyError.
        kwargs["connect_args"] = {
            "check_same_thread": False,
            "timeout": _SQLITE_BUSY_TIMEOUT_SECONDS,
        }
    else:
        kwargs["pool_size"] = 10
        kwargs["max_pool_overflow"] = 20

    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            # WAL keeps readers from blocking the pipeline's writes. It does
            # not make concurrent writers possible — nothing in SQLite does.
            cursor.execute("PRAGMA journal_mode=WAL")
            # SECURITY: SQLite ignores FK constraints unless asked. Our cascade
            # deletes are what make a retention purge actually remove child
            # rows (extractions, vault entries) rather than orphan them.
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute(
                f"PRAGMA busy_timeout={int(_SQLITE_BUSY_TIMEOUT_SECONDS * 1000)}"
            )
            cursor.close()

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )
    return _SessionFactory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session.

    Commits on success, rolls back on any exception, always closes.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session for background jobs, CLI tasks, and tests."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_database() -> None:
    """Create tables that do not yet exist.

    Adequate for local SQLite. Production should use Alembic migrations so that
    schema changes to PII-bearing tables are reviewable.
    """
    from app.models.database_models import Base

    Base.metadata.create_all(bind=get_engine())
    logger.info("Database schema ready (%d tables)", len(Base.metadata.tables))


def reset_engine() -> None:
    """Drop cached engine/session factory. Used by tests between fixtures."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
