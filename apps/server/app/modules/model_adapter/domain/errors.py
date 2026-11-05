from app.shared.exceptions.errors import AppError


class ModelAdapterError(AppError):
    code = "model_unavailable"
    status_code = 503


class ModelTimeoutError(ModelAdapterError):
    code = "model_timeout"


class ModelHttpError(ModelAdapterError):
    def __init__(self, http_status: int) -> None:
        self.http_status = http_status
        super().__init__("模型服务不可用")


class ModelOutputError(ModelAdapterError):
    code = "model_output"


class ModelCapabilityError(ModelAdapterError):
    code = "model_capability"
