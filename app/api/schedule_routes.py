"""Scheduled fill job CRUD + APScheduler reload."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_db
from app.dependencies import get_current_user
from app.repositories.credential_repository import CredentialRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.repositories.template_repository import TemplateRepository
from app.services.scheduler_service import reload_jobs
from app.web.templating import templates

router = APIRouter(prefix="/schedules", tags=["schedules"])

WEEKDAYS = [
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
]


def _require_configured(user: User, db: Session) -> RedirectResponse | None:
    if CredentialRepository(db).get_for_user(user.id) is None:
        return RedirectResponse("/setup", status_code=303)
    return None


@router.get("", response_class=HTMLResponse)
def list_schedules(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    redirect = _require_configured(user, db)
    if redirect:
        return redirect
    jobs = ScheduleRepository(db).list_for_user(user.id)
    tmpl = TemplateRepository(db).list_for_user(user.id)
    return templates.TemplateResponse(
        request,
        "schedules.html",
        {
            "user": user,
            "jobs": jobs,
            "templates": tmpl,
            "weekdays": WEEKDAYS,
            "flash": request.session.pop("flash", None),
            "error": None,
        },
    )


@router.post("")
def create_schedule(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    template_id: int = Form(...),
    weekday: int = Form(...),
    hour: int = Form(...),
    minute: int = Form(0),
    enabled: str | None = Form(None),
):
    if TemplateRepository(db).get_for_user(user.id, template_id) is None:
        request.session["flash"] = "Invalid template."
        return RedirectResponse("/schedules", status_code=303)
    ScheduleRepository(db).create(
        user_id=user.id,
        template_id=template_id,
        weekday=max(0, min(6, weekday)),
        hour=max(0, min(23, hour)),
        minute=max(0, min(59, minute)),
        enabled=(enabled or "").lower() in {"true", "1", "on", "yes"},
    )
    reload_jobs()
    request.session["flash"] = "Schedule created (times are UTC)."
    return RedirectResponse("/schedules", status_code=303)


@router.post("/{job_id}/toggle")
def toggle_schedule(
    job_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repo = ScheduleRepository(db)
    job = repo.get_for_user(user.id, job_id)
    if job is not None:
        repo.update(
            job,
            template_id=job.template_id,
            weekday=job.weekday,
            hour=job.hour,
            minute=job.minute,
            enabled=not job.enabled,
        )
        reload_jobs()
        request.session["flash"] = "Schedule updated."
    return RedirectResponse("/schedules", status_code=303)


@router.post("/{job_id}/delete")
def delete_schedule(
    job_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    repo = ScheduleRepository(db)
    job = repo.get_for_user(user.id, job_id)
    if job is not None:
        repo.delete(job)
        reload_jobs()
        request.session["flash"] = "Schedule deleted."
    return RedirectResponse("/schedules", status_code=303)
