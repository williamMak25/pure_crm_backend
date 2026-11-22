"""Application exception types and the JSON error format.

Every error response has the shape the frontend's `ApiError` reads:
``{"message": str, "statusCode": int, "errors": [...]?}``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from advanced_alchemy.exceptions import (
    DuplicateKeyError,
    IntegrityError,
    NotFoundError,
    RepositoryError,
)
from litestar import MediaType, Response
from litestar.exceptions import HTTPException, ValidationException
from litestar.status_codes import (
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

if TYPE_CHECKING:
    from litestar import Request

logger = logging.getLogger(__name__)


class ApplicationError(Exception):
    """Base exception type for the app's custom exception types."""

    status_code: int = HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = "Internal server error"

    def __init__(self, detail: str | None = None) -> None:
        if detail:
            self.detail = detail
        super().__init__(self.detail)


class ApplicationClientError(ApplicationError):
    """A request the client can fix."""

    status_code = HTTP_400_BAD_REQUEST
    detail = "Bad request"


class AuthorizationError(ApplicationClientError):
    """A user tried to do something they shouldn't have."""

    status_code = HTTP_403_FORBIDDEN
    detail = "You do not have permission to do this"


def _error_response(status_code: int, message: str, errors: Any = None) -> Response[dict[str, Any]]:
    body: dict[str, Any] = {"message": message, "statusCode": status_code}
    if errors:
        body["errors"] = errors
    return Response(content=body, status_code=status_code, media_type=MediaType.JSON)


def http_exception_handler(_: Request[Any, Any, Any], exc: HTTPException) -> Response[dict[str, Any]]:
    errors = exc.extra if isinstance(exc, ValidationException) else None
    if exc.status_code >= HTTP_500_INTERNAL_SERVER_ERROR:
        logger.exception("Unhandled HTTP error", exc_info=exc)
        return _error_response(exc.status_code, "Internal server error")
    return _error_response(exc.status_code, exc.detail, errors)


def application_exception_handler(_: Request[Any, Any, Any], exc: ApplicationError) -> Response[dict[str, Any]]:
    return _error_response(exc.status_code, exc.detail)


def repository_exception_handler(_: Request[Any, Any, Any], exc: RepositoryError) -> Response[dict[str, Any]]:
    if isinstance(exc, NotFoundError):
        return _error_response(HTTP_404_NOT_FOUND, "Record not found")
    if isinstance(exc, DuplicateKeyError | IntegrityError):
        return _error_response(HTTP_409_CONFLICT, exc.detail or "This record conflicts with an existing one")
    logger.exception("Repository error", exc_info=exc)
    return _error_response(HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error")


def internal_exception_handler(_: Request[Any, Any, Any], exc: Exception) -> Response[dict[str, Any]]:
    logger.exception("Unhandled error", exc_info=exc)
    return _error_response(HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error")


exception_handlers = {
    HTTPException: http_exception_handler,
    ApplicationError: application_exception_handler,
    RepositoryError: repository_exception_handler,
    Exception: internal_exception_handler,
}
