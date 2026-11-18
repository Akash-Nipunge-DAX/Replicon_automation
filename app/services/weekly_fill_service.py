"""Weekly timesheet fill orchestration.

Pattern — Facade + Template Method:
  One entry point (``run_week``) replaces the old AI/fill_prompt orchestration.
  The algorithm is fixed; task/hour/skip rules come from the user's FillTemplate
  (strategy data), so every user can customize without changing this code.
"""

from __future__ import annotations

import logging
from calendar import monthcalendar
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.clients.exceptions import RepliconAPIError, TimeEntryValidationError
from app.db.models import FillTemplate, User
from app.repositories.fill_run_repository import FillRunRepository
from app.repositories.template_repository import TemplateRepository
from app.services.timesheet_service import TimesheetService

logger = logging.getLogger(__name__)


class WeeklyFillService:
    """Fill every working day in a week using a template, then optionally submit."""

    def __init__(self, db: Session, timesheet_service: TimesheetService) -> None:
        self._db = db
        self._ts = timesheet_service
        self._templates = TemplateRepository(db)
        self._runs = FillRunRepository(db)

    def run_week(
        self,
        *,
        user: User,
        user_uri: str,
        week_date: date,
        template_id: int | None = None,
    ) -> dict[str, Any]:
        template = self._resolve_template(user.id, template_id)
        if not template.tasks:
            raise TimeEntryValidationError("Template has no tasks configured.")

        inspect = self._ts.inspect(user_uri=user_uri, target_date=week_date)
        fill_days, skipped = self._build_day_lists(inspect.summary.get("raw", {}), template)

        results: list[dict[str, Any]] = []
        created = updated = existing = errors = 0
        consecutive_failures = 0

        for day in fill_days:
            for task in template.tasks:
                try:
                    resp = self._ts.create_time_entry(
                        user_uri=user_uri,
                        task_name=task.task_name,
                        entry_date=day,
                        hours=task.hours,
                        timesheet_uri=inspect.timesheet.uri,
                    )
                    results.append(
                        {
                            "date": day.isoformat(),
                            "task": task.task_name,
                            "hours": task.hours,
                            "status": resp.status,
                        }
                    )
                    consecutive_failures = 0
                    if resp.status == "created":
                        created += 1
                    elif resp.status == "updated":
                        updated += 1
                    elif resp.status == "existing_entry":
                        existing += 1
                except (RepliconAPIError, TimeEntryValidationError) as exc:
                    consecutive_failures += 1
                    errors += 1
                    msg = getattr(exc, "message", str(exc))
                    results.append(
                        {
                            "date": day.isoformat(),
                            "task": task.task_name,
                            "hours": task.hours,
                            "status": "error",
                            "error": msg,
                        }
                    )
                    if consecutive_failures >= 3:
                        break
            if consecutive_failures >= 3:
                break

        submit_info: dict[str, Any] | None = None
        if (
            template.submit_after_fill
            and consecutive_failures < 3
            and (created + updated + existing) > 0
        ):
            try:
                submit_resp = self._ts.submit_timesheet(
                    user_uri=user_uri,
                    target_date=week_date,
                    timesheet_uri=inspect.timesheet.uri,
                )
                submit_info = {
                    "status": submit_resp.status,
                    "message": submit_resp.message,
                    "before_status": submit_resp.before_status,
                    "after_status": submit_resp.after_status,
                }
            except RepliconAPIError as exc:
                submit_info = {"status": "failed", "error": exc.message}
                errors += 1

        if errors and (created + updated + existing) == 0:
            run_status = "failed"
        elif errors:
            run_status = "partial"
        else:
            run_status = "success"

        summary = {
            "timesheet": inspect.timesheet.display_text or inspect.timesheet.uri,
            "timesheet_uri": inspect.timesheet.uri,
            "week_date": week_date.isoformat(),
            "template": template.name,
            "fill_days": [d.isoformat() for d in fill_days],
            "skipped": skipped,
            "created": created,
            "updated": updated,
            "existing": existing,
            "errors": errors,
            "submit": submit_info,
            "entries": results,
        }
        self._runs.create(
            user_id=user.id,
            template_id=template.id,
            week_date=week_date.isoformat(),
            status=run_status,
            summary=summary,
        )
        return {"status": run_status, **summary}

    def month_week_statuses(
        self,
        *,
        user_uri: str,
        year: int,
        month: int,
    ) -> list[dict[str, Any]]:
        """Inspect each distinct week that touches the given calendar month."""
        week_dates = _representative_week_dates(year, month)
        cards: list[dict[str, Any]] = []
        for week_date in week_dates:
            try:
                insp = self._ts.inspect(user_uri=user_uri, target_date=week_date)
                approval = _approval_from_summary(insp.summary.get("raw", {}))
                days = _day_hours_from_summary(insp.summary.get("raw", {}))
                cards.append(
                    {
                        "week_date": week_date.isoformat(),
                        "display": insp.timesheet.display_text,
                        "uri": insp.timesheet.uri,
                        "approval": approval,
                        "days": days,
                        "error": None,
                    }
                )
            except RepliconAPIError as exc:
                cards.append(
                    {
                        "week_date": week_date.isoformat(),
                        "display": None,
                        "uri": None,
                        "approval": "Error",
                        "days": [],
                        "error": exc.message,
                    }
                )
        return cards

    def _resolve_template(self, user_id: int, template_id: int | None) -> FillTemplate:
        if template_id is not None:
            template = self._templates.get_for_user(user_id, template_id)
            if template is None:
                raise TimeEntryValidationError("Template not found.")
            return template
        template = self._templates.get_default(user_id) or self._templates.ensure_default_seed(
            user_id
        )
        return template

    def _build_day_lists(
        self,
        summary_raw: dict[str, Any],
        template: FillTemplate,
    ) -> tuple[list[date], dict[str, list[str]]]:
        actuals = _actuals_by_date(summary_raw)
        fill_days: list[date] = []
        weekends: list[str] = []
        holidays: list[str] = []

        for item in actuals:
            d = _parse_replicon_date(item.get("date"))
            if d is None:
                continue
            iso = d.isoformat()
            weekly_off = bool(item.get("isWeeklyDayOff"))
            holiday = bool(item.get("isHolidayDayOff"))
            if template.skip_weekends and (weekly_off or d.weekday() >= 5):
                weekends.append(iso)
                continue
            if template.skip_holidays and holiday:
                holidays.append(iso)
                continue
            fill_days.append(d)

        return fill_days, {"weekends": weekends, "holidays": holidays}


def _actuals_by_date(summary_raw: dict[str, Any]) -> list[dict[str, Any]]:
    data = summary_raw.get("d") if isinstance(summary_raw, dict) else None
    if not isinstance(data, dict):
        data = summary_raw if isinstance(summary_raw, dict) else {}
    actuals = data.get("actualsByDate") or []
    return [a for a in actuals if isinstance(a, dict)]


def _parse_replicon_date(value: Any) -> date | None:
    if not isinstance(value, dict):
        return None
    try:
        return date(int(value["year"]), int(value["month"]), int(value["day"]))
    except (KeyError, TypeError, ValueError):
        return None


def _approval_from_summary(summary_raw: dict[str, Any]) -> str:
    data = summary_raw.get("d") if isinstance(summary_raw, dict) else None
    if not isinstance(data, dict):
        data = summary_raw if isinstance(summary_raw, dict) else {}
    approval = data.get("approvalStatus") or {}
    if isinstance(approval, dict):
        return str(approval.get("displayText") or approval.get("uri") or "Unknown")
    return "Unknown"


def _day_hours_from_summary(summary_raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in _actuals_by_date(summary_raw):
        d = _parse_replicon_date(item.get("date"))
        if d is None:
            continue
        work = item.get("workingTimeDuration") or {}
        total = item.get("totalTimeDuration") or {}
        rows.append(
            {
                "date": d.isoformat(),
                "weekly_off": bool(item.get("isWeeklyDayOff")),
                "holiday": bool(item.get("isHolidayDayOff")),
                "work_hours": int(work.get("hours") or 0),
                "total_hours": int(total.get("hours") or 0),
            }
        )
    return rows


def _representative_week_dates(year: int, month: int) -> list[date]:
    """One date per distinct week that intersects the month (Sunday-start weeks)."""
    seen: set[date] = set()
    result: list[date] = []
    for week in monthcalendar(year, month):
        # monthcalendar uses Monday-first; pick first non-zero day in the week row.
        days = [d for d in week if d != 0]
        if not days:
            continue
        sample = date(year, month, days[len(days) // 2])
        # Normalize to the Sunday that starts Replicon weeks (observed Sun–Sat).
        sunday = sample - timedelta(days=(sample.weekday() + 1) % 7)
        if sunday not in seen:
            seen.add(sunday)
            # Use a mid-week date for inspect stability.
            result.append(sunday + timedelta(days=2))
    return result
