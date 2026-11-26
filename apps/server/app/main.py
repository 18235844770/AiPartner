import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.health import HealthResponse, build_health
from app.config.settings import get_settings
from app.shared.cors import DESKTOP_ORIGINS
from app.modules.audio.api.router import router as audio_router
from app.modules.conversation.api.router import router as conversation_router
from app.modules.conversation.api.account_router import router as account_chat_router
from app.modules.dialogue.api.router import router as dialogue_router
from app.modules.dialogue.api.turn_router import router as turn_router
from app.modules.identity.api.router import router as identity_router
from app.modules.identity.api.account_router import router as account_router
from app.modules.infrastructure.api.router import config_router, log_router, scope_router, task_router
from app.modules.memory.api.context_router import router as memory_context_router
from app.modules.memory.api.router import router as memory_router
from app.modules.persona.api.router import router as persona_router
from app.modules.state.api.router import router as state_router
from app.shared.database.session import dispose_engine
from app.shared.exceptions.handlers import register_exception_handlers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    app = FastAPI(title="AI Companion", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(DESKTOP_ORIGINS),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    settings = get_settings()
    if settings.multi_user_enabled:
        app.include_router(account_router, prefix="/api")
        app.include_router(account_chat_router, prefix="/api")
        app.mount("/mobile", StaticFiles(directory=Path(__file__).resolve().parents[2] / "mobile", html=True), name="mobile")
    else:
        for router in (
            identity_router, conversation_router, persona_router, memory_router, memory_context_router, state_router,
            dialogue_router, turn_router, config_router, log_router, task_router, scope_router, audio_router,
        ):
            app.include_router(router, prefix="/api")

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return await build_health()

    return app


app = create_app()
