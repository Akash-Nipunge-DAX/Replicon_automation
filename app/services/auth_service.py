"""Registration and login.

Pattern — Service layer:
  Auth rules live here; routes only collect form input and set the session cookie.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import User
from app.repositories.user_repository import UserRepository
from app.security.passwords import hash_password, verify_password


class AuthError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AuthService:
    def __init__(self, db: Session) -> None:
        self._users = UserRepository(db)

    def register(self, username: str, password: str) -> User:
        username = (username or "").strip().lower()
        if len(username) < 3:
            raise AuthError("Username must be at least 3 characters.")
        if len(password or "") < 6:
            raise AuthError("Password must be at least 6 characters.")
        if self._users.get_by_username(username):
            raise AuthError("That username is already taken.")
        return self._users.create(
            username=username,
            password_hash=hash_password(password),
        )

    def authenticate(self, username: str, password: str) -> User:
        user = self._users.get_by_username((username or "").strip().lower())
        if user is None or not verify_password(password or "", user.password_hash):
            raise AuthError("Invalid username or password.")
        return user

    def get_user(self, user_id: int) -> User | None:
        return self._users.get_by_id(user_id)
