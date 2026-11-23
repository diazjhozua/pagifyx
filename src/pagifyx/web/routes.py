"""HTTP routes for the brochure workflow. Routes validate input, then call BrochureService."""

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Annotated, NamedTuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from pagifyx.core.folds import face_panels, get_fold_spec
from pagifyx.core.models import LOGO_IMAGE_ID, FoldType, Panel, Preset
from pagifyx.llm.client import LLMError
from pagifyx.reading.scraper import ScrapeError
from pagifyx.workflow.service import (
    BrochureError,
    BrochureService,
    build_brand_overrides,
    build_theme_overrides,
    save_logo_upload,
)
from pagifyx.workflow.session import Session, SessionNotFound, SessionStore

router = APIRouter()
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_WORKFLOW_ERRORS = (ScrapeError, LLMError, BrochureError)
_PRESET_LABELS = {
    Preset.FULL_COLOUR: "Full colour",
    Preset.NIGHT: "Night",
    Preset.PAPER: "Paper",
}


@dataclass(frozen=True)
class Deps:
    store: SessionStore
    service: BrochureService
    templates: Jinja2Templates


def get_deps(request: Request) -> Deps:
    deps: Deps = request.app.state.deps
    return deps


def get_session(session_id: str, deps: Annotated[Deps, Depends(get_deps)]) -> Session:
    try:
        return deps.store.get(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="No such brochure session.") from exc


DepsDep = Annotated[Deps, Depends(get_deps)]
SessionDep = Annotated[Session, Depends(get_session)]


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


async def _attempt(session: Session, action: Awaitable[object]) -> bool:
    """Run one workflow step. A user-facing error is stored on the session and returns False."""
    try:
        await action
    except _WORKFLOW_ERRORS as exc:
        session.error = str(exc)
        return False
    return True


def _parse_fold(value: str) -> FoldType | None:
    """A blank value means the model chooses the fold."""
    if not value:
        return None
    try:
        return FoldType(value)
    except ValueError as exc:
        raise BrochureError("Choose half, tri, or z, or let pagifyx choose.") from exc


def _image_url(session: Session, image_id: str | None) -> str | None:
    if image_id is None:
        return None
    path = session.image_paths().get(image_id)
    return f"/sessions/{session.id}/files/{path.name}" if path is not None else None


class _Card(NamedTuple):
    """One panel as the overview shows it."""

    number: int
    panel: Panel
    image_url: str | None
    alt: str


def _alt_text(session: Session, image_id: str | None) -> str:
    if image_id is None:
        return ""
    if image_id == LOGO_IMAGE_ID:
        return "Logo"
    return next((image.alt for image in session.images if image.image_id == image_id), "")


def _cards(session: Session, panels: list[Panel], first_number: int) -> list[_Card]:
    """Panels with their print numbers, counted across both faces."""
    return [
        _Card(
            number=number,
            panel=panel,
            image_url=_image_url(session, panel.image_id),
            alt=_alt_text(session, panel.image_id),
        )
        for number, panel in enumerate(panels, start=first_number)
    ]


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, deps: DepsDep) -> HTMLResponse:
    return deps.templates.TemplateResponse(request, "index.html", {})


@router.post("/sessions")
async def create_session(deps: DepsDep, url: Annotated[str, Form()] = "") -> RedirectResponse:
    session = deps.store.create(url)
    await _attempt(session, deps.service.read_website(session))
    return _redirect(f"/sessions/{session.id}")


@router.get("/sessions/{session_id}", response_class=HTMLResponse)
async def session_page(request: Request, deps: DepsDep, session: SessionDep) -> HTMLResponse:
    context = {
        "session": session,
        "error": session.take_error(),
        "folds": [(fold, get_fold_spec(fold)) for fold in FoldType],
    }
    return deps.templates.TemplateResponse(request, "session.html", context)


@router.post("/sessions/{session_id}/retry")
async def retry_read(deps: DepsDep, session: SessionDep) -> RedirectResponse:
    await _attempt(session, deps.service.read_website(session))
    return _redirect(f"/sessions/{session.id}")


@router.post("/sessions/{session_id}/paste")
async def paste_text(
    deps: DepsDep, session: SessionDep, text: Annotated[str, Form()] = ""
) -> RedirectResponse:
    await _attempt(session, deps.service.read_pasted_text(session, text))
    return _redirect(f"/sessions/{session.id}")


@router.post("/sessions/{session_id}/fold")
async def choose_fold(
    deps: DepsDep,
    session: SessionDep,
    fold: Annotated[str, Form()] = "",
    brand_name: Annotated[str, Form()] = "",
    tagline: Annotated[str, Form()] = "",
    phone: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    address: Annotated[str, Form()] = "",
    primary_color: Annotated[str, Form()] = "",
    font_family: Annotated[str, Form()] = "",
    logo: Annotated[UploadFile | None, File()] = None,
) -> RedirectResponse:
    # Keep what the user typed, so the settings page shows it again after a failed step.
    session.settings_form = {
        "fold": fold,
        "brand_name": brand_name,
        "tagline": tagline,
        "phone": phone,
        "email": email,
        "address": address,
        "primary_color": primary_color,
        "font_family": font_family,
    }

    async def apply() -> None:
        chosen = _parse_fold(fold)
        theme = build_theme_overrides(primary_color=primary_color, font_family=font_family)
        logo_path = session.brand_overrides.logo_path
        if logo is not None and logo.filename:
            logo_path = save_logo_upload(session, await logo.read())
        brand = build_brand_overrides(
            brand_name=brand_name,
            tagline=tagline,
            logo_path=logo_path,
            phone=phone,
            email=email,
            address=address,
        )
        await deps.service.choose_fold(session, chosen, brand, theme)

    if not await _attempt(session, apply()):
        return _redirect(f"/sessions/{session.id}")
    return _redirect(f"/sessions/{session.id}/overview")


@router.get("/sessions/{session_id}/overview", response_model=None)
async def overview_page(request: Request, deps: DepsDep, session: SessionDep) -> Response:
    plan = session.overview
    if plan is None:
        return _redirect(f"/sessions/{session.id}")
    spec = get_fold_spec(plan.fold)
    outside, inside = face_panels(plan, spec)
    context = {
        "session": session,
        "spec": spec,
        "preset": _PRESET_LABELS[plan.design.preset],
        "primary": session.theme_overrides.primary_color or plan.design.primary,
        "outside": _cards(session, outside, 1),
        "inside": _cards(session, inside, len(outside) + 1),
        "has_generated": any(panel.generated for panel in plan.panels),
        "error": session.take_error(),
    }
    return deps.templates.TemplateResponse(request, "overview.html", context)


@router.post("/sessions/{session_id}/revise")
async def revise(
    deps: DepsDep, session: SessionDep, message: Annotated[str, Form()] = ""
) -> RedirectResponse:
    await _attempt(session, deps.service.revise(session, message))
    return _redirect(f"/sessions/{session.id}/overview")


@router.post("/sessions/{session_id}/approve")
async def approve(deps: DepsDep, session: SessionDep) -> RedirectResponse:
    await _attempt(session, deps.service.approve(session))
    return _redirect(f"/sessions/{session.id}/overview")


@router.get("/sessions/{session_id}/download", response_model=None)
async def download(session: SessionDep) -> Response:
    if session.brochure_path is None or not session.brochure_path.is_file():
        return _redirect(f"/sessions/{session.id}/overview")
    return FileResponse(session.brochure_path, media_type=DOCX_MEDIA_TYPE, filename="brochure.docx")


@router.get("/sessions/{session_id}/files/{filename}")
async def session_file(session: SessionDep, filename: str) -> FileResponse:
    """Serve an image or logo from this session's assets folder only."""
    assets = session.assets_dir.resolve()
    path = (assets / filename).resolve()
    if path.parent != assets or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path)
