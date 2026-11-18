"""Scheduled job persistence."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import ScheduledJob


class ScheduleRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_for_user(self, user_id: int) -> list[ScheduledJob]:
        stmt = (
            select(ScheduledJob)
            .where(ScheduledJob.user_id == user_id)
            .options(selectinload(ScheduledJob.template))
            .order_by(ScheduledJob.id)
        )
        return list(self._db.scalars(stmt).unique().all())

    def list_enabled(self) -> list[ScheduledJob]:
        stmt = (
            select(ScheduledJob)
            .where(ScheduledJob.enabled.is_(True))
            .options(selectinload(ScheduledJob.template))
        )
        return list(self._db.scalars(stmt).unique().all())

    def get_for_user(self, user_id: int, job_id: int) -> ScheduledJob | None:
        stmt = (
            select(ScheduledJob)
            .where(ScheduledJob.user_id == user_id, ScheduledJob.id == job_id)
            .options(selectinload(ScheduledJob.template))
        )
        return self._db.scalars(stmt).first()

    def create(
        self,
        *,
        user_id: int,
        template_id: int,
        weekday: int,
        hour: int,
        minute: int,
        enabled: bool = True,
    ) -> ScheduledJob:
        job = ScheduledJob(
            user_id=user_id,
            template_id=template_id,
            weekday=weekday,
            hour=hour,
            minute=minute,
            enabled=enabled,
        )
        self._db.add(job)
        self._db.flush()
        return job

    def update(
        self,
        job: ScheduledJob,
        *,
        template_id: int,
        weekday: int,
        hour: int,
        minute: int,
        enabled: bool,
    ) -> ScheduledJob:
        job.template_id = template_id
        job.weekday = weekday
        job.hour = hour
        job.minute = minute
        job.enabled = enabled
        self._db.flush()
        return job

    def delete(self, job: ScheduledJob) -> None:
        self._db.delete(job)
        self._db.flush()

    def mark_run(self, job: ScheduledJob, status: str) -> None:
        job.last_run_at = datetime.now(timezone.utc)
        job.last_status = status
        self._db.flush()
