"""Manual weekly fill trigger from the dashboard."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.dependencies import get_current_user
from app.repositories.credential_repository import CredentialRepository
from app.services.client_factory import RepliconClientFactory
from app.services.timesheet_service import TimesheetService
from app.services.weekly_fill_service import WeeklyFillService

router = APIRouter(tags=["fill"])


@router.post("/fill/run")
def run_fill(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    week_date: str = Form(...),
    template_id: int = Form(...),
):
    cred = CredentialRepository(db).get_for_user(user.id)
    if cred is None:
        return RedirectResponse("/setup", status_code=303)

    try:
        parsed = datetime.strptime(week_date, "%Y-%m-%d").date()
    except ValueError:
        request.session["flash"] = "Invalid week date."
        return RedirectResponse("/", status_code=303)

    client = RepliconClientFactory(get_settings()).from_credential(cred)
    try:
        result = WeeklyFillService(db, TimesheetService(client)).run_week(
            user=user,
            user_uri=cred.user_uri,
            week_date=parsed,
            template_id=template_id,
        )
        request.session["flash"] = (
            f"Fill {result['status']}: created={result['created']} "
            f"updated={result['updated']} errors={result['errors']} "
            f"submit={(result.get('submit') or {}).get('status', 'n/a')}"
        )
    except Exception as exc:  # noqa: BLE001
        request.session["flash"] = f"Fill failed: {exc}"
    finally:
        client.close()

    return RedirectResponse("/history", status_code=303)
