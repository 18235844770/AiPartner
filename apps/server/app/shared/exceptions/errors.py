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
