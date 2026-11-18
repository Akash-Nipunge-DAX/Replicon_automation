"""Pydantic models for timesheet request/response payloads."""

from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RepliconDate(BaseModel):
    """Replicon calendar date object (year/month/day — not a UTC timestamp)."""

    year: int
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)

    @classmethod
    def from_date(cls, value: datetime.date) -> RepliconDate:
        return cls(year=value.year, month=value.month, day=value.day)

    def to_date(self) -> datetime.date:
        return datetime.date(self.year, self.month, self.day)


class TimesheetRequest(BaseModel):
    """Request body for timesheet inspection endpoints."""

    user_uri: str = Field(
        ...,
        min_length=1,
        description=(
            "Replicon user URI, e.g. "
            "urn:replicon-tenant:...:user:..."
        ),
        examples=["urn:replicon-tenant:53dfa1643ee24f85b3d0e99144356ec2:user:EXAMPLE"],
    )
    # Field name is "date"; use datetime.date to avoid Python 3.10 name clash
    # with from __future__ import annotations + Pydantic evaluation.
    date: datetime.date = Field(
        ...,
        description="Calendar date within the timesheet period (YYYY-MM-DD).",
        examples=["2026-09-15"],
    )

    @field_validator("user_uri")
    @classmethod
    def user_uri_must_not_be_placeholder(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in {"string", "useruri", "<user uri>"}:
            raise ValueError(
                "user_uri must be a real Replicon user URI, not a placeholder"
            )
        return cleaned


class Allocation(BaseModel):
    """Allocation entry used by the disabled bulk update endpoint."""

    task: str = Field(..., min_length=1, description="Task name or task URI.")
    hours: float = Field(..., gt=0, description="Hours to allocate (must be > 0).")


class TimesheetUpdateRequest(BaseModel):
    """Legacy bulk update request model.

    ``POST /timesheets/update`` remains disabled. Single-entry writes use
    ``POST /timesheets/time-entry`` via PutTimeEntryRevisionGroup instead.
    """

    user_uri: str = Field(..., min_length=1)
    date: datetime.date
    allocations: list[Allocation] = Field(..., min_length=1)


class TimeEntryCreateRequest(BaseModel):
    """Request body for creating a single time-entry revision group."""

    user_uri: str = Field(
        ...,
        min_length=1,
        description="Replicon user URI that owns the timesheet.",
    )
    timesheet_uri: str | None = Field(
        default=None,
        description=(
            "Optional timesheet URI. If omitted, it is resolved automatically "
            "from user_uri + date via GetTimesheetForDate2."
        ),
    )
    task_name: str = Field(
        ...,
        min_length=1,
        description='Task display name to resolve dynamically, e.g. "Meetings".',
        examples=["Meetings", "Coding", "Management"],
    )
    date: datetime.date = Field(
        ...,
        description="Calendar date for the time entry (YYYY-MM-DD).",
        examples=["2026-09-21"],
    )
    hours: float = Field(
        ...,
        gt=0,
        description="Hours to allocate (must be > 0). Fractional hours are supported.",
        examples=[3],
    )

    @field_validator("user_uri", "task_name")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @field_validator("timesheet_uri")
    @classmethod
    def strip_optional_timesheet_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class TimeEntryCreateResponse(BaseModel):
    """Result of a single time-entry create attempt (or duplicate detection)."""

    status: str = Field(
        ...,
        description=(
            "`created` for a new revision group; "
            "`updated` when an existing entry is overwritten on an open timesheet; "
            "`existing_entry` when the timesheet is submitted/locked and the entry "
            "already exists."
        ),
    )
    message: str
    user_uri: str
    timesheet_uri: str
    task_name: str
    task_uri: str | None = None
    entry_date: datetime.date
    hours: float
    time_entry_revision_group_uri: str | None = None
    unit_of_work_id: str | None = None
    existing_entry: dict[str, Any] | None = None
    replicon: dict[str, Any] | None = Field(
        default=None,
        description="Sanitized Replicon put result when status=created.",
    )
    warnings: list[str] = Field(default_factory=list)
    schema_notes: list[str] = Field(
        default_factory=list,
        description="Documented assumptions / unresolved schema notes for operators.",
    )


class TimesheetSubmitRequest(BaseModel):
    """Submit an entire weekly timesheet for approval (once per period)."""

    user_uri: str = Field(
        ...,
        min_length=1,
        description="Replicon user URI that owns the timesheet.",
    )
    date: datetime.date = Field(
        ...,
        description=(
            "Any calendar date within the weekly timesheet period. "
            "The timesheet is resolved via GetTimesheetForDate2."
        ),
        examples=["2026-09-21"],
    )
    timesheet_uri: str | None = Field(
        default=None,
        description=(
            "Optional timesheet URI. If omitted, resolved from user_uri + date. "
            "If provided, must match the resolved timesheet."
        ),
    )
    comments: str | None = Field(
        default=None,
        description="Optional comments included with Submit2.",
    )
    change_reason: str | None = Field(
        default=None,
        description="Optional changeReason included with Submit2.",
    )

    @field_validator("user_uri")
    @classmethod
    def strip_user_uri(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("user_uri must not be empty")
        return cleaned

    @field_validator("timesheet_uri")
    @classmethod
    def strip_optional_timesheet_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class TimesheetSubmitResponse(BaseModel):
    """Result of a weekly timesheet submit attempt."""

    status: str = Field(
        ...,
        description=(
            "`submitted` when Submit2 succeeds; "
            "`already_submitted` when summary indicates the timesheet is "
            "already waiting for approval / submitted / approved."
        ),
    )
    message: str
    user_uri: str
    timesheet_uri: str
    timesheet_display_text: str | None = None
    date: datetime.date
    unit_of_work_id: str | None = None
    before_status: str | None = None
    after_status: str | None = None
    summary_before: dict[str, Any] | None = None
    summary_after: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    schema_notes: list[str] = Field(default_factory=list)


class TimesheetIdentity(BaseModel):
    """Normalized timesheet identity extracted from GetTimesheetForDate2."""

    uri: str
    display_text: str | None = None
    slug: str | None = None
    format: str | None = None


class TimesheetInspectResponse(BaseModel):
    """Combined read-only inspection result for a timesheet period."""

    timesheet: TimesheetIdentity
    summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Wrapper containing raw GetTimesheetSummary payload.",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Wrapper containing raw BulkGetTimesheetDetails payload.",
    )
    tasks: dict[str, Any] = Field(
        default_factory=dict,
        description="Wrapper containing raw GetProjectTaskDetailsForTimesheet payload.",
    )
    warnings: list[str] = Field(default_factory=list)

    model_config = {
        "json_schema_extra": {
            "example": {
                "timesheet": {
                    "uri": (
                        "urn:replicon-tenant:53dfa1643ee24f85b3d0e99144356ec2:"
                        "timesheet:501a22e2-3d89-44bf-a7e6-ec35f948e871"
                    ),
                    "display_text": ".akash-nipunge/2026-9-6",
                    "slug": ".akash-nipunge/2026-9-6",
                    "format": "urn:replicon:policy:timesheet:timesheet-format:gen4-timesheet",
                },
                "summary": {"raw": {}},
                "details": {"raw": {}},
                "tasks": {"raw": {}},
                "warnings": [],
            }
        }
    }


class HealthResponse(BaseModel):
    """Liveness probe response."""

    status: str = "healthy"
