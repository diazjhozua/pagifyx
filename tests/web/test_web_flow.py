import json
from pathlib import Path
from typing import Any

import pytest
from docx import Document
from fastapi.testclient import TestClient

from pagifyx.core.brand import BrandOverrides
from pagifyx.core.config import Settings
from pagifyx.reading.scraper import PageSnapshot, ScrapeError, SiteSnapshot
from pagifyx.web.app import create_app
from pagifyx.workflow.service import BrochureError, build_theme_overrides, save_logo_upload
from pagifyx.workflow.session import Session

HALF_SECTIONS = ["Call to action", "Cover", "What we offer", "Highlights"]
TRI_SECTIONS = [
    "Call to action",
    "Who we are",
    "Cover",
    "What we offer",
    "Highlights",
    "Who we are",
]


def snapshot() -> SiteSnapshot:
    page = PageSnapshot(
        url="https://acme.test/",
        title="Acme",
        meta_description="Acme builds widgets",
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


def plan_json(
    fold: str = "tri",
    *,
    sections: list[str] | None = None,
    who_headline: str | None = None,
    body: str = "Body text.",
    generated: bool = False,
    primary: str = "#1F4E79",
) -> str:
    """A model reply shaped like a plan: fold, design, and panels in print order."""
    chosen = sections or (HALF_SECTIONS if fold == "half" else TRI_SECTIONS)
    panels: list[dict[str, Any]] = []
    for section in chosen:
        headline = f"Headline {section}"
        if section == "Who we are" and who_headline:
            headline = who_headline
        panels.append(
            {
                "section": section,
                "headline": headline,
                "body": body,
                "image_id": None,
                "generated": generated,
            }
        )
    design = {"preset": "paper", "primary": primary, "accent": ""}
    return json.dumps({"fold": fold, "design": design, "panels": panels})


ANALYSIS_JSON = json.dumps(
    {
        "language": "en",
        "brand": {"name": "Acme", "tagline": "Built well", "tone": "clear"},
        "content": {
            "who_we_are": "We build.",
            "offerings": ["Widgets"],
            "highlights": ["Fast"],
            "contact": {"phone": None, "email": None, "address": None},
        },
    }
)


@pytest.fixture
def stub_scrape(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_scrape(raw_url: str) -> SiteSnapshot:
        return snapshot()

    monkeypatch.setattr("pagifyx.workflow.service.scrape_site", fake_scrape)


def open_site(client: TestClient) -> str:
    response = client.post("/sessions", data={"url": "https://acme.test"})
    return str(response.url).rstrip("/").rsplit("/", 1)[-1]


def fold_form(fold: str = "tri", **extra: str) -> dict[str, str]:
    form = {
        "fold": fold,
        "brand_name": "Acme",
        "tagline": "Built well",
        "primary_color": "",
        "font_family": "",
    }
    form.update(extra)
    return form


def test_index_page_renders(settings: Settings, make_chat: Any) -> None:
    chat, _ = make_chat([])
    client = TestClient(create_app(settings, chat))
    response = client.get("/")
    assert response.status_code == 200
    assert "Read website" in response.text


def test_unknown_session_returns_404(settings: Settings, make_chat: Any) -> None:
    chat, _ = make_chat([])
    client = TestClient(create_app(settings, chat))
    assert client.get("/sessions/does-not-exist").status_code == 404


def test_invalid_url_is_a_user_error_not_a_crash(settings: Settings, make_chat: Any) -> None:
    chat, _ = make_chat([])
    client = TestClient(create_app(settings, chat))
    response = client.post("/sessions", data={"url": "http://["})
    assert response.status_code == 200
    assert "does not look like a valid" in response.text


def test_blocked_site_offers_retry_and_paste(
    settings: Settings, make_chat: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def blocked(raw_url: str) -> SiteSnapshot:
        raise ScrapeError("blocked by site")

    monkeypatch.setattr("pagifyx.workflow.service.scrape_site", blocked)
    chat, _ = make_chat([])
    client = TestClient(create_app(settings, chat))
    response = client.post("/sessions", data={"url": "https://acme.test"})
    assert "blocked by site" in response.text
    assert "Use pasted text" in response.text


def test_full_flow_read_plan_revise_approve_download(
    settings: Settings, make_chat: Any, stub_scrape: None
) -> None:
    chat, completions = make_chat([ANALYSIS_JSON, plan_json(), plan_json(who_headline="Shorter")])
    client = TestClient(create_app(settings, chat))
    session_id = open_site(client)

    response = client.post(f"/sessions/{session_id}/fold", data=fold_form())
    assert "Headline Cover" in response.text

    response = client.post(f"/sessions/{session_id}/revise", data={"message": "Shorter title"})
    assert "Shorter title" in response.text
    assert len(completions.requests) == 3

    response = client.post(f"/sessions/{session_id}/approve")
    assert "Download brochure.docx" in response.text

    download = client.get(f"/sessions/{session_id}/download")
    assert download.status_code == 200
    assert download.content[:2] == b"PK"  # .docx files are zip archives


def test_model_chooses_the_fold_when_the_form_leaves_it_blank(
    settings: Settings, make_chat: Any, stub_scrape: None
) -> None:
    chat, _ = make_chat([ANALYSIS_JSON, plan_json("half")])
    client = TestClient(create_app(settings, chat))
    session_id = open_site(client)

    response = client.post(f"/sessions/{session_id}/fold", data=fold_form(fold=""))
    assert "Half-fold" in response.text


def test_failed_fold_change_keeps_the_previous_plan(
    settings: Settings, make_chat: Any, stub_scrape: None
) -> None:
    chat, _ = make_chat([ANALYSIS_JSON, plan_json("tri"), "bad", "bad"])
    client = TestClient(create_app(settings, chat))
    session_id = open_site(client)
    client.post(f"/sessions/{session_id}/fold", data=fold_form("tri"))

    response = client.post(f"/sessions/{session_id}/fold", data=fold_form("half"))
    assert "did not return valid output" in response.text

    overview = client.get(f"/sessions/{session_id}/overview")
    assert "Tri-fold · Paper style" in overview.text
    client.post(f"/sessions/{session_id}/approve")
    built = Path(settings.output_dir) / session_id / "brochure.docx"
    assert [len(table.columns) for table in Document(built).tables] == [3, 3]


def test_failed_revision_leaves_history_untouched(
    settings: Settings, make_chat: Any, stub_scrape: None
) -> None:
    chat, _ = make_chat([ANALYSIS_JSON, plan_json(), "bad", "bad"])
    client = TestClient(create_app(settings, chat))
    session_id = open_site(client)
    client.post(f"/sessions/{session_id}/fold", data=fold_form())

    response = client.post(f"/sessions/{session_id}/revise", data={"message": "Make it bolder"})
    assert "did not return valid output" in response.text

    overview = client.get(f"/sessions/{session_id}/overview")
    assert "Make it bolder" not in overview.text  # failed revisions never enter the chat log


def test_revision_invalidates_the_previous_download(
    settings: Settings, make_chat: Any, stub_scrape: None
) -> None:
    chat, _ = make_chat([ANALYSIS_JSON, plan_json(), plan_json(who_headline="Shorter")])
    client = TestClient(create_app(settings, chat))
    session_id = open_site(client)
    client.post(f"/sessions/{session_id}/fold", data=fold_form())
    client.post(f"/sessions/{session_id}/approve")
    assert client.get(f"/sessions/{session_id}/download", follow_redirects=False).status_code == 200

    client.post(f"/sessions/{session_id}/revise", data={"message": "Shorter"})
    response = client.get(f"/sessions/{session_id}/download", follow_redirects=False)
    assert response.status_code == 303


def test_contact_panel_is_rejected_without_contact_details(
    settings: Settings, make_chat: Any, stub_scrape: None
) -> None:
    sections = ["Call to action", "Contact", "Cover", "What we offer", "Highlights", "Who we are"]
    chat, _ = make_chat([ANALYSIS_JSON, plan_json(sections=sections), plan_json(sections=sections)])
    client = TestClient(create_app(settings, chat))
    session_id = open_site(client)

    response = client.post(f"/sessions/{session_id}/fold", data=fold_form())
    assert "Use a Contact panel only" in response.text


def test_contact_panel_accepts_details_typed_in_the_form(
    settings: Settings, make_chat: Any, stub_scrape: None
) -> None:
    sections = ["Call to action", "Contact", "Cover", "What we offer", "Highlights", "Who we are"]
    body = "Call +1 555 0100 today."
    chat, _ = make_chat([ANALYSIS_JSON, plan_json(sections=sections, body=body)])
    client = TestClient(create_app(settings, chat))
    session_id = open_site(client)

    response = client.post(f"/sessions/{session_id}/fold", data=fold_form(phone="+1 555 0100"))
    assert "Headline Contact" in response.text
    assert "Call +1 555 0100 today." in response.text


def test_numbers_not_on_the_website_are_rejected(
    settings: Settings, make_chat: Any, stub_scrape: None
) -> None:
    body = "Save £499 today."
    chat, _ = make_chat([ANALYSIS_JSON, plan_json(body=body), plan_json(body=body)])
    client = TestClient(create_app(settings, chat))
    session_id = open_site(client)

    response = client.post(f"/sessions/{session_id}/fold", data=fold_form())
    assert "not on the website or in the form" in response.text
    assert "499" in response.text


def test_a_colour_not_taken_from_the_website_is_rejected(
    settings: Settings, make_chat: Any, stub_scrape: None
) -> None:
    chat, _ = make_chat([ANALYSIS_JSON, plan_json(primary="#00FF00"), plan_json(primary="#00FF00")])
    client = TestClient(create_app(settings, chat))
    session_id = open_site(client)

    response = client.post(f"/sessions/{session_id}/fold", data=fold_form())
    assert "primary colour from the website" in response.text


def test_generated_panels_are_marked_on_the_overview(
    settings: Settings, make_chat: Any, stub_scrape: None
) -> None:
    chat, _ = make_chat([ANALYSIS_JSON, plan_json(generated=True)])
    client = TestClient(create_app(settings, chat))
    session_id = open_site(client)

    response = client.post(f"/sessions/{session_id}/fold", data=fold_form())
    assert "draft-tag" in response.text


def test_build_theme_overrides_validates_color() -> None:
    with pytest.raises(BrochureError):
        build_theme_overrides(primary_color="blue", font_family="")
    overrides = build_theme_overrides(primary_color="#1f4e79", font_family=" Georgia ")
    assert overrides.primary_color == "#1F4E79"
    assert overrides.font_family == "Georgia"


def test_save_logo_upload_rejects_non_image(tmp_path: Path) -> None:
    session = Session(id="s", url="https://acme.test", directory=tmp_path / "s")
    with pytest.raises(BrochureError):
        save_logo_upload(session, b"<svg></svg>")


def test_brand_overrides_default_to_no_changes() -> None:
    overrides = BrandOverrides()
    assert overrides.brand_name == "" and overrides.logo_path is None
