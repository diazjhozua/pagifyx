"""Application factory for the local pagifyx web app."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pagifyx.core.config import Settings, get_settings
from pagifyx.llm.client import ChatClient
from pagifyx.web.routes import Deps, router
from pagifyx.workflow.service import BrochureService
from pagifyx.workflow.session import SessionStore

WEB_DIR = Path(__file__).parent


def create_app(settings: Settings | None = None, chat: ChatClient | None = None) -> FastAPI:
    """Build the app. Tests pass `chat` to avoid calling a real model."""
    settings = settings or get_settings()
    app = FastAPI(title="pagifyx")
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.state.deps = Deps(
        store=SessionStore(settings.output_dir),
        service=BrochureService(chat or ChatClient.from_settings(settings)),
        templates=Jinja2Templates(directory=WEB_DIR / "templates"),
    )
    app.include_router(router)
    return app
