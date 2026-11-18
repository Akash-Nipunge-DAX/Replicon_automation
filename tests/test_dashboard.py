"""Dashboard auth, templates, and weekly-fill unit tests (no live Replicon)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from app.db.models import User
from app.repositories.template_repository import TemplateRepository
from app.repositories.user_repository import UserRepository
from app.security.passwords import hash_password
from app.services.auth_service import AuthService
from app.services.weekly_fill_service import WeeklyFillService
from app.models.timesheet_models import (
    TimeEntryCreateResponse,
    TimesheetIdentity,
    TimesheetInspectResponse,
    TimesheetSubmitResponse,
)


def test_register_and_login(client):
    r = client.post(
        "/register",
        data={
            "username": "alice",
            "password": "secret12",
            "password_confirm": "secret12",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/setup"

    r = client.post(
        "/login",
        data={"username": "alice", "password": "secret12"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_auth_service_rejects_short_password(db_session):
    auth = AuthService(db_session)
    try:
        auth.register("bob", "123")
        assert False, "expected AuthError"
    except Exception as exc:
        assert "6" in str(exc)


def test_default_template_seed(db_session):
    user = UserRepository(db_session).create(
        username="carol", password_hash=hash_password("secret12")
    )
    template = TemplateRepository(db_session).ensure_default_seed(user.id)
    assert template.name == "Default 9h"
    assert len(template.tasks) == 3
    assert {t.task_name for t in template.tasks} == {"Coding", "Management", "Meetings"}


def test_weekly_fill_skips_weekend_and_holiday(db_session):
    user = UserRepository(db_session).create(
        username="dave", password_hash=hash_password("secret12")
    )
    template = TemplateRepository(db_session).ensure_default_seed(user.id)

    summary_raw = {
        "d": {
            "actualsByDate": [
                {
                    "date": {"year": 2026, "month": 10, "day": 4},
                    "isWeeklyDayOff": True,
                    "isHolidayDayOff": False,
                },
                {
                    "date": {"year": 2026, "month": 10, "day": 5},
                    "isWeeklyDayOff": False,
                    "isHolidayDayOff": False,
                },
                {
                    "date": {"year": 2026, "month": 10, "day": 6},
                    "isWeeklyDayOff": False,
                    "isHolidayDayOff": True,
                },
            ],
            "approvalStatus": {"displayText": "Not Submitted", "uri": "urn:open"},
        }
    }

    mock_ts = MagicMock()
    mock_ts.inspect.return_value = TimesheetInspectResponse(
        timesheet=TimesheetIdentity(
            uri="urn:timesheet:1",
            display_text=".user/2026-10-4",
        ),
        summary={"raw": summary_raw},
        details={"raw": {}},
        tasks={"raw": {}},
    )
    mock_ts.create_time_entry.return_value = TimeEntryCreateResponse(
        status="created",
        message="ok",
        user_uri="urn:user:1",
        timesheet_uri="urn:timesheet:1",
        task_name="Coding",
        entry_date=date(2026, 10, 5),
        hours=3,
    )
    mock_ts.submit_timesheet.return_value = TimesheetSubmitResponse(
        status="submitted",
        message="ok",
        user_uri="urn:user:1",
        timesheet_uri="urn:timesheet:1",
        timesheet_display_text=".user/2026-10-4",
        date=date(2026, 10, 5),
    )

    result = WeeklyFillService(db_session, mock_ts).run_week(
        user=user,
        user_uri="urn:user:1",
        week_date=date(2026, 10, 5),
        template_id=template.id,
    )

    assert result["status"] == "success"
    assert result["fill_days"] == ["2026-10-05"]
    assert "2026-10-04" in result["skipped"]["weekends"]
    assert "2026-10-06" in result["skipped"]["holidays"]
    # One working day × 3 tasks
    assert mock_ts.create_time_entry.call_count == 3
    mock_ts.submit_timesheet.assert_called_once()
