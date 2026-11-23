"""In-memory state for one brochure being made in the web UI."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from openai.types.chat import ChatCompletionMessageParam

from pagifyx.core.brand import BrandOverrides
from pagifyx.core.folds import FoldType
from pagifyx.core.models import LOGO_IMAGE_ID, Overview, SiteAnalysis
from pagifyx.core.theme import DEFAULT_PRIMARY_COLOR, ThemeOverrides
from pagifyx.reading.assets import ImageAsset


@dataclass
class Session:
    """One brochure in progress. Workflow steps run under `lock` and commit atomically."""

    id: str
    url: str
    directory: Path
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    analysis: SiteAnalysis | None = None
    images: list[ImageAsset] = field(default_factory=list)
    logo_path: Path | None = None
    colour_candidates: list[str] = field(default_factory=lambda: [DEFAULT_PRIMARY_COLOR])
    detected_font: str | None = None
    source_text: str = ""
    brand_overrides: BrandOverrides = field(default_factory=BrandOverrides)
    theme_overrides: ThemeOverrides = field(default_factory=ThemeOverrides)
    settings_form: dict[str, str] = field(default_factory=dict)
    fold: FoldType | None = None
    overview: Overview | None = None
    history: list[ChatCompletionMessageParam] = field(default_factory=list)
    revisions: list[str] = field(default_factory=list)
    brochure_path: Path | None = None
    error: str | None = None

    @property
    def assets_dir(self) -> Path:
        return self.directory / "assets"

    def effective_logo(self) -> Path | None:
        return self.brand_overrides.logo_path or self.logo_path

    def image_paths(self) -> dict[str, Path]:
        """Map every image id the Overview may use to its file on disk."""
        paths = {image.image_id: image.path for image in self.images}
        logo = self.effective_logo()
        if logo is not None:
            paths[LOGO_IMAGE_ID] = logo
        return paths

    def clear_plan(self) -> None:
        """Drop the fold, Overview, chat, built file, and the last submitted settings."""
        self.settings_form = {}
        self.fold = None
        self.overview = None
        self.history = []
        self.revisions = []
        self.brochure_path = None

    def commit_read(
        self,
        analysis: SiteAnalysis,
        *,
        images: list[ImageAsset],
        logo_path: Path | None,
        colours: list[str],
        detected_font: str | None,
        source_text: str,
    ) -> None:
        """Replace everything read from the site in one step. Call only after the model succeeded.

        Files from the previous read are deleted here, unless the new read uses them too.
        A logo the user uploaded is not part of a read, so it is never deleted.
        """
        kept = {image.path for image in images}
        if logo_path is not None:
            kept.add(logo_path)
        previous = [image.path for image in self.images]
        if self.logo_path is not None:
            previous.append(self.logo_path)
        self.clear_plan()
        self.analysis = analysis
        self.images = images
        self.logo_path = logo_path
        self.colour_candidates = colours
        self.detected_font = detected_font
        self.source_text = source_text
        for path in previous:
            if path not in kept:
                path.unlink(missing_ok=True)

    def take_error(self) -> str | None:
        """Return the pending error message once, then clear it."""
        message, self.error = self.error, None
        return message


class SessionNotFound(Exception):
    """No session exists for the requested id."""


class SessionStore:
    """Holds sessions in memory for the lifetime of the local process."""

    def __init__(self, output_root: Path) -> None:
        self._root = output_root
        self._sessions: dict[str, Session] = {}

    def create(self, url: str) -> Session:
        session_id = uuid4().hex
        session = Session(id=session_id, url=url, directory=self._root / session_id)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise SessionNotFound(session_id) from exc
