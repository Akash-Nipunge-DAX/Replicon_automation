"""ORM models for the self-serve dashboard.

Each logged-in user owns credentials, templates, schedules, and fill history.
No admin role — repositories always filter by ``user_id``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    """Dashboard account (username/password). Separate from Replicon identity."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    credential: Mapped[RepliconCredential | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    templates: Mapped[list[FillTemplate]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    schedules: Mapped[list[ScheduledJob]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    fill_runs: Mapped[list[FillRun]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RepliconCredential(Base):
    """One-time Replicon setup per dashboard user (token stored encrypted)."""

    __tablename__ = "replicon_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    user_uri: Mapped[str] = mapped_column(String(512))
    base_url: Mapped[str] = mapped_column(String(256), default="https://na5.replicon.com")
    # Fernet ciphertext (never store plaintext tokens).
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    configured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="credential")


class FillTemplate(Base):
    """Named fill strategy: which tasks/hours and skip rules to apply."""

    __tablename__ = "fill_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    skip_weekends: Mapped[bool] = mapped_column(Boolean, default=True)
    skip_holidays: Mapped[bool] = mapped_column(Boolean, default=True)
    submit_after_fill: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="templates")
    tasks: Mapped[list[TemplateTask]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="TemplateTask.sort_order",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_template_user_name"),
    )


class TemplateTask(Base):
    """One task allocation inside a fill template (e.g. Coding = 3h)."""

    __tablename__ = "template_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("fill_templates.id", ondelete="CASCADE"), index=True
    )
    task_name: Mapped[str] = mapped_column(String(128))
    hours: Mapped[float] = mapped_column(Float)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    template: Mapped[FillTemplate] = relationship(back_populates="tasks")


class ScheduledJob(Base):
    """User-defined schedule that triggers WeeklyFillService via APScheduler."""

    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[int] = mapped_column(
        ForeignKey("fill_templates.id", ondelete="CASCADE")
    )
    # 0=Monday … 6=Sunday (Python datetime.weekday())
    weekday: Mapped[int] = mapped_column(Integer, default=0)
    hour: Mapped[int] = mapped_column(Integer, default=9)
    minute: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="schedules")
    template: Mapped[FillTemplate] = relationship()


class FillRun(Base):
    """Audit row for a weekly fill (manual or scheduled)."""

    __tablename__ = "fill_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("fill_templates.id", ondelete="SET NULL"), nullable=True
    )
    week_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    status: Mapped[str] = mapped_column(String(32))  # success | partial | failed
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="fill_runs")
    template: Mapped[FillTemplate | None] = relationship()
