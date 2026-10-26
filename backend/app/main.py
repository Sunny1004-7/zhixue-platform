from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import Settings
from .database import Database
from .graph_api import router as graph_router
from .material_api import router as material_router
from .model_api import router as model_router
from .practice_api import router as practice_router
from .resource_handlers import build_resource_handlers
from .seed import seed_database
from .teaching_decision_api import router as teaching_decision_router
from .tutoring_api import router as tutoring_router
from .video_api import router as video_router


def create_app(settings: Settings | None = None) -> FastAPI:
    actual_settings = settings or Settings.from_env()
    database = Database(actual_settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.create_schema()
        with database.session_factory() as session:
            seed_database(session, actual_settings.fact_source)
        yield
        database.dispose()

    application = FastAPI(
        title="知学智教 API",
        version="0.1.0",
        description="知学智教个性化教学平台的业务与算法服务接口",
        lifespan=lifespan,
    )
    application.state.settings = actual_settings
    application.state.db = database
    # 测试可显式注入确定性适配器；正式环境默认使用已配置的OpenAI兼容端口。
    application.state.model_adapter_registry = {}
    # Test deployments intentionally omit upstream handlers so unavailability is testable.
    if actual_settings.environment != "test":
        application.state.personalized_resource_handlers = build_resource_handlers(
            settings=actual_settings,
            adapter_registry=application.state.model_adapter_registry,
        )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(actual_settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router)
    application.include_router(graph_router)
    application.include_router(material_router)
    application.include_router(model_router)
    application.include_router(practice_router)
    application.include_router(video_router)
    application.include_router(tutoring_router)
    application.include_router(teaching_decision_router)
    return application


app = create_app()
