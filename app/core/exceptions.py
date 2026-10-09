"""Domain errors. Each carries an HTTP status and a stable machine-readable code."""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.extra: dict[str, Any] = extra


class UnsupportedFileTypeError(AppError):
    status_code = 415
    code = "unsupported_file_type"


class FileTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"


class InvalidFileError(AppError):
    """The upload is the right type but its content cannot be processed."""

    status_code = 422
    code = "invalid_file"


class RecordNotFoundError(AppError):
    status_code = 404
    code = "file_not_found"


class FileProcessingFailedError(AppError):
    """The requested resource does not exist because processing failed."""

    status_code = 409
    code = "file_processing_failed"
