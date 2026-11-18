"""Custom exceptions for Replicon API interactions."""

from __future__ import annotations

from typing import Any


class RepliconAPIError(Exception):
    """Raised when a Replicon API call fails or returns an unexpected payload."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        service: str | None = None,
        operation: str | None = None,
        response_body: Any = None,
        error_type: str = "api_error",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.service = service
        self.operation = operation
        self.response_body = response_body
        self.error_type = error_type

    def to_detail(self) -> dict[str, Any]:
        """Build a safe, token-free detail payload for HTTP responses."""
        detail: dict[str, Any] = {
            "message": self.message,
            "error_type": self.error_type,
        }
        if self.service:
            detail["service"] = self.service
        if self.operation:
            detail["operation"] = self.operation
        if self.status_code is not None:
            detail["upstream_status"] = self.status_code
        if self.response_body is not None:
            detail["upstream_response"] = self._sanitize_body(self.response_body)
        return detail

    @staticmethod
    def _sanitize_body(body: Any) -> Any:
        """Strip sensitive keys from nested response bodies before returning them."""
        sensitive = {"authorization", "access_token", "token", "password", "secret"}

        if isinstance(body, dict):
            cleaned: dict[str, Any] = {}
            for key, value in body.items():
                if key.lower() in sensitive:
                    cleaned[key] = "[REDACTED]"
                else:
                    cleaned[key] = RepliconAPIError._sanitize_body(value)
            return cleaned
        if isinstance(body, list):
            return [RepliconAPIError._sanitize_body(item) for item in body]
        return body


class RepliconAuthError(RepliconAPIError):
    """Authentication or authorization failure (HTTP 401/403 or Replicon auth fault)."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("error_type", "authorization_error")
        super().__init__(message, **kwargs)


class RepliconNotFoundError(RepliconAPIError):
    """Resource or endpoint not found (HTTP 404)."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("error_type", "not_found")
        super().__init__(message, **kwargs)


class RepliconRateLimitError(RepliconAPIError):
    """Upstream rate limiting (HTTP 429)."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("error_type", "rate_limit")
        super().__init__(message, **kwargs)


class RepliconTimeoutError(RepliconAPIError):
    """Request timed out talking to Replicon."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("error_type", "timeout")
        kwargs.setdefault("status_code", None)
        super().__init__(message, **kwargs)


class RepliconConnectionError(RepliconAPIError):
    """Network/connection failure talking to Replicon."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("error_type", "connection_error")
        super().__init__(message, **kwargs)


class RepliconInvalidResponseError(RepliconAPIError):
    """Response was not valid JSON or missing expected structure."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("error_type", "invalid_response")
        super().__init__(message, **kwargs)


class TimeEntryValidationError(Exception):
    """Raised when a time-entry write request fails local business validation."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
