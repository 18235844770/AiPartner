import json
from typing import Any

from sqlalchemy import text

from app.shared.database.session import get_engine

_CONFIG_COLUMNS = (
    "id",
    "config_key",
    "provider",
    "model_name",
    "task_type",
    "parameters",
    "is_enabled",
    "is_default",
    "version",
    "created_at",
    "updated_at",
)
_LOG_COLUMNS = (
    "id",
    "companion_id",
    "conversation_id",
    "dialogue_decision_id",
    "background_task_id",
    "config_id",
    "trace_id",
    "task_type",
    "provider",
    "model_name",
    "status",
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "error_code",
    "error_message",
    "created_at",
    "completed_at",
)


async def park_model_config(config_key: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """集成测试会临时占用全局配置键。先取走已有行，结束后原样放回。"""
    async with get_engine().connect() as connection:
        configs = (
            await connection.execute(
                text(f"SELECT {', '.join(_CONFIG_COLUMNS)} FROM model_configs WHERE config_key = :config_key"),
                {"config_key": config_key},
            )
        ).mappings().all()
        logs = (
            await connection.execute(
                text(
                    f"""
                    SELECT {', '.join(f'l.{column}' for column in _LOG_COLUMNS)}
                    FROM model_call_logs AS l
                    JOIN model_configs AS c ON c.id = l.config_id
                    WHERE c.config_key = :config_key
                    """
                ),
                {"config_key": config_key},
            )
        ).mappings().all()
    return [dict(row) for row in configs], [dict(row) for row in logs]


async def restore_model_config(configs: list[dict[str, Any]], logs: list[dict[str, Any]]) -> None:
    if not configs:
        return
    async with get_engine().begin() as connection:
        for row in configs:
            payload = dict(row)
            payload["parameters"] = json.dumps(payload["parameters"])
            await connection.execute(
                text(
                    f"""
                    INSERT INTO model_configs ({", ".join(_CONFIG_COLUMNS)})
                    VALUES (
                        :id, :config_key, :provider, :model_name, :task_type, CAST(:parameters AS jsonb),
                        :is_enabled, :is_default, :version, :created_at, :updated_at
                    )
                    """
                ),
                payload,
            )
        for row in logs:
            await connection.execute(
                text(
                    f"""
                    INSERT INTO model_call_logs ({", ".join(_LOG_COLUMNS)})
                    VALUES (
                        :id, :companion_id, :conversation_id, :dialogue_decision_id, :background_task_id,
                        :config_id, :trace_id, :task_type, :provider, :model_name, :status, :latency_ms,
                        :input_tokens, :output_tokens, :error_code, :error_message, :created_at, :completed_at
                    )
                    """
                ),
                row,
            )
