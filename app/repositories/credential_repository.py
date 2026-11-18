"""Replicon credential persistence (encrypted token)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RepliconCredential


class CredentialRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_for_user(self, user_id: int) -> RepliconCredential | None:
        stmt = select(RepliconCredential).where(RepliconCredential.user_id == user_id)
        return self._db.scalars(stmt).first()

    def upsert(
        self,
        *,
        user_id: int,
        user_uri: str,
        base_url: str,
        access_token_encrypted: str,
    ) -> RepliconCredential:
        existing = self.get_for_user(user_id)
        if existing is None:
            existing = RepliconCredential(user_id=user_id)
            self._db.add(existing)
        existing.user_uri = user_uri.strip()
        existing.base_url = base_url.rstrip("/")
        existing.access_token_encrypted = access_token_encrypted
        self._db.flush()
        return existing
