import logging
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.certificates import router
from app.core.config import Settings
from app.db.database import Base, create_database_engine, create_session_factory
from app.db import models  # noqa: F401 - register ORM models with Base.metadata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

WEB_DIR = Path(__file__).resolve().parent / "web"


def create_app(settings: Settings | None = None, *, create_tables_on_startup: bool = True) -> FastAPI:
    app_settings = settings or Settings.from_environment()
    engine = create_database_engine(app_settings.database_url)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if create_tables_on_startup:
            Base.metadata.create_all(bind=engine)
            from app.services.job_service import recover_interrupted_jobs
            recover_interrupted_jobs(session_factory)
        app_settings.generated_files_dir.mkdir(parents=True, exist_ok=True)
        yield
        engine.dispose()

    application = FastAPI(
        title="Bulk Certificate Generator",
        description="Validate recipients, track bulk jobs, and generate downloadable PDF certificates.",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.session_factory = session_factory
    application.state.engine = engine
    application.include_router(router, prefix="/api/v1")
    application.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home() -> HTMLResponse:
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(
            html.replace("{{organization_name}}", escape(app_settings.organization_name)),
            headers={"Cache-Control": "no-store"},
        )

    return application


app = create_app()
