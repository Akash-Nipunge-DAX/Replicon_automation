"""In-process APScheduler integration.

Pattern — Scheduler as a thin adapter:
  Job definitions live in SQLite (ScheduledJob). On startup we register them
  with APScheduler. When a trigger fires we open a fresh DB session and call
  WeeklyFillService — same path as the dashboard "Run fill" button.
"""

from __future__ import annotations

import logging
from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.db import session as db_session
from app.db.session import get_engine
from app.repositories.credential_repository import CredentialRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.repositories.user_repository import UserRepository
from app.services.client_factory import RepliconClientFactory
from app.services.timesheet_service import TimesheetService
from app.services.weekly_fill_service import WeeklyFillService

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="UTC")
    return _scheduler


def start_scheduler() -> None:
    """Start APScheduler and reload enabled jobs from the database."""
    get_engine()
    sched = get_scheduler()
    if not sched.running:
        sched.start()
    reload_jobs()
    logger.info("apscheduler_started")


def shutdown_scheduler() -> None:
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
        logger.info("apscheduler_stopped")


def reload_jobs() -> None:
    """Replace all dashboard_* jobs with current DB definitions."""
    get_engine()
    sched = get_scheduler()

    for job in list(sched.get_jobs()):
        if job.id.startswith("dashboard_"):
            job.remove()

    db = db_session.SessionLocal()
    try:
        jobs = ScheduleRepository(db).list_enabled()
        for job in jobs:
            job_id = f"dashboard_{job.id}"
            # APScheduler cron: day_of_week 0=Mon … 6=Sun (matches Python weekday).
            trigger = CronTrigger(
                day_of_week=job.weekday,
                hour=job.hour,
                minute=job.minute,
                timezone="UTC",
            )
            sched.add_job(
                _run_scheduled_job,
                trigger=trigger,
                id=job_id,
                kwargs={"scheduled_job_id": job.id},
                replace_existing=True,
            )
            logger.info(
                "scheduled_job_registered",
                extra={
                    "job_id": job.id,
                    "weekday": job.weekday,
                    "hour": job.hour,
                    "minute": job.minute,
                },
            )
    finally:
        db.close()


def _run_scheduled_job(scheduled_job_id: int) -> None:
    get_engine()
    assert db_session.SessionLocal is not None
    db = db_session.SessionLocal()
    try:
        from sqlalchemy import select

        from app.db.models import ScheduledJob

        schedules = ScheduleRepository(db)
        # Worker loads by id (no session user); still scopes data via job.user_id.
        job = db.scalars(
            select(ScheduledJob).where(ScheduledJob.id == scheduled_job_id)
        ).first()
        if job is None or not job.enabled:
            return

        user = UserRepository(db).get_by_id(job.user_id)
        cred = CredentialRepository(db).get_for_user(job.user_id)
        if user is None or cred is None:
            schedules.mark_run(job, "failed_no_credential")
            db.commit()
            return

        factory = RepliconClientFactory(get_settings())
        client = factory.from_credential(cred)
        try:
            ts = TimesheetService(client)
            fill = WeeklyFillService(db, ts)
            result = fill.run_week(
                user=user,
                user_uri=cred.user_uri,
                week_date=date.today(),
                template_id=job.template_id,
            )
            schedules.mark_run(job, result.get("status", "unknown"))
            db.commit()
        finally:
            client.close()
    except Exception:
        logger.exception("scheduled_job_failed", extra={"job_id": scheduled_job_id})
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()
