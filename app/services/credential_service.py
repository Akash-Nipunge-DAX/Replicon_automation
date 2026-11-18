"""One-time Replicon credential setup per dashboard user."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.clients.exceptions import RepliconAPIError
from app.clients.replicon_client import RepliconClient
from app.config import Settings
from app.db.models import RepliconCredential
from app.repositories.credential_repository import CredentialRepository
from app.repositories.template_repository import TemplateRepository
from app.security.crypto import encrypt_token
from app.services.timesheet_service import TimesheetService


class CredentialError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class CredentialService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self._settings = settings
        self._creds = CredentialRepository(db)
        self._templates = TemplateRepository(db)

    def get(self, user_id: int) -> RepliconCredential | None:
        return self._creds.get_for_user(user_id)

    def is_configured(self, user_id: int) -> bool:
        return self.get(user_id) is not None

    def save_and_validate(
        self,
        *,
        user_id: int,
        user_uri: str,
        access_token: str,
        base_url: str | None = None,
    ) -> RepliconCredential:
        user_uri = (user_uri or "").strip()
        access_token = (access_token or "").strip()
        base_url = (base_url or self._settings.replicon_base_url).rstrip("/")

        if not user_uri.startswith("urn:"):
            raise CredentialError("User URI must look like urn:replicon-tenant:…:user:…")
        if len(access_token) < 10:
            raise CredentialError("Access token looks too short.")

        # Validate by performing a real inspect against "today".
        client = RepliconClient(
            base_url=base_url,
            access_token=access_token,
            timeout_seconds=self._settings.replicon_timeout_seconds,
        )
        service = TimesheetService(client)
        try:
            service.inspect(user_uri=user_uri, target_date=date.today())
        except RepliconAPIError as exc:
            raise CredentialError(
                f"Could not reach Replicon with these credentials: {exc.message}"
            ) from exc
        finally:
            client.close()

        credential = self._creds.upsert(
            user_id=user_id,
            user_uri=user_uri,
            base_url=base_url,
            access_token_encrypted=encrypt_token(access_token),
        )
        # Seed default fill template on first successful setup.
        self._templates.ensure_default_seed(user_id)
        return credential
