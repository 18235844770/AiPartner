"""List model tasks or initialize the defaults for a beta installation."""

import argparse
import asyncio
import os
import sys
from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from app.modules.infrastructure.domain.enums import CONFIG_TASK_TYPES, ModelConfigKey
from app.config.settings import get_settings
from app.modules.infrastructure.api.schemas import AddModelConfigVersionRequest, CreateModelConfigRequest
from app.modules.infrastructure.services.model_config_service import ModelConfigService
from app.modules.model_adapter.domain.embedding import LOCAL_EMBEDDING_MODEL
from app.shared.database.session import dispose_engine, get_session_factory
from app.shared.exceptions.errors import ConflictError


async def init_beta() -> None:
    settings = get_settings()
    if not settings.deepseek_api_key.strip():
        raise SystemExit("DEEPSEEK_API_KEY is required for beta deployment")
    models = {
        ModelConfigKey.DECISION: os.getenv("DEEPSEEK_DECISION_MODEL", "deepseek-v4-pro"),
        ModelConfigKey.CONVERSATION: os.getenv("DEEPSEEK_CONVERSATION_MODEL", "deepseek-flash"),
        ModelConfigKey.MEMORY: os.getenv("DEEPSEEK_MEMORY_MODEL", "deepseek-flash"),
    }
    service = ModelConfigService()
    try:
        async with get_session_factory()() as session:
            for key, name in models.items():
                try:
                    await service.create(session, CreateModelConfigRequest(
                        config_key=key, model_name=name, parameters={"thinking": "disabled"},
                    ))
                    print(f"Initialized {key.value}: {name}")
                except ConflictError:
                    configs = await service.list_configs(session)
                    config = next((item for item in configs if item.config_key == key.value and item.is_enabled and item.is_default), None)
                    if config is None:
                        raise SystemExit(f"Enable a default configuration for {key.value} before starting beta")
                    print(f"Preserved {key.value}: {config.model_name}")
            embedding = await service.ensure_local_embedding(settings.embedding_model_name)
            if embedding.model_name == "BAAI/bge-m3" and settings.embedding_model_name == LOCAL_EMBEDDING_MODEL:
                await service.add_version(session, ModelConfigKey.EMBEDDING, AddModelConfigVersionRequest(
                    model_name=LOCAL_EMBEDDING_MODEL,
                ))
                print(f"Upgraded beta embedding default to {LOCAL_EMBEDDING_MODEL}")
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--beta", action="store_true")
    if parser.parse_args().beta:
        asyncio.run(init_beta())
        return
    pairs = ", ".join(f"{key.value}->{task.value}" for key, task in CONFIG_TASK_TYPES.items())
    print(f"model config keys ok: {len(ModelConfigKey)} ({pairs})")
    print("no model name inserted")


if __name__ == "__main__":
    main()
