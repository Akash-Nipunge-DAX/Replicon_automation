"""Timesheet HTTP routes — inspect, time-entry create, weekly submit."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.dependencies import get_timesheet_service
from app.models.timesheet_models import (
    HealthResponse,
    TimeEntryCreateRequest,
    TimeEntryCreateResponse,
    TimesheetInspectResponse,
    TimesheetRequest,
    TimesheetSubmitRequest,
    TimesheetSubmitResponse,
    TimesheetUpdateRequest,
)
from app.services.timesheet_service import TimesheetService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["timesheets"])
health_router = APIRouter(tags=["health"])


@health_router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Liveness probe for load balancers and container orchestration.",
)
def health() -> HealthResponse:
    return HealthResponse(status="healthy")


@router.post(
    "/timesheets/inspect",
    response_model=TimesheetInspectResponse,
    summary="Inspect a timesheet (read-only)",
    description=(
        "Resolves the timesheet for a user/date via GetTimesheetForDate2, then "
        "fetches GetTimesheetSummary, BulkGetTimesheetDetails, and "
        "GetProjectTaskDetailsForTimesheet. Does not modify Replicon data."
    ),
)
def inspect_timesheet(
    request: TimesheetRequest,
    service: TimesheetService = Depends(get_timesheet_service),
) -> TimesheetInspectResponse:
    logger.info(
        "api_inspect",
        extra={
            "user_uri": request.user_uri,
            "date": request.date.isoformat(),
        },
    )
    return service.inspect(request.user_uri, request.date)


@router.post(
    "/timesheets/time-entry",
    response_model=TimeEntryCreateResponse,
    summary="Create a single time entry (PutTimeEntryRevisionGroup)",
    description=(
        "Creates one time-entry revision group for a user/date/task using "
        "TimeEntryRevisionGroupService1/PutTimeEntryRevisionGroup. "
        "Only user_uri, date, task_name, and hours are required — timesheet_uri "
        "is optional and auto-resolved from user_uri + date. "
        "Resolves task names dynamically. If an entry already exists for the same "
        "user/date/task and the timesheet is still open (not submitted), it is "
        "overwritten. If the timesheet is submitted/waiting/approved, the existing "
        "entry is left alone. "
        "Does not submit the weekly timesheet — use POST /timesheets/submit."
    ),
)
def create_time_entry(
    request: TimeEntryCreateRequest,
    service: TimesheetService = Depends(get_timesheet_service),
) -> TimeEntryCreateResponse:
    logger.info(
        "api_create_time_entry",
        extra={
            "user_uri": request.user_uri,
            "timesheet_uri": request.timesheet_uri,
            "task_name": request.task_name,
            "date": request.date.isoformat(),
            "hours": request.hours,
        },
    )
    return service.create_time_entry(
        user_uri=request.user_uri,
        timesheet_uri=request.timesheet_uri,
        task_name=request.task_name,
        entry_date=request.date,
        hours=request.hours,
    )


@router.post(
    "/timesheets/submit",
    response_model=TimesheetSubmitResponse,
    summary="Submit weekly timesheet (Submit2)",
    description=(
        "Submits the entire weekly timesheet for approval via "
        "TimesheetApprovalService1/Submit2 on na5. "
        "Provide user_uri and any date within the week — the timesheet period "
        "is resolved automatically. Call once per week after entries are filled. "
        "Does not approve/reject/reopen."
    ),
)
def submit_timesheet(
    request: TimesheetSubmitRequest,
    service: TimesheetService = Depends(get_timesheet_service),
) -> TimesheetSubmitResponse:
    logger.info(
        "api_submit_timesheet",
        extra={
            "user_uri": request.user_uri,
            "date": request.date.isoformat(),
            "timesheet_uri": request.timesheet_uri,
        },
    )
    return service.submit_timesheet(
        user_uri=request.user_uri,
        target_date=request.date,
        timesheet_uri=request.timesheet_uri,
        comments=request.comments,
        change_reason=request.change_reason,
    )


@router.post(
    "/timesheets/update",
    summary="Bulk timesheet update (DISABLED)",
    description=(
        "Intentionally disabled. Bulk weekly updates and PutStandardTimesheet2 "
        "are not used. Use POST /timesheets/time-entry for single "
        "PutTimeEntryRevisionGroup writes. This endpoint does NOT call Replicon."
    ),
    responses={
        501: {
            "description": "Bulk update not enabled",
            "content": {
                "application/json": {
                    "example": {
                        "detail": (
                            "Bulk timesheet update is disabled. Use "
                            "POST /timesheets/time-entry "
                            "(PutTimeEntryRevisionGroup) for single entries."
                        )
                    }
                }
            },
        }
    },
)
def update_timesheet(
    request: TimesheetUpdateRequest,
) -> JSONResponse:
    """Refuse bulk updates — single entries go through /timesheets/time-entry."""
    logger.warning(
        "api_update_rejected",
        extra={
            "user_uri": request.user_uri,
            "date": request.date.isoformat(),
            "allocation_count": len(request.allocations),
        },
    )
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "detail": (
                "Bulk timesheet update is disabled. Use "
                "POST /timesheets/time-entry (PutTimeEntryRevisionGroup) "
                "for single entries. PutStandardTimesheet2 is not used."
            )
        },
    )
