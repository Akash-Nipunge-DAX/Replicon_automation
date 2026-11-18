"""Dashboard overview, setup, and history pages."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.dependencies import get_current_user, get_credential_service
from app.repositories.credential_repository import CredentialRepository
from app.repositories.fill_run_repository import FillRunRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.repositories.template_repository import TemplateRepository
from app.services.client_factory import RepliconClientFactory
from app.services.credential_service import CredentialError, CredentialService
from app.services.timesheet_service import TimesheetService
from app.services.weekly_fill_service import WeeklyFillService
from app.web.templating import templates

router = APIRouter(tags=["dashboard"])


def _require_configured(user: User, db: Session) -> RedirectResponse | None:
    if CredentialRepository(db).get_for_user(user.id) is None:
        return RedirectResponse("/setup", status_code=303)
    return None


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    year: int | None = Query(None),
    month: int | None = Query(None),
):
    redirect = _require_configured(user, db)
    if redirect:
        return redirect

    today = date.today()
    year = year or today.year
    month = month or today.month

    cred = CredentialRepository(db).get_for_user(user.id)
    assert cred is not None
    templates_repo = TemplateRepository(db)
    templates_list = templates_repo.list_for_user(user.id)
    if not templates_list:
        templates_repo.ensure_default_seed(user.id)
        templates_list = templates_repo.list_for_user(user.id)

    factory = RepliconClientFactory(get_settings())
    client = factory.from_credential(cred)
    week_cards: list = []
    overview_error = None
    try:
        fill = WeeklyFillService(db, TimesheetService(client))
        week_cards = fill.month_week_statuses(
            user_uri=cred.user_uri, year=year, month=month
        )
    except Exception as exc:  # noqa: BLE001 — surface on dashboard
        overview_error = str(exc)
    finally:
        client.close()

    runs = FillRunRepository(db).list_for_user(user.id, limit=5)
    schedules = ScheduleRepository(db).list_for_user(user.id)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "year": year,
            "month": month,
            "week_cards": week_cards,
            "overview_error": overview_error,
            "templates": templates_list,
            "recent_runs": runs,
            "schedules": schedules,
            "flash": request.session.pop("flash", None),
        },
    )


@router.get("/setup", response_class=HTMLResponse)
def setup_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    creds: CredentialService = Depends(get_credential_service),
):
    existing = creds.get(user.id)
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "user": user,
            "configured": existing is not None,
            "user_uri": existing.user_uri if existing else "",
            "base_url": existing.base_url if existing else settings.replicon_base_url,
            "error": None,
            "success": request.session.pop("flash", None),
        },
    )


@router.post("/setup")
def setup_submit(
    request: Request,
    user: User = Depends(get_current_user),
    user_uri: str = Form(...),
    access_token: str = Form(...),
    base_url: str = Form("https://na5.replicon.com"),
    creds: CredentialService = Depends(get_credential_service),
):
    try:
        creds.save_and_validate(
            user_id=user.id,
            user_uri=user_uri,
            access_token=access_token,
            base_url=base_url,
        )
    except CredentialError as exc:
        return templates.TemplateResponse(
            request,
            "setup.html",
            {
                "user": user,
                "configured": False,
                "user_uri": user_uri,
                "base_url": base_url,
                "error": exc.message,
                "success": None,
            },
            status_code=400,
        )
    request.session["flash"] = "Replicon credentials saved. Default template seeded."
    return RedirectResponse("/", status_code=303)


@router.get("/history", response_class=HTMLResponse)
def history_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    redirect = _require_configured(user, db)
    if redirect:
        return redirect
    import json

    runs = FillRunRepository(db).list_for_user(user.id, limit=100)
    parsed = []
    for run in runs:
        try:
            summary = json.loads(run.summary_json or "{}")
        except json.JSONDecodeError:
            summary = {}
        parsed.append({"run": run, "summary": summary})
    return templates.TemplateResponse(
        request,
        "history.html",
        {"user": user, "runs": parsed},
    )
