import struct
import zlib
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn
from docx.table import _Cell

from pagifyx.core.folds import get_fold_spec
from pagifyx.core.models import Design, FoldType, Overview, Panel, PanelSection, Preset
from pagifyx.core.theme import Theme, build_palette
from pagifyx.output.docx_builder import BrochureBrand, build_brochure

CTA, CONTACT, COVER = PanelSection.CALL_TO_ACTION, PanelSection.CONTACT, PanelSection.COVER
WHO, OFFER, HIGHLIGHTS = (
    PanelSection.WHO_WE_ARE,
    PanelSection.WHAT_WE_OFFER,
    PanelSection.HIGHLIGHTS,
)
FACE_SECTIONS = {
    FoldType.HALF: [CTA, COVER, WHO, OFFER],
    FoldType.TRI: [CTA, CONTACT, COVER, WHO, OFFER, HIGHLIGHTS],
    FoldType.Z: [CTA, CONTACT, COVER, WHO, OFFER, HIGHLIGHTS],
}

BRAND = BrochureBrand(name="Acme", tagline="Built well", logo_path=None)
PALETTE = build_palette("#1F4E79")
THEME = Theme(font_family="Calibri", palette=PALETTE)


def overview_for(fold: FoldType, preset: Preset = Preset.PAPER) -> Overview:
    return Overview(
        fold=fold,
        design=Design(preset=preset, primary="#1F4E79"),
        panels=[
            Panel(section=section, headline=f"Headline {section.value}", body="First.\nSecond.")
            for section in FACE_SECTIONS[fold]
        ],
    )


def build(fold: FoldType, tmp_path: Path, preset: Preset = Preset.PAPER) -> Document:
    path = build_brochure(
        overview_for(fold, preset),
        get_fold_spec(fold),
        BRAND,
        THEME,
        {},
        tmp_path / "brochure.docx",
    )
    return Document(path)


def cell_texts(document: Document, side: int) -> list[str]:
    return [cell.text for cell in document.tables[side].rows[0].cells]


def fill_of(cell: _Cell) -> str | None:
    shading = cell._tc.tcPr.find(qn("w:shd"))
    return None if shading is None else shading.get(qn("w:fill"))


def make_png(width: int = 4, height: int = 4) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    raw = b"".join(b"\x00" + b"\x10\x20\x30" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_tri_fold_has_two_landscape_sections_with_three_panels_each(tmp_path: Path) -> None:
    document = build(FoldType.TRI, tmp_path)
    assert len(document.sections) == 2
    for section in document.sections:
        assert section.orientation == WD_ORIENT.LANDSCAPE
        assert section.page_width > section.page_height
    assert [len(table.columns) for table in document.tables] == [3, 3]


def test_cover_is_the_outside_right_panel(tmp_path: Path) -> None:
    document = build(FoldType.TRI, tmp_path)
    assert "Acme" in cell_texts(document, 0)[2]
    assert "Headline Who we are" in cell_texts(document, 1)[0]


def test_half_fold_has_two_panels_per_side(tmp_path: Path) -> None:
    document = build(FoldType.HALF, tmp_path)
    assert [len(table.columns) for table in document.tables] == [2, 2]
    assert "Acme" in cell_texts(document, 0)[1]


def test_panel_headlines_reach_the_document(tmp_path: Path) -> None:
    document = build(FoldType.TRI, tmp_path)
    everything = " ".join(cell_texts(document, 0) + cell_texts(document, 1))
    assert "Headline Highlights" in everything


def test_panels_have_no_all_caps_labels(tmp_path: Path) -> None:
    document = build(FoldType.TRI, tmp_path)
    everything = " ".join(cell_texts(document, 0) + cell_texts(document, 1))
    assert "WHO WE ARE" not in everything
    assert "CALL TO ACTION" not in everything


def test_full_colour_fills_the_cover_with_the_primary_colour(tmp_path: Path) -> None:
    document = build(FoldType.TRI, tmp_path, Preset.FULL_COLOUR)
    cover = document.tables[0].rows[0].cells[2]
    assert fill_of(cover) == PALETTE.primary.lstrip("#")
    who = document.tables[1].rows[0].cells[0]
    assert fill_of(who) == PALETTE.paper.lstrip("#")


def test_night_fills_ordinary_panels_with_ink(tmp_path: Path) -> None:
    document = build(FoldType.TRI, tmp_path, Preset.NIGHT)
    who = document.tables[1].rows[0].cells[0]
    assert fill_of(who) == PALETTE.ink.lstrip("#")


def test_paper_keeps_every_panel_on_paper(tmp_path: Path) -> None:
    document = build(FoldType.TRI, tmp_path, Preset.PAPER)
    fills = {fill_of(cell) for table in document.tables for cell in table.rows[0].cells}
    assert fills == {PALETTE.paper.lstrip("#")}


def test_gallery_panel_shows_only_its_image(tmp_path: Path) -> None:
    image = tmp_path / "img-1.png"
    image.write_bytes(make_png())
    plan = overview_for(FoldType.TRI)
    plan.panels[5] = Panel(section=PanelSection.GALLERY, image_id="img-1")
    path = build_brochure(
        plan,
        get_fold_spec(FoldType.TRI),
        BRAND,
        THEME,
        {"img-1": image},
        tmp_path / "brochure.docx",
    )
    gallery = Document(path).tables[1].rows[0].cells[2]
    assert gallery.text == ""
    assert gallery._tc.xpath(".//w:drawing")


def test_cover_prints_its_message_but_not_a_repeat_of_the_brand_name(tmp_path: Path) -> None:
    document = build(FoldType.TRI, tmp_path)
    assert "Headline Cover" in cell_texts(document, 0)[2]

    plan = overview_for(FoldType.TRI)
    plan.panels[2] = Panel(section=PanelSection.COVER, headline="acme")
    path = build_brochure(
        plan, get_fold_spec(FoldType.TRI), BRAND, THEME, {}, tmp_path / "repeat.docx"
    )
    cover = cell_texts(Document(path), 0)[2]
    assert cover.lower().count("acme") == 1
