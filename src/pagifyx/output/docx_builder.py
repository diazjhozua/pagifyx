"""Builds the printable .docx: landscape Letter, one section per face, one table per face.

Each face is one table row with one column per panel, as tall as the printable area, so every
panel is a full-height block. The plan's preset and the theme's palette decide the look:

- Full colour: the cover and call to action are solid primary blocks. Other panels are paper.
- Night: the cover and call to action are primary blocks. Other panels are ink, with paper text.
- Paper: every panel is paper. Headlines are primary and carry an accent rule.

Headlines have no labels above them. Three or more lines of body text become a bulleted list.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import (
    WD_CELL_VERTICAL_ALIGNMENT,
    WD_ROW_HEIGHT_RULE,
    WD_TABLE_ALIGNMENT,
)
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.section import Section
from docx.shared import Emu, Inches, Pt, RGBColor
from docx.table import _Cell
from docx.text.paragraph import Paragraph

from pagifyx.core.folds import FoldSpec, face_panels
from pagifyx.core.models import Overview, Panel, PanelSection, Preset
from pagifyx.core.theme import MIN_TEXT_CONTRAST, Palette, Theme, contrast_ratio, mix

PAGE_WIDTH = Inches(11)
PAGE_HEIGHT = Inches(8.5)
MARGIN = Inches(0.5)
# Slightly under the printable height (8.5 in less two 0.5 in margins) so the paragraph that
# ends each section never spills onto an extra page.
FACE_HEIGHT = Inches(7.2)
PAD_X = Inches(0.4)
PAD_TOP = Inches(0.5)
# Three or more lines of body text become a bulleted list. Fewer lines stay as paragraphs.
BULLET_THRESHOLD = 3
# Panels whose fill is the emphasis colour of the preset.
_EMPHASISED = (PanelSection.COVER, PanelSection.CALL_TO_ACTION)


@dataclass(frozen=True)
class Typography:
    """Type sizes in points, on one scale. Each step is about 1.3 times the one below it."""

    cover_pt: float
    headline_pt: float
    lead_pt: float
    body_pt: float


# Three panels per side: the usual face. Two panels per side: larger type on a wider panel.
THREE_ACROSS = Typography(cover_pt=40, headline_pt=26, lead_pt=14, body_pt=11.5)
TWO_ACROSS = Typography(cover_pt=48, headline_pt=34, lead_pt=16, body_pt=13.5)

# OOXML requires these children in this order. Word reports the file as damaged if they are not.
_TCPR_ORDER = (
    "cnfStyle",
    "tcW",
    "gridSpan",
    "hMerge",
    "vMerge",
    "tcBorders",
    "shd",
    "noWrap",
    "tcMar",
    "textDirection",
    "tcFitText",
    "vAlign",
    "hideMark",
)
_PPR_ORDER = (
    "pStyle",
    "keepNext",
    "keepLines",
    "pageBreakBefore",
    "framePr",
    "widowControl",
    "numPr",
    "suppressLineNumbers",
    "pBdr",
    "shd",
    "tabs",
    "suppressAutoHyphens",
    "kinsoku",
    "wordWrap",
    "overflowPunct",
    "topLinePunct",
    "autoSpaceDE",
    "autoSpaceDN",
    "bidi",
    "adjustRightInd",
    "snapToGrid",
    "spacing",
    "ind",
    "contextualSpacing",
    "mirrorIndents",
    "suppressOverlap",
    "jc",
    "textDirection",
    "textAlignment",
    "textboxTightWrap",
    "outlineLvl",
    "divId",
    "cnfStyle",
    "rPr",
    "sectPr",
    "pPrChange",
)


@dataclass(frozen=True)
class BrochureBrand:
    """Brand identity printed on the cover."""

    name: str
    tagline: str
    logo_path: Path | None


@dataclass(frozen=True)
class _Role:
    """Colours for one kind of panel: its fill, its body text, and its headline."""

    fill: str
    text: str
    headline: str


@dataclass(frozen=True)
class _Look:
    emphasis: _Role  # cover and call to action
    default: _Role  # every other panel
    rule: str | None  # accent rule under headlines, if the preset uses one


def _look(preset: Preset, palette: Palette) -> _Look:
    on_primary = palette.text_on(palette.primary)
    if preset is Preset.FULL_COLOUR:
        return _Look(
            emphasis=_Role(palette.primary, on_primary, on_primary),
            default=_Role(palette.paper, palette.ink, palette.primary),
            rule=None,
        )
    if preset is Preset.NIGHT:
        accent_reads = contrast_ratio(palette.accent, palette.ink) >= MIN_TEXT_CONTRAST
        return _Look(
            emphasis=_Role(palette.primary, on_primary, on_primary),
            default=_Role(
                palette.ink, palette.paper, palette.accent if accent_reads else palette.paper
            ),
            rule=None,
        )
    return _Look(
        emphasis=_Role(palette.paper, palette.primary, palette.primary),
        default=_Role(palette.paper, palette.ink, palette.primary),
        rule=palette.accent,
    )


def build_brochure(
    overview: Overview,
    spec: FoldSpec,
    brand: BrochureBrand,
    theme: Theme,
    image_paths: Mapping[str, Path],
    output_path: Path,
) -> Path:
    """Write the brochure to `output_path` and return it."""
    document: DocumentType = Document()
    document.core_properties.title = brand.name or "Brochure"
    normal = document.styles["Normal"]
    normal.font.name = theme.font_family
    normal.font.size = Pt(THREE_ACROSS.body_pt)

    look = _look(overview.design.preset, theme.palette)
    outside, inside = face_panels(overview, spec)
    for number, panels in enumerate((outside, inside)):
        section = document.sections[0] if number == 0 else document.add_section(WD_SECTION.NEW_PAGE)
        _set_landscape_letter(section)
        _write_face(document, panels, brand, theme, image_paths, look)

    _end_with_spacer(document)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_path)
    return output_path


def _end_with_spacer(document: DocumentType) -> None:
    """Word needs a paragraph after the last table. Keep spacers at 1 pt so none adds a page."""
    document.add_paragraph()
    for paragraph in document.paragraphs:
        if not paragraph.text:
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.line_spacing = Pt(1)


def _set_landscape_letter(section: Section) -> None:
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width = PAGE_WIDTH
    section.page_height = PAGE_HEIGHT
    for margin in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, margin, MARGIN)


def _write_face(
    document: DocumentType,
    panels: list[Panel],
    brand: BrochureBrand,
    theme: Theme,
    image_paths: Mapping[str, Path],
    look: _Look,
) -> None:
    table = document.add_table(rows=1, cols=len(panels))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    row = table.rows[0]
    row.height = FACE_HEIGHT
    row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
    column_width = Emu(int((PAGE_WIDTH - 2 * MARGIN) / len(panels)))
    type_ = TWO_ACROSS if len(panels) <= 2 else THREE_ACROSS
    divider = mix(theme.palette.ink, theme.palette.paper, 0.8)
    for column in table.columns:
        column.width = column_width
    last_index = len(panels) - 1
    for index, (cell, panel) in enumerate(zip(row.cells, panels, strict=True)):
        cell.width = column_width
        _set_side_padding(cell)
        if index < last_index:
            _set_right_border(cell, divider)
        role = look.emphasis if panel.section in _EMPHASISED else look.default
        _shade(cell, role.fill)
        _fill_panel(cell, panel, brand, image_paths, column_width, type_, role, look.rule)
        _drop_leading_empty_paragraph(cell)
        if panel.section is not PanelSection.COVER:
            cell.paragraphs[0].paragraph_format.space_before = PAD_TOP


def _fill_panel(
    cell: _Cell,
    panel: Panel,
    brand: BrochureBrand,
    image_paths: Mapping[str, Path],
    column_width: Emu,
    type_: Typography,
    role: _Role,
    rule: str | None,
) -> None:
    if panel.section is PanelSection.COVER:
        _fill_cover(cell, brand, panel, column_width, type_, role)
        return
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
    image_path = image_paths.get(panel.image_id) if panel.image_id else None
    if image_path is not None:
        _add_picture(cell, image_path, Emu(int(column_width - 2 * PAD_X)))
    if panel.section is PanelSection.GALLERY:
        return
    _fill_text(cell, panel, type_, role, rule)


def _fill_cover(
    cell: _Cell,
    brand: BrochureBrand,
    panel: Panel,
    column_width: Emu,
    type_: Typography,
    role: _Role,
) -> None:
    """Cover content sits at the bottom left: the cover message, logo, brand name, and tagline.

    The message is skipped when the model simply repeated the brand name.
    """
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.BOTTOM
    message = panel.headline.strip()
    if message and message.lower() != brand.name.strip().lower():
        _add_paragraph(
            cell, message, type_.headline_pt, bold=True, color=_rgb(role.text), space_after=18
        )
    if brand.logo_path is not None:
        _add_picture(cell, brand.logo_path, Emu(int(column_width * 0.4)), space_after=18)
    _add_paragraph(
        cell,
        brand.name,
        type_.cover_pt,
        bold=True,
        color=_rgb(role.text),
        space_after=6,
    )
    if brand.tagline:
        # Cell padding is top and bottom zero, so the last line needs space below it.
        _add_paragraph(
            cell,
            brand.tagline,
            type_.lead_pt,
            color=_rgb(role.text),
            space_after=PAD_TOP.inches * 72,
        )


def _fill_text(
    cell: _Cell,
    panel: Panel,
    type_: Typography,
    role: _Role,
    rule: str | None,
) -> None:
    headline = _add_paragraph(
        cell,
        panel.headline,
        type_.headline_pt,
        bold=True,
        color=_rgb(role.headline),
        space_after=10,
    )
    if rule is not None:
        _accent_rule(headline, rule)
    lines = [line.strip() for line in panel.body.splitlines() if line.strip()]
    if len(lines) >= BULLET_THRESHOLD:
        for line in lines:
            _add_bullet(cell, line, _rgb(role.text), type_.body_pt)
    else:
        for line in lines:
            _add_paragraph(cell, line, type_.body_pt, color=_rgb(role.text), space_after=4)


def _drop_leading_empty_paragraph(cell: _Cell) -> None:
    """Python-docx cells start with one empty paragraph. Remove it so content sits at the top."""
    first = cell.paragraphs[0]
    if not first.text and len(cell.paragraphs) > 1:
        first._element.getparent().remove(first._element)


def _add_paragraph(
    cell: _Cell,
    text: str,
    size_pt: float,
    *,
    bold: bool = False,
    color: RGBColor | None = None,
    space_after: float = 4,
) -> Paragraph:
    paragraph = cell.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(space_after)
    paragraph.paragraph_format.line_spacing = 1.15
    run = paragraph.add_run(text)
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    return paragraph


def _add_bullet(cell: _Cell, text: str, colour: RGBColor, size_pt: float) -> None:
    paragraph = cell.add_paragraph(style="List Bullet")
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.paragraph_format.line_spacing = 1.15
    run = paragraph.add_run(text)
    run.font.size = Pt(size_pt)
    run.font.color.rgb = colour


def _add_picture(cell: _Cell, path: Path, width: Emu, *, space_after: float = 10) -> None:
    paragraph = cell.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(space_after)
    paragraph.add_run().add_picture(str(path), width=width)


def _rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color.lstrip("#").upper())


def _insert_ordered(parent, child, order: tuple[str, ...]) -> None:
    """Insert `child` at its schema position, replacing any existing element with the same tag."""
    name = child.tag.split("}")[1]
    for existing in parent.findall(qn(f"w:{name}")):
        parent.remove(existing)
    rank = order.index(name)
    for existing in list(parent):
        local = existing.tag.split("}")[1]
        if local in order and order.index(local) > rank:
            existing.addprevious(child)
            return
    parent.append(child)


def _set_side_padding(cell: _Cell) -> None:
    """Left and right cell padding only. Top spacing is a paragraph property (see _write_face).

    Cell top and bottom padding made the face table overflow onto a blank extra page in Word.
    """
    margins = OxmlElement("w:tcMar")
    for side, length in (("left", PAD_X), ("right", PAD_X)):
        element = OxmlElement(f"w:{side}")
        element.set(qn("w:w"), str(round(length.inches * 1440)))
        element.set(qn("w:type"), "dxa")
        margins.append(element)
    _insert_ordered(cell._tc.get_or_add_tcPr(), margins, _TCPR_ORDER)


def _set_right_border(cell: _Cell, hex_color: str) -> None:
    borders = OxmlElement("w:tcBorders")
    right = OxmlElement("w:right")
    right.set(qn("w:val"), "single")
    right.set(qn("w:sz"), "6")
    right.set(qn("w:space"), "0")
    right.set(qn("w:color"), hex_color.lstrip("#").upper())
    borders.append(right)
    _insert_ordered(cell._tc.get_or_add_tcPr(), borders, _TCPR_ORDER)


def _shade(cell: _Cell, hex_color: str) -> None:
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), hex_color.lstrip("#").upper())
    _insert_ordered(cell._tc.get_or_add_tcPr(), shading, _TCPR_ORDER)


def _accent_rule(paragraph: Paragraph, hex_color: str) -> None:
    """A bottom border under a paragraph, used as the accent line under each headline."""
    border = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12")
    bottom.set(qn("w:space"), "6")
    bottom.set(qn("w:color"), hex_color.lstrip("#").upper())
    border.append(bottom)
    _insert_ordered(paragraph._p.get_or_add_pPr(), border, _PPR_ORDER)
