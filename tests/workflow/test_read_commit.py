"""A site read commits only after the model answers. A failed read keeps the previous plan."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pagifyx.core.brand import BrandOverrides
from pagifyx.core.folds import FoldType
from pagifyx.core.models import Design, Overview, Preset, SiteAnalysis
from pagifyx.core.theme import DEFAULT_PRIMARY_COLOR
from pagifyx.llm.client import ChatClient, LLMError
from pagifyx.reading.assets import ImageAsset
from pagifyx.reading.scraper import PageSnapshot, SiteSnapshot
from pagifyx.workflow.service import BrochureService
from pagifyx.workflow.session import Session


def analysis_json(brand_name: str) -> str:
    return json.dumps(
        {
            "language": "en",
            "brand": {"name": brand_name, "tagline": "Built well", "tone": "clear"},
            "content": {
                "who_we_are": "We build.",
                "offerings": ["Widgets"],
                "highlights": ["Fast"],
                "contact": {"phone": None, "email": None, "address": None},
            },
        }
    )


def snapshot() -> SiteSnapshot:
    page = PageSnapshot(
        url="https://acme.test/",
        title="Acme",
        meta_description="",
        text="Acme builds widgets for busy teams. " * 10,
        links=(),
        images=(),
    )
    return SiteSnapshot(
        lang="en",
        pages=[page],
        color_counts={"rgb(31, 78, 121)": 10},
        font_counts={'"Inter", sans-serif': 3},
        og_image=None,
        logo_png=None,
    )


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_scrape(raw_url: str) -> SiteSnapshot:
        return snapshot()

    monkeypatch.setattr("pagifyx.workflow.service.scrape_site", fake_scrape)


def new_session(tmp_path: Path) -> Session:
    return Session(id="s1", url="https://acme.test", directory=tmp_path / "s1")


def give_a_plan(session: Session) -> None:
    design = Design(preset=Preset.PAPER, primary="#1F4E79")
    session.fold = FoldType.TRI
    session.overview = Overview(fold=FoldType.TRI, design=design, panels=[])


def test_failed_reread_keeps_the_previous_plan(
    tmp_path: Path, make_chat: Callable[[list[str]], tuple[ChatClient, Any]], site: None
) -> None:
    chat, _ = make_chat([analysis_json("Acme"), "bad", "bad"])
    service = BrochureService(chat)
    session = new_session(tmp_path)
    asyncio.run(service.read_website(session))
    give_a_plan(session)

    with pytest.raises(LLMError):
        asyncio.run(service.read_website(session))

    assert session.analysis is not None
    assert session.analysis.brand.name == "Acme"
    assert session.fold is FoldType.TRI
    assert session.overview is not None


def test_successful_reread_replaces_the_plan(
    tmp_path: Path, make_chat: Callable[[list[str]], tuple[ChatClient, Any]], site: None
) -> None:
    chat, _ = make_chat([analysis_json("Acme"), analysis_json("Beta")])
    service = BrochureService(chat)
    session = new_session(tmp_path)
    asyncio.run(service.read_website(session))
    give_a_plan(session)

    asyncio.run(service.read_website(session))

    assert session.analysis is not None
    assert session.analysis.brand.name == "Beta"
    assert session.fold is None
    assert session.overview is None
    assert session.colour_candidates == ["#1F4E79"]


def test_failed_paste_keeps_the_previous_plan(
    tmp_path: Path, make_chat: Callable[[list[str]], tuple[ChatClient, Any]]
) -> None:
    chat, _ = make_chat([analysis_json("Acme"), "bad", "bad"])
    service = BrochureService(chat)
    session = new_session(tmp_path)
    asyncio.run(service.read_pasted_text(session, "Acme builds widgets."))
    give_a_plan(session)

    with pytest.raises(LLMError):
        asyncio.run(service.read_pasted_text(session, "Something else."))

    assert session.analysis is not None
    assert session.analysis.brand.name == "Acme"
    assert session.overview is not None


def test_commit_deletes_the_previous_read_files_but_not_an_uploaded_logo(
    tmp_path: Path,
) -> None:
    session = new_session(tmp_path)
    session.assets_dir.mkdir(parents=True)
    old_image = session.assets_dir / "read-old-img-1.jpg"
    old_logo = session.assets_dir / "read-old-logo.png"
    upload = session.assets_dir / "logo-upload.png"
    for path in (old_image, old_logo, upload):
        path.write_bytes(b"x")
    session.images = [ImageAsset(image_id="img-1", path=old_image, alt="", width=1, height=1)]
    session.logo_path = old_logo
    session.brand_overrides = BrandOverrides(logo_path=upload)
    analysis = SiteAnalysis.model_validate_json(analysis_json("Beta"))

    session.commit_read(
        analysis,
        images=[],
        logo_path=None,
        colours=[DEFAULT_PRIMARY_COLOR],
        detected_font=None,
        source_text="",
    )

    assert not old_image.exists()
    assert not old_logo.exists()
    assert upload.exists()
    assert session.analysis is not None
    assert session.analysis.brand.name == "Beta"
