"""FastAPI dependency providers.

Pattern — Dependency Injection:
  Routes declare what they need (db, user, timesheet service). This module
  wires concrete implementations so unit tests can override Depends.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.clients.replicon_client import RepliconClient
from app.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_db
from app.repositories.credential_repository import CredentialRepository
from app.services.auth_service import AuthService
from app.services.client_factory import RepliconClientFactory
from app.services.credential_service import CredentialService
from app.services.timesheet_service import TimesheetService
from app.services.weekly_fill_service import WeeklyFillService


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(db)


def get_credential_service(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CredentialService:
    return CredentialService(db, settings)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Require a logged-in session user."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Not authenticated",
            headers={"Location": "/login"},
        )
    user = AuthService(db).get_user(int(user_id))
    if user is None:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Not authenticated",
            headers={"Location": "/login"},
        )
    return user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return AuthService(db).get_user(int(user_id))


def get_timesheet_service_for_user(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TimesheetService:
    """Build TimesheetService from the logged-in user's stored Replicon token."""
    cred = CredentialRepository(db).get_for_user(user.id)
    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Replicon not configured",
            headers={"Location": "/setup"},
        )
    client = RepliconClientFactory(settings).from_credential(cred)
    return TimesheetService(client)


def get_weekly_fill_service(
    db: Session = Depends(get_db),
    timesheet_service: TimesheetService = Depends(get_timesheet_service_for_user),
) -> WeeklyFillService:
    return WeeklyFillService(db, timesheet_service)


# --- Legacy global-token client (JSON API / unit tests) --------------------


@lru_cache
def _get_or_create_client_cached(
    base_url: str,
    access_token: str,
    timeout_seconds: float,
) -> RepliconClient:
    return RepliconClient(
        base_url=base_url,
        access_token=access_token,
        timeout_seconds=timeout_seconds,
    )


def get_replicon_client(settings: Settings = Depends(get_settings)) -> RepliconClient:
    """Provide a RepliconClient from global env (legacy JSON routes / tests)."""
    return _get_or_create_client_cached(
        settings.normalized_base_url(),
        settings.require_access_token(),
        settings.replicon_timeout_seconds,
    )


def get_timesheet_service(
    client: RepliconClient = Depends(get_replicon_client),
) -> TimesheetService:
    """Provide a TimesheetService bound to the global Replicon client."""
    return TimesheetService(client)


def clear_dependency_caches() -> None:
    """Clear cached settings/clients — useful in tests."""
    get_settings.cache_clear()
    _get_or_create_client_cached.cache_clear()
