import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import HealthResponse, build_health
from app.shared.cors import DESKTOP_ORIGINS
from app.modules.conversation.api.router import router as conversation_router
from app.modules.dialogue.api.router import router as dialogue_router
from app.modules.dialogue.api.turn_router import router as turn_router
from app.modules.identity.api.router import router as identity_router
from app.modules.infrastructure.api.router import config_router, log_router, task_router
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
    app.include_router(identity_router, prefix="/api")
    app.include_router(conversation_router, prefix="/api")
    app.include_router(persona_router, prefix="/api")
    app.include_router(memory_router, prefix="/api")
    app.include_router(state_router, prefix="/api")
    app.include_router(dialogue_router, prefix="/api")
    app.include_router(turn_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(log_router, prefix="/api")
    app.include_router(task_router, prefix="/api")

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return await build_health()

    return app


app = create_app()
