"""Unit tests for Replicon timesheet automation (no live API calls)."""

from __future__ import annotations

import os
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure settings load without a real token for app import in most tests
os.environ.setdefault("REPLICON_BASE_URL", "https://na5.replicon.com")
os.environ.setdefault("REPLICON_ACCESS_TOKEN", "test-token-not-real")

from app.clients.exceptions import (  # noqa: E402
    RepliconAPIError,
    RepliconAuthError,
    RepliconInvalidResponseError,
)
from app.clients.replicon_client import RepliconClient  # noqa: E402
from app.dependencies import clear_dependency_caches  # noqa: E402
from app.main import app  # noqa: E402
from app.models.timesheet_models import RepliconDate, TimesheetRequest  # noqa: E402
from app.services.timesheet_service import TimesheetService  # noqa: E402


EXAMPLE_USER_URI = (
    "urn:replicon-tenant:53dfa1643ee24f85b3d0e99144356ec2:user:example"
)
EXAMPLE_TIMESHEET_URI = (
    "urn:replicon-tenant:53dfa1643ee24f85b3d0e99144356ec2:"
    "timesheet:501a22e2-3d89-44bf-a7e6-ec35f948e871"
)
EXAMPLE_DATE = date(2026, 9, 15)


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    clear_dependency_caches()
    yield
    clear_dependency_caches()


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock(spec=RepliconClient)
    client.unwrap_d.side_effect = lambda response, operation: (
        RepliconClient.unwrap_d(response, operation=operation)
    )
    return client


@pytest.fixture
def service(mock_client: MagicMock) -> TimesheetService:
    return TimesheetService(mock_client)


# ---------------------------------------------------------------------------
# Date / payload helpers
# ---------------------------------------------------------------------------


def test_replicon_date_conversion() -> None:
    rd = RepliconDate.from_date(EXAMPLE_DATE)
    assert rd.model_dump() == {"year": 2026, "month": 9, "day": 15}
    assert rd.to_date() == EXAMPLE_DATE


def test_get_timesheet_for_date_payload_creation() -> None:
    payload = TimesheetService.build_get_timesheet_for_date_payload(
        EXAMPLE_USER_URI,
        EXAMPLE_DATE,
    )
    assert payload == {
        "userUri": EXAMPLE_USER_URI,
        "date": {"year": 2026, "month": 9, "day": 15},
        "timesheetGetOptionUri": (
            "urn:replicon:timesheet-get-option:create-timesheet-if-necessary"
        ),
    }


def test_timesheet_request_rejects_placeholder_user_uri() -> None:
    with pytest.raises(Exception):
        TimesheetRequest(user_uri="string", date=EXAMPLE_DATE)


# ---------------------------------------------------------------------------
# Mocked GetTimesheetForDate2 response (documentation example)
# ---------------------------------------------------------------------------


def _get_timesheet_for_date_response() -> dict[str, Any]:
    return {
        "d": {
            "timesheet": {
                "displayText": ".akash-nipunge/2026-9-6",
                "slug": ".akash-nipunge/2026-9-6",
                "uri": EXAMPLE_TIMESHEET_URI,
            },
            "timesheetFormat": (
                "urn:replicon:policy:timesheet:timesheet-format:gen4-timesheet"
            ),
        }
    }


def _summary_response_45h() -> dict[str, Any]:
    """Mock summary consistent with Coding/Management/Meetings 3+3+3 × 5 days."""
    return {
        "d": {
            "actualPayableTimeCalculationStatus": "valid",
            "actualsByProject": [
                {
                    "project": {
                        "displayText": "DP - Core Service",
                        "uri": (
                            "urn:replicon-tenant:53dfa1643ee24f85b3d0e99144356ec2:"
                            "project:16999"
                        ),
                    },
                    "total": {"hours": 45, "minutes": 0, "seconds": 0},
                }
            ],
            "approvalStatus": {"displayText": "Approved"},
            "timesheetStatus": {"displayText": "Approved"},
            "workingTimeDuration": {"hours": 45, "minutes": 0, "seconds": 0},
        }
    }


def _details_response(
    start: date = date(2026, 9, 6),
    end: date = date(2026, 9, 12),
) -> dict[str, Any]:
    return {
        "d": [
            {
                "uri": EXAMPLE_TIMESHEET_URI,
                "dateRange": {
                    "startDate": {
                        "year": start.year,
                        "month": start.month,
                        "day": start.day,
                    },
                    "endDate": {
                        "year": end.year,
                        "month": end.month,
                        "day": end.day,
                    },
                },
                "attestationStatusUri": None,
                "customFields": [],
            }
        ]
    }


def _tasks_response(
    start: date = date(2026, 8, 30),
    end: date = date(2026, 9, 5),
) -> dict[str, Any]:
    """Task allocation range intentionally different from Sep 6–12 period."""

    def task_entry(name: str, task_id: str) -> dict[str, Any]:
        return {
            "dateRangeWhereTimeAllocationIsAllowed": {
                "startDate": {
                    "year": start.year,
                    "month": start.month,
                    "day": start.day,
                },
                "endDate": {"year": end.year, "month": end.month, "day": end.day},
            },
            "task": {
                "parentTask": None,
                "task": {
                    "code": None,
                    "displayText": name,
                    "name": name,
                    "uri": (
                        "urn:replicon-tenant:53dfa1643ee24f85b3d0e99144356ec2:"
                        f"task:{task_id}"
                    ),
                },
            },
        }

    return {
        "d": {
            "projects": [],
            "tasks": [
                task_entry("Coding", "132443"),
                task_entry("Management", "132444"),
                task_entry("Meetings", "132445"),
            ],
        }
    }


def test_extract_timesheet_uri(service: TimesheetService) -> None:
    data = RepliconClient.unwrap_d(
        _get_timesheet_for_date_response(),
        operation="GetTimesheetForDate2",
    )
    identity = service.extract_timesheet_identity(data)
    assert identity.uri == EXAMPLE_TIMESHEET_URI
    assert identity.display_text == ".akash-nipunge/2026-9-6"
    assert identity.slug == ".akash-nipunge/2026-9-6"
    assert "gen4-timesheet" in (identity.format or "")


def test_missing_timesheet_response(service: TimesheetService) -> None:
    with pytest.raises(RepliconInvalidResponseError):
        service.extract_timesheet_identity({"something": "else"})


def test_get_summary(service: TimesheetService, mock_client: MagicMock) -> None:
    mock_client.post.return_value = _summary_response_45h()
    result = service.get_summary(EXAMPLE_TIMESHEET_URI)
    mock_client.post.assert_called_once_with(
        "TimesheetService1",
        "GetTimesheetSummary",
        {"timesheetUri": EXAMPLE_TIMESHEET_URI},
    )
    assert result["d"]["workingTimeDuration"]["hours"] == 45


def test_get_project_task_details(
    service: TimesheetService,
    mock_client: MagicMock,
) -> None:
    mock_client.post.return_value = _tasks_response()
    result = service.get_project_task_details(EXAMPLE_TIMESHEET_URI)
    mock_client.post.assert_called_once_with(
        "TimesheetService1",
        "GetProjectTaskDetailsForTimesheet",
        {"timesheetUri": EXAMPLE_TIMESHEET_URI},
    )
    tasks = result["d"]["tasks"]
    names = [t["task"]["task"]["displayText"] for t in tasks]
    assert names == ["Coding", "Management", "Meetings"]


def test_inspect_workflow(service: TimesheetService, mock_client: MagicMock) -> None:
    mock_client.post.side_effect = [
        _get_timesheet_for_date_response(),  # GetTimesheetForDate2
        _summary_response_45h(),  # GetTimesheetSummary
        _details_response(),  # BulkGetTimesheetDetails
        _tasks_response(),  # GetProjectTaskDetailsForTimesheet
    ]

    result = service.inspect(EXAMPLE_USER_URI, EXAMPLE_DATE)

    assert result.timesheet.uri == EXAMPLE_TIMESHEET_URI
    assert result.summary["raw"]["d"]["workingTimeDuration"]["hours"] == 45
    assert "raw" in result.details
    assert len(result.tasks["raw"]["d"]["tasks"]) == 3
    # Task range Aug 30–Sep 5 vs timesheet Sep 6–12 → warnings
    assert any(
        "does not match timesheet period" in w for w in result.warnings
    )

    operations = [call.args[1] for call in mock_client.post.call_args_list]
    assert operations == [
        "GetTimesheetForDate2",
        "GetTimesheetSummary",
        "BulkGetTimesheetDetails",
        "GetProjectTaskDetailsForTimesheet",
    ]


def test_update_timesheet_not_implemented(service: TimesheetService) -> None:
    with pytest.raises(NotImplementedError, match="PutTimeEntryRevisionGroup"):
        service.update_timesheet()


# ---------------------------------------------------------------------------
# Time entry write path (mocked — never hits real Replicon)
# ---------------------------------------------------------------------------


MEETINGS_TASK_URI = (
    "urn:replicon-tenant:53dfa1643ee24f85b3d0e99144356ec2:task:132445"
)
ENTRY_DATE = date(2026, 9, 21)


def _existing_revision_group(task_uri: str = MEETINGS_TASK_URI) -> dict[str, Any]:
    return {
        "uri": (
            "urn:replicon-tenant:53dfa1643ee24f85b3d0e99144356ec2:"
            "time-entry-revision-group:existing-not-for-reuse"
        ),
        "entryDate": {"year": 2026, "month": 9, "day": 21},
        "customMetadata": [
            {
                "keyUri": "urn:replicon:time-entry-metadata-key:task",
                "value": {"uri": task_uri},
            }
        ],
    }


def test_client_put_time_entry_endpoint() -> None:
    client = RepliconClient("https://na5.replicon.com/", "token")
    url = client.build_url(
        "TimeEntryRevisionGroupService1",
        "PutTimeEntryRevisionGroup",
    )
    assert url == (
        "https://na5.replicon.com/services/"
        "TimeEntryRevisionGroupService1.svc/PutTimeEntryRevisionGroup"
    )
    client.close()


def test_task_lookup_resolves_coding_management_meetings(
    service: TimesheetService,
) -> None:
    tasks_raw = _tasks_response()
    assert "task:132443" in service.resolve_task_uri(tasks_raw, "Coding")
    assert "task:132444" in service.resolve_task_uri(tasks_raw, "Management")
    assert "task:132445" in service.resolve_task_uri(tasks_raw, "Meetings")
    assert "task:132445" in service.resolve_task_uri(tasks_raw, "meetings")


def test_hours_validation_rejects_non_positive(
    service: TimesheetService,
    mock_client: MagicMock,
) -> None:
    from app.clients.exceptions import TimeEntryValidationError

    with pytest.raises(TimeEntryValidationError, match="hours must be greater"):
        service.create_time_entry(
            user_uri=EXAMPLE_USER_URI,
            timesheet_uri=EXAMPLE_TIMESHEET_URI,
            task_name="Meetings",
            entry_date=ENTRY_DATE,
            hours=0,
        )
    mock_client.post.assert_not_called()


def test_request_model_rejects_hours_lte_zero() -> None:
    from pydantic import ValidationError
    from app.models.timesheet_models import TimeEntryCreateRequest

    with pytest.raises(ValidationError):
        TimeEntryCreateRequest(
            user_uri=EXAMPLE_USER_URI,
            timesheet_uri=EXAMPLE_TIMESHEET_URI,
            task_name="Meetings",
            date=ENTRY_DATE,
            hours=0,
        )


def test_duplicate_on_open_timesheet_overwrites(
    service: TimesheetService,
    mock_client: MagicMock,
) -> None:
    existing_uri = (
        "urn:replicon-tenant:53dfa1643ee24f85b3d0e99144356ec2:"
        "time-entry-revision-group:existing-not-for-reuse"
    )
    mock_client.post.side_effect = [
        {
            "d": {
                "timesheet": {
                    "uri": EXAMPLE_TIMESHEET_URI,
                    "displayText": ".akash-nipunge/2026-9-20",
                    "slug": ".akash-nipunge/2026-9-20",
                },
                "timesheetFormat": "urn:replicon:policy:timesheet:timesheet-format:gen4-timesheet",
            }
        },
        _details_response(start=date(2026, 9, 20), end=date(2026, 9, 26)),
        _tasks_response(start=date(2026, 9, 20), end=date(2026, 9, 26)),
        {"d": {"timesheetStatus": {"displayText": "Not Submitted"}}},
    ]
    mock_client.get_time_entry_revision_groups_for_user_and_date_range.return_value = {
        "d": [_existing_revision_group()]
    }
    mock_client.put_time_entry_revision_group.return_value = {
        "d": {"uri": existing_uri}
    }

    result = service.create_time_entry(
        user_uri=EXAMPLE_USER_URI,
        timesheet_uri=EXAMPLE_TIMESHEET_URI,
        task_name="Meetings",
        entry_date=ENTRY_DATE,
        hours=3,
    )
    assert result.status == "updated"
    put_payload = mock_client.put_time_entry_revision_group.call_args.args[0]
    assert put_payload["timeEntryRevisionGroup"]["target"] == {"uri": existing_uri}


def test_duplicate_on_submitted_timesheet_skips_write(
    service: TimesheetService,
    mock_client: MagicMock,
) -> None:
    mock_client.post.side_effect = [
        {
            "d": {
                "timesheet": {
                    "uri": EXAMPLE_TIMESHEET_URI,
                    "displayText": ".akash-nipunge/2026-9-20",
                    "slug": ".akash-nipunge/2026-9-20",
                },
                "timesheetFormat": "urn:replicon:policy:timesheet:timesheet-format:gen4-timesheet",
            }
        },
        _details_response(start=date(2026, 9, 20), end=date(2026, 9, 26)),
        _tasks_response(start=date(2026, 9, 20), end=date(2026, 9, 26)),
        {"d": {"timesheetStatus": {"displayText": "Waiting for Approval"}}},
    ]
    mock_client.get_time_entry_revision_groups_for_user_and_date_range.return_value = {
        "d": [_existing_revision_group()]
    }

    result = service.create_time_entry(
        user_uri=EXAMPLE_USER_URI,
        timesheet_uri=EXAMPLE_TIMESHEET_URI,
        task_name="Meetings",
        entry_date=ENTRY_DATE,
        hours=3,
    )
    assert result.status == "existing_entry"
    mock_client.put_time_entry_revision_group.assert_not_called()


def test_create_single_meetings_entry(
    service: TimesheetService,
    mock_client: MagicMock,
) -> None:
    created_uri = (
        "urn:replicon-tenant:53dfa1643ee24f85b3d0e99144356ec2:"
        "time-entry-revision-group:new-created-uri"
    )
    mock_client.post.side_effect = [
        {
            "d": {
                "timesheet": {
                    "uri": EXAMPLE_TIMESHEET_URI,
                    "displayText": ".akash-nipunge/2026-9-20",
                    "slug": ".akash-nipunge/2026-9-20",
                },
                "timesheetFormat": "urn:replicon:policy:timesheet:timesheet-format:gen4-timesheet",
            }
        },
        _details_response(start=date(2026, 9, 20), end=date(2026, 9, 26)),
        _tasks_response(start=date(2026, 9, 20), end=date(2026, 9, 26)),
    ]
    mock_client.get_time_entry_revision_groups_for_user_and_date_range.return_value = {
        "d": []
    }
    mock_client.put_time_entry_revision_group.return_value = {
        "d": {"uri": created_uri, "parameterCorrelationId": None}
    }

    # timesheet_uri omitted — resolved from user_uri + date
    result = service.create_time_entry(
        user_uri=EXAMPLE_USER_URI,
        task_name="Meetings",
        entry_date=ENTRY_DATE,
        hours=3,
    )

    assert result.status == "created"
    assert result.timesheet_uri == EXAMPLE_TIMESHEET_URI
    assert result.task_uri == MEETINGS_TASK_URI
    assert result.time_entry_revision_group_uri == created_uri
    assert result.hours == 3
    assert result.unit_of_work_id is not None

    put_payload = mock_client.put_time_entry_revision_group.call_args.args[0]
    assert put_payload["timeEntryRevisionGroup"]["target"] is None
    assert put_payload["timeEntryRevisionGroup"]["user"]["uri"] == EXAMPLE_USER_URI
    assert put_payload["timeEntryRevisionGroup"]["interval"]["hours"] == {
        "hours": 3,
        "minutes": 0,
        "seconds": 0,
    }
    assert put_payload["unitOfWorkId"].startswith("replicon-automation-")
    # Never reuse a hardcoded existing revision-group URI
    assert "8e6473ab-8a24-4c8a-94e8-49ed3caec726" not in str(put_payload)


def test_put_payload_builder_target_is_null() -> None:
    payload = TimesheetService.build_put_time_entry_revision_group_payload(
        user_uri=EXAMPLE_USER_URI,
        task_uri=MEETINGS_TASK_URI,
        entry_date=ENTRY_DATE,
        hours=3,
        unit_of_work_id="replicon-automation-test",
    )
    assert payload["timeEntryRevisionGroup"]["target"] is None
    assert payload["unitOfWorkId"] == "replicon-automation-test"


def test_time_entry_endpoint_created(
    api_client: TestClient,
    mock_client: MagicMock,
) -> None:
    created_uri = (
        "urn:replicon-tenant:53dfa1643ee24f85b3d0e99144356ec2:"
        "time-entry-revision-group:api-created"
    )
    mock_client.post.side_effect = [
        {
            "d": {
                "timesheet": {
                    "uri": EXAMPLE_TIMESHEET_URI,
                    "displayText": "x",
                    "slug": "x",
                },
                "timesheetFormat": "gen4",
            }
        },
        _details_response(start=date(2026, 9, 20), end=date(2026, 9, 26)),
        _tasks_response(start=date(2026, 9, 20), end=date(2026, 9, 26)),
    ]
    mock_client.get_time_entry_revision_groups_for_user_and_date_range.return_value = {
        "d": []
    }
    mock_client.put_time_entry_revision_group.return_value = {
        "d": {"uri": created_uri}
    }

    response = api_client.post(
        "/timesheets/time-entry",
        json={
            "user_uri": EXAMPLE_USER_URI,
            "task_name": "Meetings",
            "date": "2026-09-21",
            "hours": 3,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert body["task_name"] == "Meetings"
    assert body["timesheet_uri"] == EXAMPLE_TIMESHEET_URI
    assert body["time_entry_revision_group_uri"] == created_uri


def test_time_entry_endpoint_rejects_hours_zero(api_client: TestClient) -> None:
    response = api_client.post(
        "/timesheets/time-entry",
        json={
            "user_uri": EXAMPLE_USER_URI,
            "task_name": "Meetings",
            "date": "2026-09-21",
            "hours": 0,
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Weekly submit (Submit2) — mocked
# ---------------------------------------------------------------------------


def test_client_submit2_endpoint() -> None:
    client = RepliconClient("https://na5.replicon.com/", "token")
    url = client.build_url("TimesheetApprovalService1", "Submit2")
    assert url == (
        "https://na5.replicon.com/services/"
        "TimesheetApprovalService1.svc/Submit2"
    )
    client.close()


def test_build_submit2_payload() -> None:
    payload = TimesheetService.build_submit2_payload(
        timesheet_uri=EXAMPLE_TIMESHEET_URI,
        unit_of_work_id="replicon-automation-test",
        comments="week done",
        change_reason=None,
    )
    assert payload == {
        "timesheetUri": EXAMPLE_TIMESHEET_URI,
        "unitOfWorkId": "replicon-automation-test",
        "comments": "week done",
    }
    assert "changeReason" not in payload


def test_submit_weekly_timesheet(
    service: TimesheetService,
    mock_client: MagicMock,
) -> None:
    mock_client.post.side_effect = [
        {
            "d": {
                "timesheet": {
                    "uri": EXAMPLE_TIMESHEET_URI,
                    "displayText": ".akash-nipunge/2026-9-20",
                    "slug": ".akash-nipunge/2026-9-20",
                },
                "timesheetFormat": "gen4",
            }
        },
        {
            "d": {
                "timesheetStatus": {"displayText": "Open"},
                "approvalStatus": {"displayText": "Not Submitted"},
            }
        },
        {
            "d": {
                "timesheetStatus": {"displayText": "Waiting"},
                "approvalStatus": {"displayText": "Waiting"},
            }
        },
    ]
    mock_client.submit_timesheet.return_value = {"d": None}

    result = service.submit_timesheet(
        user_uri=EXAMPLE_USER_URI,
        target_date=ENTRY_DATE,
    )
    assert result.status == "submitted"
    assert result.timesheet_uri == EXAMPLE_TIMESHEET_URI
    assert result.before_status == "Open"
    assert result.after_status == "Waiting"
    assert result.unit_of_work_id is not None

    put_payload = mock_client.submit_timesheet.call_args.args[0]
    assert put_payload["timesheetUri"] == EXAMPLE_TIMESHEET_URI
    assert put_payload["unitOfWorkId"].startswith("replicon-automation-")


def test_submit_skips_when_already_waiting(
    service: TimesheetService,
    mock_client: MagicMock,
) -> None:
    mock_client.post.side_effect = [
        {
            "d": {
                "timesheet": {
                    "uri": EXAMPLE_TIMESHEET_URI,
                    "displayText": "x",
                    "slug": "x",
                },
                "timesheetFormat": "gen4",
            }
        },
        {
            "d": {
                "timesheetStatus": {"displayText": "Waiting for Approval"},
            }
        },
    ]

    result = service.submit_timesheet(
        user_uri=EXAMPLE_USER_URI,
        target_date=ENTRY_DATE,
    )
    assert result.status == "already_submitted"
    mock_client.submit_timesheet.assert_not_called()


def test_submit_endpoint(
    api_client: TestClient,
    mock_client: MagicMock,
) -> None:
    mock_client.post.side_effect = [
        {
            "d": {
                "timesheet": {
                    "uri": EXAMPLE_TIMESHEET_URI,
                    "displayText": "x",
                    "slug": "x",
                },
                "timesheetFormat": "gen4",
            }
        },
        {"d": {"timesheetStatus": {"displayText": "Open"}}},
        {"d": {"timesheetStatus": {"displayText": "Waiting"}}},
    ]
    mock_client.submit_timesheet.return_value = {"d": None}

    response = api_client.post(
        "/timesheets/submit",
        json={
            "user_uri": EXAMPLE_USER_URI,
            "date": "2026-09-21",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "submitted"
    assert body["timesheet_uri"] == EXAMPLE_TIMESHEET_URI



# ---------------------------------------------------------------------------
# RepliconClient error handling
# ---------------------------------------------------------------------------


def test_client_build_url() -> None:
    client = RepliconClient("https://na5.replicon.com/", "token")
    url = client.build_url("TimesheetService1", "GetTimesheetForDate2")
    assert url == (
        "https://na5.replicon.com/services/TimesheetService1.svc/GetTimesheetForDate2"
    )
    client.close()


def test_client_requires_token() -> None:
    with pytest.raises(ValueError, match="REPLICON_ACCESS_TOKEN"):
        RepliconClient("https://na5.replicon.com", "")


def test_authorization_error_from_http() -> None:
    client = RepliconClient("https://na5.replicon.com", "token")
    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.content = b'{"message":"forbidden"}'
    mock_response.json.return_value = {"message": "forbidden"}

    with pytest.raises(RepliconAuthError) as exc_info:
        client._handle_response(
            mock_response,
            service="TimesheetService1",
            operation="GetStandardTimesheet2",
        )
    assert exc_info.value.status_code == 403
    client.close()


def test_authorization_error_from_replicon_fault_body() -> None:
    client = RepliconClient("https://na5.replicon.com", "token")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"{}"
    mock_response.json.return_value = {
        "error": {
            "message": (
                "All access checks failed to authorize access in "
                "GetStandardTimesheet2. Required action: "
                "urn:replicon:timesheet-action:view-timesheet"
            ),
            "type": "AuthorizationError1",
        }
    }

    with pytest.raises(RepliconAuthError):
        client._handle_response(
            mock_response,
            service="TimesheetService1",
            operation="GetStandardTimesheet2",
        )
    client.close()


def test_invalid_json_response() -> None:
    client = RepliconClient("https://na5.replicon.com", "token")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"not-json"
    mock_response.text = "not-json"
    mock_response.json.side_effect = ValueError("no json")

    with pytest.raises(RepliconInvalidResponseError):
        client._handle_response(
            mock_response,
            service="TimesheetService1",
            operation="GetTimesheetSummary",
        )
    client.close()


def test_unwrap_d_missing_key() -> None:
    with pytest.raises(RepliconInvalidResponseError):
        RepliconClient.unwrap_d({"x": 1}, operation="GetTimesheetForDate2")


def test_upstream_500_maps_to_api_error() -> None:
    client = RepliconClient("https://na5.replicon.com", "token")
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.content = b'{"error":"boom"}'
    mock_response.json.return_value = {"error": "boom"}

    with pytest.raises(RepliconAPIError) as exc_info:
        client._handle_response(
            mock_response,
            service="TimesheetService1",
            operation="GetTimesheetSummary",
        )
    assert exc_info.value.error_type == "upstream_error"
    # Ensure token never appears in exception detail
    detail = exc_info.value.to_detail()
    assert "token" not in str(detail).lower() or "[REDACTED]" in str(detail)
    client.close()


def test_exception_sanitizes_sensitive_keys() -> None:
    err = RepliconAPIError(
        "fail",
        response_body={"Authorization": "Bearer secret", "ok": True},
    )
    detail = err.to_detail()
    assert detail["upstream_response"]["Authorization"] == "[REDACTED]"
    assert detail["upstream_response"]["ok"] is True


# ---------------------------------------------------------------------------
# FastAPI route tests
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(mock_client: MagicMock) -> TestClient:
    from app.dependencies import get_timesheet_service

    service = TimesheetService(mock_client)

    def _override() -> TimesheetService:
        return service

    app.dependency_overrides[get_timesheet_service] = _override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_health_endpoint(api_client: TestClient) -> None:
    response = api_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_inspect_endpoint(api_client: TestClient, mock_client: MagicMock) -> None:
    mock_client.post.side_effect = [
        _get_timesheet_for_date_response(),
        _summary_response_45h(),
        _details_response(),
        _tasks_response(),
    ]
    response = api_client.post(
        "/timesheets/inspect",
        json={"user_uri": EXAMPLE_USER_URI, "date": "2026-09-15"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["timesheet"]["uri"] == EXAMPLE_TIMESHEET_URI
    assert "summary" in body
    assert "warnings" in body


def test_update_endpoint_returns_501(api_client: TestClient) -> None:
    response = api_client.post(
        "/timesheets/update",
        json={
            "user_uri": EXAMPLE_USER_URI,
            "date": "2026-09-15",
            "allocations": [
                {"task": "Coding", "hours": 3},
                {"task": "Management", "hours": 3},
                {"task": "Meetings", "hours": 3},
            ],
        },
    )
    assert response.status_code == 501
    assert "PutTimeEntryRevisionGroup" in response.json()["detail"]
    # Ensure no Replicon call was attempted via the overridden mock
    # (update route does not use the service for writes)


def test_inspect_propagates_auth_error(
    api_client: TestClient,
    mock_client: MagicMock,
) -> None:
    mock_client.post.side_effect = RepliconAuthError(
        "All access checks failed",
        service="TimesheetService1",
        operation="GetTimesheetSummary",
        status_code=200,
    )
    response = api_client.post(
        "/timesheets/inspect",
        json={"user_uri": EXAMPLE_USER_URI, "date": "2026-09-15"},
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["operation"] == "GetTimesheetSummary"


# ---------------------------------------------------------------------------
# Integration test template (skipped unless explicitly enabled)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.getenv("RUN_REPLICON_INTEGRATION_TESTS", "").lower() != "true",
    reason="Set RUN_REPLICON_INTEGRATION_TESTS=true to call real Replicon API",
)
def test_integration_inspect_live() -> None:
    """Live integration template — requires real token and user URI.

    Environment:
        REPLICON_BASE_URL
        REPLICON_ACCESS_TOKEN
        REPLICON_TEST_USER_URI
        REPLICON_TEST_DATE (optional, default 2026-09-15)
    """
    clear_dependency_caches()
    user_uri = os.environ["REPLICON_TEST_USER_URI"]
    target = date.fromisoformat(os.getenv("REPLICON_TEST_DATE", "2026-09-15"))

    from app.config import get_settings
    from app.clients.replicon_client import RepliconClient as LiveClient

    settings = get_settings()
    client = LiveClient(
        settings.normalized_base_url(),
        settings.replicon_access_token,
        timeout_seconds=settings.replicon_timeout_seconds,
    )
    try:
        svc = TimesheetService(client)
        result = svc.inspect(user_uri, target)
        assert result.timesheet.uri.startswith("urn:replicon")
        assert "raw" in result.summary
    finally:
        client.close()
