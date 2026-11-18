"""Pytest configuration."""

from __future__ import annotations

import os

# Default env for unit tests — never require a real token for normal pytest runs.
os.environ.setdefault("REPLICON_BASE_URL", "https://na5.replicon.com")
os.environ.setdefault("REPLICON_ACCESS_TOKEN", "test-token-not-real")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.dependencies import clear_dependency_caches
from app.main import app


@pytest.fixture()
def db_session():
    """Isolated in-memory SQLite for dashboard tests."""
    clear_dependency_caches()
    get_settings.cache_clear()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import app.db.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        clear_dependency_caches()
        get_settings.cache_clear()


@pytest.fixture()
def client(db_session):
    """HTTP client with DB dependency overridden."""

    def _override_get_db():
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
