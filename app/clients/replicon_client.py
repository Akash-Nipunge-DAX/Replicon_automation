"""Reusable HTTP client for Replicon REST/SOAP-style service endpoints."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests import Response
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
)
from requests.exceptions import (
    JSONDecodeError as RequestsJSONDecodeError,
)
from requests.exceptions import (
    Timeout as RequestsTimeout,
)

from app.clients.exceptions import (
    RepliconAPIError,
    RepliconAuthError,
    RepliconConnectionError,
    RepliconInvalidResponseError,
    RepliconNotFoundError,
    RepliconRateLimitError,
    RepliconTimeoutError,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0


class RepliconClient:
    """Thin, reusable client for Replicon service operations.

    Constructs URLs as::

        {base_url}/services/{service}.svc/{operation}

    Never logs the access token or Authorization header.
    """

    def __init__(
        self,
        base_url: str,
        access_token: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        if not access_token:
            raise ValueError(
                "REPLICON_ACCESS_TOKEN is required. "
                "Set it in the environment or .env file."
            )

        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def build_url(self, service: str, operation: str) -> str:
        """Build a Replicon service operation URL."""
        return f"{self.base_url}/services/{service}.svc/{operation}"

    def post(
        self,
        service: str,
        operation: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST JSON to a Replicon service operation and return parsed JSON.

        Raises:
            RepliconAPIError (and subclasses) on failure.
        """
        url = self.build_url(service, operation)
        body = payload if payload is not None else {}
        start = time.perf_counter()

        logger.info(
            "replicon_request",
            extra={
                "service": service,
                "operation": operation,
                "url": url,
            },
        )

        try:
            response = self._session.post(
                url,
                json=body,
                timeout=self.timeout_seconds,
            )
        except RequestsTimeout as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "replicon_timeout",
                extra={
                    "service": service,
                    "operation": operation,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            raise RepliconTimeoutError(
                f"Replicon request timed out after {self.timeout_seconds}s",
                service=service,
                operation=operation,
            ) from exc
        except RequestsConnectionError as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "replicon_connection_error",
                extra={
                    "service": service,
                    "operation": operation,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            raise RepliconConnectionError(
                "Failed to connect to Replicon API",
                service=service,
                operation=operation,
            ) from exc

        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "replicon_response",
            extra={
                "service": service,
                "operation": operation,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )

        return self._handle_response(response, service=service, operation=operation)

    def _handle_response(
        self,
        response: Response,
        *,
        service: str,
        operation: str,
    ) -> dict[str, Any]:
        """Map HTTP and Replicon fault responses to typed exceptions."""
        status = response.status_code
        parsed_body = self._safe_parse_json(response)

        if status == 401 or status == 403:
            raise RepliconAuthError(
                "Replicon authentication or authorization failed",
                status_code=status,
                service=service,
                operation=operation,
                response_body=parsed_body,
            )

        if status == 404:
            raise RepliconNotFoundError(
                "Replicon endpoint or resource was not found",
                status_code=status,
                service=service,
                operation=operation,
                response_body=parsed_body,
            )

        if status == 429:
            raise RepliconRateLimitError(
                "Replicon rate limit exceeded",
                status_code=status,
                service=service,
                operation=operation,
                response_body=parsed_body,
            )

        if 400 <= status < 500:
            raise RepliconAPIError(
                "Replicon API rejected the request",
                status_code=status,
                service=service,
                operation=operation,
                response_body=parsed_body,
                error_type="client_error",
            )

        if status >= 500:
            raise RepliconAPIError(
                "Replicon API request failed",
                status_code=status,
                service=service,
                operation=operation,
                response_body=parsed_body,
                error_type="upstream_error",
            )

        if parsed_body is None:
            raise RepliconInvalidResponseError(
                "Replicon returned a non-JSON or empty response",
                status_code=status,
                service=service,
                operation=operation,
                response_body=response.text[:2000] if response.text else None,
            )

        if not isinstance(parsed_body, dict):
            raise RepliconInvalidResponseError(
                "Replicon returned JSON that is not an object",
                status_code=status,
                service=service,
                operation=operation,
                response_body=parsed_body,
            )

        self._raise_if_replicon_fault(parsed_body, service=service, operation=operation)
        return parsed_body

    @staticmethod
    def _safe_parse_json(response: Response) -> Any:
        if not response.content:
            return None
        try:
            return response.json()
        except (ValueError, RequestsJSONDecodeError):
            return None

    @staticmethod
    def _raise_if_replicon_fault(
        body: dict[str, Any],
        *,
        service: str,
        operation: str,
    ) -> None:
        """Detect Replicon-style fault / AuthorizationError payloads in 200 responses."""
        # Common patterns: {"error": {...}}, nested AuthorizationError1, etc.
        fault_markers = (
            "AuthorizationError1",
            "authorizationerror",
            "access checks failed",
            "unauthorized",
        )

        serialized = str(body).lower()
        for marker in fault_markers:
            if marker.lower() in serialized:
                message = RepliconClient._extract_fault_message(body) or (
                    "Replicon authorization failed for this operation. "
                    "The token is valid but lacks the required permission."
                )
                raise RepliconAuthError(
                    message,
                    status_code=200,
                    service=service,
                    operation=operation,
                    response_body=body,
                )

        if "error" in body and body["error"] is not None:
            error_payload = body["error"]
            message = (
                RepliconClient._extract_fault_message(error_payload)
                or "Replicon returned an error payload"
            )
            raise RepliconAPIError(
                message,
                status_code=200,
                service=service,
                operation=operation,
                response_body=body,
            )

    @staticmethod
    def _extract_fault_message(payload: Any) -> str | None:
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            for key in ("message", "Message", "description", "Description", "reason"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            # Nested fault objects
            for nested_key in ("fault", "Fault", "error", "Error"):
                nested = payload.get(nested_key)
                if nested is not None:
                    found = RepliconClient._extract_fault_message(nested)
                    if found:
                        return found
        if isinstance(payload, list):
            for item in payload:
                found = RepliconClient._extract_fault_message(item)
                if found:
                    return found
        return None

    @staticmethod
    def unwrap_d(response: dict[str, Any], *, operation: str) -> Any:
        """Safely unwrap Replicon's common ``{"d": ...}`` envelope."""
        if "d" not in response:
            raise RepliconInvalidResponseError(
                f"Replicon response for {operation} is missing the expected 'd' key",
                operation=operation,
                response_body=response,
            )
        return response["d"]

    def get_time_entry_revision_groups_for_user_and_date_range(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """POST GetTimeEntryRevisionGroupsForUserAndDateRange (read / duplicate check)."""
        return self.post(
            "TimeEntryRevisionGroupService1",
            "GetTimeEntryRevisionGroupsForUserAndDateRange",
            payload,
        )

    def put_time_entry_revision_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST PutTimeEntryRevisionGroup (create or update a single revision group).

        Official OpenAPI: creates or updates a time entry revision group.
        For *new* entries, ``timeEntryRevisionGroup.target`` must be null.
        ``unitOfWorkId`` is required (client-generated unique idempotency key).
        """
        return self.post(
            "TimeEntryRevisionGroupService1",
            "PutTimeEntryRevisionGroup",
            payload,
        )

    def submit_timesheet(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST TimesheetApprovalService1/Submit2 — submit weekly timesheet for approval.

        na5 OpenAPI required fields: timesheetUri, unitOfWorkId.
        Optional: comments, changeReason.
        Response body is void (``{"d": null}``).
        """
        return self.post(
            "TimesheetApprovalService1",
            "Submit2",
            payload,
        )

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()
