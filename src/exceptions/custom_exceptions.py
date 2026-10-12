class AppException(Exception):
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class ValidationError(AppException):
    status_code = 400
    error_code = "VALIDATION_ERROR"


class UnauthorizedError(AppException):
    status_code = 401
    error_code = "UNAUTHORIZED"


class NotFoundError(AppException):
    status_code = 404
    error_code = "NOT_FOUND"


class ConflictError(AppException):
    status_code = 409
    error_code = "CONFLICT"


class RateLimitError(AppException):
    status_code = 429
    error_code = "RATE_LIMITED"
