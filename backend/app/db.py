from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_engine(
            get_settings().database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session (and at most one transaction) per request."""
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()


def reset_engine() -> None:
    """Used by tests that point the app at a different database."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
