# backend/core/exceptions.py
# ВЛАДЕЛЕЦ: TZ-01. Stub в TZ-00 для единой обработки ошибок.
from fastapi import HTTPException, status


class SphereException(Exception):
    """Базовый класс исключений платформы."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(SphereException):
    def __init__(self, resource: str, resource_id: str = ""):
        msg = f"{resource} not found" + (f": {resource_id}" if resource_id else "")
        super().__init__(msg, status.HTTP_404_NOT_FOUND)


class PermissionDeniedError(SphereException):
    def __init__(self, action: str = ""):
        msg = "Permission denied" + (f": {action}" if action else "")
        super().__init__(msg, status.HTTP_403_FORBIDDEN)


class AuthenticationError(SphereException):
    def __init__(self, detail: str = "Invalid credentials"):
        super().__init__(detail, status.HTTP_401_UNAUTHORIZED)


class ConflictError(SphereException):
    def __init__(self, message: str):
        super().__init__(message, status.HTTP_409_CONFLICT)


class ValidationError(SphereException):
    def __init__(self, message: str):
        super().__init__(message, status.HTTP_422_UNPROCESSABLE_ENTITY)


def sphere_exception_handler(request, exc: SphereException):
    """FastAPI exception handler для SphereException."""
    raise HTTPException(status_code=exc.status_code, detail=exc.message)
