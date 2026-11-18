"""Factory for per-user RepliconClient instances.

Pattern — Factory:
  Dashboard users each store their own token. This factory builds a client
  from decrypted credentials instead of the global REPLICON_ACCESS_TOKEN.
"""

from __future__ import annotations

from app.clients.replicon_client import RepliconClient
from app.config import Settings
from app.db.models import RepliconCredential
from app.security.crypto import decrypt_token


class RepliconClientFactory:
    """Create a RepliconClient bound to one user's stored credential."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def from_credential(self, credential: RepliconCredential) -> RepliconClient:
        token = decrypt_token(credential.access_token_encrypted)
        return RepliconClient(
            base_url=credential.base_url.rstrip("/"),
            access_token=token,
            timeout_seconds=self._settings.replicon_timeout_seconds,
        )
