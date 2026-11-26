class AppError(Exception):
    code = "app_error"
    status_code = 400

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404


class ConflictError(AppError):
    code = "conflict"
    status_code = 409


class UnauthorizedError(AppError):
    code = "unauthorized"
    status_code = 401


class CredentialsRejectedError(UnauthorizedError):
    code = "credentials_rejected"


class ForbiddenError(AppError):
    code = "forbidden"
    status_code = 403


class RateLimitError(AppError):
    code = "rate_limited"
    status_code = 429


class UnavailableError(AppError):
    code = "unavailable"
    status_code = 503
