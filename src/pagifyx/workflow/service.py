"""Brochure workflow: read a site, plan the brochure, revise it in chat, then build the .docx.

Each step runs under the session lock and commits its results only after the model call
succeeds. A failed step therefore leaves the previous state intact.
"""

import re
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import httpx
from openai.types.chat import ChatCompletionMessageParam

from pagifyx.core.brand import BrandOverrides
from pagifyx.core.folds import check_plan, get_fold_spec
from pagifyx.core.grounding import check_grounding
from pagifyx.core.models import LOGO_IMAGE_ID, BrandText, Contact, FoldType, Overview, SiteAnalysis
from pagifyx.core.theme import (
    DEFAULT_PRIMARY_COLOR,
    ThemeOverrides,
    candidate_colours,
    detect_font_family,
    resolve_theme,
)
from pagifyx.llm.client import ChatClient
from pagifyx.llm.prompts import (
    analysis_request,
    assistant_turn,
    overview_as_json,
    plan_request,
    revision_request,
    system_message,
    user_turn,
)
from pagifyx.output.docx_builder import BrochureBrand, build_brochure
from pagifyx.reading.assets import ImageAsset, download_images, fetch_bytes, store_logo
from pagifyx.reading.images import select_images
from pagifyx.reading.scraper import USER_AGENT, PageSnapshot, SiteSnapshot, scrape_site
from pagifyx.workflow.session import Session

MAX_LLM_TEXT_CHARS = 12_000
MAX_LOGO_BYTES = 5 * 1024 * 1024
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
_FONT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9 \-]{0,39}")


class BrochureError(Exception):
    """A workflow step cannot proceed. The message is safe to show the user."""


def site_text(pages: list[PageSnapshot]) -> str:
    """Join page text under source headers, capped at MAX_LLM_TEXT_CHARS."""
    sections = []
    for page in pages:
        body = "\n".join(part for part in (page.meta_description, page.text) if part)
        sections.append(f"## {page.title or page.url} ({page.url})\n{body}")
    return "\n\n".join(sections)[:MAX_LLM_TEXT_CHARS]


def build_brand_overrides(
    *,
    brand_name: str,
    tagline: str,
    logo_path: Path | None,
    phone: str,
    email: str,
    address: str,
) -> BrandOverrides:
    return BrandOverrides(
        brand_name=brand_name.strip()[:80],
        tagline=tagline.strip()[:160],
        logo_path=logo_path,
        contact=Contact(
            phone=phone.strip()[:40] or None,
            email=email.strip()[:120] or None,
            address=address.strip()[:200] or None,
        ),
    )


def build_theme_overrides(*, primary_color: str, font_family: str) -> ThemeOverrides:
    color = primary_color.strip()
    if color and not _HEX_COLOR.fullmatch(color):
        raise BrochureError("Primary color must look like #1F4E79.")
    font = font_family.strip()
    if font and not _FONT_NAME.fullmatch(font):
        raise BrochureError("Font names may contain only letters, digits, spaces, and hyphens.")
    return ThemeOverrides(primary_color=color.upper(), font_family=font)


def save_logo_upload(session: Session, data: bytes) -> Path:
    """Store a user-uploaded logo after checking that python-docx can embed it."""
    if len(data) > MAX_LOGO_BYTES:
        raise BrochureError("The logo must be 5 MB or smaller.")
    # A new name per upload: the logo in use by the current plan is never overwritten.
    path = store_logo(session.assets_dir, data, stem=f"logo-upload-{uuid4().hex[:8]}")
    if path is None:
        raise BrochureError("The logo must be a PNG or JPEG image that Word can embed.")
    return path


def brand_text(analysis: SiteAnalysis | None, overrides: BrandOverrides) -> BrandText:
    """Brand wording with user overrides applied over what the model extracted."""
    base = analysis.brand if analysis else BrandText()
    return BrandText(
        name=overrides.brand_name or base.name,
        tagline=overrides.tagline or base.tagline,
        tone=base.tone,
    )


def _with_overrides(analysis: SiteAnalysis, brand: BrandOverrides) -> SiteAnalysis:
    """The analysis the plan is built from: form values win, site values fill the gaps."""
    site = analysis.content.contact
    contact = Contact(
        phone=brand.contact.phone or site.phone,
        email=brand.contact.email or site.email,
        address=brand.contact.address or site.address,
    )
    content = analysis.content.model_copy(update={"contact": contact})
    return analysis.model_copy(update={"brand": brand_text(analysis, brand), "content": content})


def _sources(session: Session, brand: BrandOverrides) -> list[str]:
    """Text a plan may repeat: the website text, and what the user typed in the form."""
    contact = brand.contact
    return [
        session.source_text,
        brand.brand_name,
        brand.tagline,
        contact.phone or "",
        contact.email or "",
        contact.address or "",
    ]


def _plan_check(
    session: Session,
    logo: Path | None,
    brand: BrandOverrides,
    *,
    contact_available: bool,
    fold: FoldType | None,
) -> Callable[[Overview], None]:
    """Build the check every model reply must pass before it becomes the plan."""
    image_ids = {image.image_id for image in session.images}
    if logo is not None:
        image_ids.add(LOGO_IMAGE_ID)
    sources = _sources(session, brand)

    def check(plan: Overview) -> None:
        if fold is not None and plan.fold != fold:
            raise ValueError(f'Use the fold "{fold.value}".')
        check_plan(plan, get_fold_spec(plan.fold), image_ids, contact_available=contact_available)
        allowed = {colour.upper() for colour in session.colour_candidates}
        if plan.design.primary.upper() not in allowed:
            raise ValueError(
                f"Use a primary colour from the website: {', '.join(sorted(allowed))}."
            )
        if plan.design.accent and plan.design.accent.upper() not in allowed:
            raise ValueError("Use an accent colour from the website list, or leave accent empty.")
        check_grounding(plan, sources)

    return check


async def _download_assets(
    session: Session, snapshot: SiteSnapshot
) -> tuple[list[ImageAsset], Path | None]:
    """Download the site's images and logo under a new file prefix, so older files stay intact.

    If the download fails, the files written so far are removed. The caller deletes the files
    from the previous read only when the whole read commits.
    """
    prefix = f"read-{uuid4().hex[:8]}-"
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True
        ) as client:
            images = await download_images(
                client, select_images(snapshot.images), session.assets_dir, prefix=prefix
            )
            logo = None
            if snapshot.logo_png:
                logo = store_logo(session.assets_dir, snapshot.logo_png, stem=f"{prefix}logo")
            if logo is None and snapshot.og_image:
                data = await fetch_bytes(client, snapshot.og_image)
                if data:
                    logo = store_logo(session.assets_dir, data, stem=f"{prefix}logo")
    except BaseException:
        for path in session.assets_dir.glob(f"{prefix}*"):
            path.unlink(missing_ok=True)
        raise
    return images, logo


class BrochureService:
    """Runs each workflow step and records its results on the Session."""

    def __init__(self, chat: ChatClient) -> None:
        self._chat = chat

    async def read_website(self, session: Session) -> None:
        """Read the site. The model is asked first; nothing is saved until it succeeds."""
        async with session.lock:
            snapshot = await scrape_site(session.url)
            text = site_text(snapshot.pages)
            analysis = await self._analyze(text, snapshot.lang)
            images, logo = await _download_assets(session, snapshot)
            session.commit_read(
                analysis,
                images=images,
                logo_path=logo,
                colours=candidate_colours(snapshot.color_counts),
                detected_font=detect_font_family(snapshot.font_counts),
                source_text=text,
            )

    async def read_pasted_text(self, session: Session, text: str) -> None:
        """Fallback for blocked sites: analyze pasted text. No images or detected theme."""
        text = text.strip()
        if not text:
            raise BrochureError("Paste some text from the site first.")
        source = text[:MAX_LLM_TEXT_CHARS]
        async with session.lock:
            analysis = await self._analyze(source, lang="")
            session.commit_read(
                analysis,
                images=[],
                logo_path=None,
                colours=[DEFAULT_PRIMARY_COLOR],
                detected_font=None,
                source_text=source,
            )

    async def choose_fold(
        self,
        session: Session,
        fold: FoldType | None,
        brand: BrandOverrides,
        theme: ThemeOverrides,
    ) -> None:
        """Make the first plan. `fold` None lets the model choose the fold."""
        async with session.lock:
            if session.analysis is None:
                raise BrochureError("Read a website before choosing a fold.")
            analysis = _with_overrides(session.analysis, brand)
            logo = brand.logo_path or session.logo_path
            contact_available = analysis.content.contact.has_details()
            request = user_turn(
                plan_request(
                    analysis,
                    session.images,
                    has_logo=logo is not None,
                    colours=session.colour_candidates,
                    fold=fold,
                    contact_available=contact_available,
                )
            )
            plan = await self._ask(
                [request],
                _plan_check(session, logo, brand, contact_available=contact_available, fold=fold),
            )
            replaced_logo = session.brand_overrides.logo_path
            session.brand_overrides = brand
            session.theme_overrides = theme
            if replaced_logo is not None and replaced_logo != brand.logo_path:
                replaced_logo.unlink(missing_ok=True)
            session.fold = plan.fold
            session.overview = plan
            session.history = [request, assistant_turn(overview_as_json(plan))]
            session.revisions = []
            session.brochure_path = None

    async def revise(self, session: Session, message: str) -> None:
        note = message.strip()
        if not note:
            raise BrochureError("Describe the change you want.")
        async with session.lock:
            if session.overview is None or session.fold is None or session.analysis is None:
                raise BrochureError("Create an overview before requesting changes.")
            fold = session.fold
            brand = session.brand_overrides
            contact_available = _with_overrides(
                session.analysis, brand
            ).content.contact.has_details()
            request = user_turn(revision_request(note, fold, get_fold_spec(fold).panel_count))
            plan = await self._ask(
                [*session.history, request],
                _plan_check(
                    session,
                    session.effective_logo(),
                    brand,
                    contact_available=contact_available,
                    fold=fold,
                ),
            )
            session.overview = plan
            session.revisions.append(note)
            session.history = [
                *session.history,
                request,
                assistant_turn(overview_as_json(plan)),
            ]
            session.brochure_path = None

    async def approve(self, session: Session) -> Path:
        async with session.lock:
            if session.overview is None:
                raise BrochureError("Create an overview before approving.")
            design = session.overview.design
            text = brand_text(session.analysis, session.brand_overrides)
            brand = BrochureBrand(
                name=text.name, tagline=text.tagline, logo_path=session.effective_logo()
            )
            theme = resolve_theme(
                design.primary, design.accent, session.detected_font, session.theme_overrides
            )
            session.brochure_path = build_brochure(
                session.overview,
                get_fold_spec(session.overview.fold),
                brand,
                theme,
                session.image_paths(),
                session.directory / "brochure.docx",
            )
            return session.brochure_path

    async def _analyze(self, text: str, lang: str) -> SiteAnalysis:
        return await self._chat.complete_json(
            [system_message(), user_turn(analysis_request(text, lang))], SiteAnalysis
        )

    async def _ask(
        self,
        history: list[ChatCompletionMessageParam],
        check: Callable[[Overview], None],
    ) -> Overview:
        """Send the conversation and accept only a plan that passes `check`."""
        return await self._chat.complete_json([system_message(), *history], Overview, check=check)
