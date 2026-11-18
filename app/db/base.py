"""SQLAlchemy declarative base.

Pattern — Layered architecture (persistence layer):
  All ORM entities inherit from Base so metadata stays in one place.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
