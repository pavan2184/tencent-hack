"""Error envelope: every non-2xx response is {"error": {code, message, details, request_id}}.

Routers raise `AppError` subclasses; `install_error_handlers` turns them (and FastAPI's own
validation/HTTP errors) into the envelope. A denied document must produce a response
byte-identical to a missing one: always raise `NotFound()` with the default message.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse

from app.core.context import get_request_id


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"
    message: str = "Internal error."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or {}
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        super().__init__(self.message)

    def to_envelope(self) -> dict[str, Any]:
        return envelope(self.code, self.message, self.details)


class Unauthenticated(AppError):
    status_code = 401
    code = "unauthenticated"
    message = "Missing actor. Send the X-Actor-Id header."


class UnknownActor(AppError):
    status_code = 401
    code = "unknown_actor"
    message = "Unknown or inactive actor."


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have the role required for this action."


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    message = "Not found."


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_error"
    message = "Request validation failed."


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"
    message = "Upload exceeds the maximum file size."


class CapExceeded(AppError):
    status_code = 429
    code = "cap_exceeded"
    message = "Upload or budget cap exceeded."


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    message = "Conflict."


class ProviderUnavailable(AppError):
    status_code = 503
    code = "provider_unavailable"
    message = "Upstream provider unavailable."


class NotImplementedFeature(AppError):
    status_code = 501
    code = "not_implemented"
    message = "Not implemented."


def envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": get_request_id(),
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_envelope())

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = {"errors": exc.errors()}
        return JSONResponse(
            status_code=422,
            content=envelope("validation_error", "Request validation failed.", details),
        )

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        code = {401: "unauthenticated", 403: "forbidden", 404: "not_found"}.get(
            exc.status_code, "http_error"
        )
        message = exc.detail if isinstance(exc.detail, str) else "HTTP error."
        return JSONResponse(status_code=exc.status_code, content=envelope(code, message))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(status_code=500, content=envelope("internal_error", "Internal error."))
