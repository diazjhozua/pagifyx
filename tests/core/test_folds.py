import pytest

from pagifyx.core.folds import check_plan, face_panels, get_fold_spec
from pagifyx.core.models import Design, FoldType, Overview, Panel, PanelSection, Preset

DESIGN = Design(preset=Preset.PAPER, primary="#1F4E79")
IMAGES = {"img-1"}


def plan(fold: FoldType, panels: list[Panel]) -> Overview:
    return Overview(fold=fold, design=DESIGN, panels=panels)


def text(section: PanelSection, headline: str = "A headline") -> Panel:
    return Panel(section=section, headline=headline, body="Some copy.")


HALF_PLAN = [
    text(PanelSection.CALL_TO_ACTION),
    text(PanelSection.COVER),
    text(PanelSection.WHO_WE_ARE),
    text(PanelSection.WHAT_WE_OFFER),
]
TRI_PLAN = [
    text(PanelSection.CALL_TO_ACTION),
    text(PanelSection.CONTACT),
    text(PanelSection.COVER),
    text(PanelSection.WHO_WE_ARE),
    text(PanelSection.WHAT_WE_OFFER),
    Panel(section=PanelSection.GALLERY, image_id="img-1"),
]


@pytest.mark.parametrize(
    ("fold", "panels", "per_side"),
    [(FoldType.HALF, 4, 2), (FoldType.TRI, 6, 3), (FoldType.Z, 6, 3)],
)
def test_fold_panel_counts(fold: FoldType, panels: int, per_side: int) -> None:
    spec = get_fold_spec(fold)
    assert spec.panel_count == panels
    assert spec.panels_per_side == per_side


def test_face_panels_split_the_plan_by_side_in_print_order() -> None:
    outside, inside = face_panels(plan(FoldType.TRI, TRI_PLAN), get_fold_spec(FoldType.TRI))
    assert [panel.section for panel in outside] == [
        PanelSection.CALL_TO_ACTION,
        PanelSection.CONTACT,
        PanelSection.COVER,
    ]
    assert [panel.section for panel in inside] == [
        PanelSection.WHO_WE_ARE,
        PanelSection.WHAT_WE_OFFER,
        PanelSection.GALLERY,
    ]


def test_valid_plans_pass() -> None:
    check_plan(
        plan(FoldType.TRI, TRI_PLAN),
        get_fold_spec(FoldType.TRI),
        IMAGES,
        contact_available=True,
    )
    check_plan(
        plan(FoldType.HALF, HALF_PLAN),
        get_fold_spec(FoldType.HALF),
        set(),
        contact_available=False,
    )


def test_wrong_panel_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="exactly 4 panels"):
        check_plan(
            plan(FoldType.HALF, HALF_PLAN[:3]),
            get_fold_spec(FoldType.HALF),
            set(),
            contact_available=False,
        )


def test_cover_must_be_the_last_outside_panel() -> None:
    panels = [HALF_PLAN[1], HALF_PLAN[0], HALF_PLAN[2], HALF_PLAN[3]]
    with pytest.raises(ValueError, match="Cover"):
        check_plan(
            plan(FoldType.HALF, panels),
            get_fold_spec(FoldType.HALF),
            set(),
            contact_available=False,
        )


def test_contact_panel_needs_contact_details() -> None:
    with pytest.raises(ValueError, match="Contact"):
        check_plan(
            plan(FoldType.TRI, TRI_PLAN),
            get_fold_spec(FoldType.TRI),
            IMAGES,
            contact_available=False,
        )


def test_gallery_panel_needs_an_image() -> None:
    panels = [*TRI_PLAN[:5], Panel(section=PanelSection.GALLERY)]
    with pytest.raises(ValueError, match="needs an image_id"):
        check_plan(
            plan(FoldType.TRI, panels), get_fold_spec(FoldType.TRI), IMAGES, contact_available=True
        )


def test_panels_other_than_gallery_need_a_headline() -> None:
    panels = [*HALF_PLAN]
    panels[2] = Panel(section=PanelSection.WHO_WE_ARE, headline="  ")
    with pytest.raises(ValueError, match="needs a headline"):
        check_plan(
            plan(FoldType.HALF, panels),
            get_fold_spec(FoldType.HALF),
            set(),
            contact_available=False,
        )


def test_contact_panel_is_used_at_most_once() -> None:
    panels = [*TRI_PLAN]
    panels[3] = text(PanelSection.CONTACT)
    with pytest.raises(ValueError, match="Contact panel at most once"):
        check_plan(
            plan(FoldType.TRI, panels), get_fold_spec(FoldType.TRI), IMAGES, contact_available=True
        )


def test_other_sections_may_repeat() -> None:
    panels = [*HALF_PLAN]
    panels[3] = text(PanelSection.WHO_WE_ARE)
    check_plan(
        plan(FoldType.HALF, panels), get_fold_spec(FoldType.HALF), set(), contact_available=False
    )


def test_unknown_image_is_rejected() -> None:
    panels = [*HALF_PLAN]
    panels[0] = Panel(section=PanelSection.CALL_TO_ACTION, headline="Act", image_id="img-9")
    with pytest.raises(ValueError, match="unknown image"):
        check_plan(
            plan(FoldType.HALF, panels),
            get_fold_spec(FoldType.HALF),
            {"img-1"},
            contact_available=False,
        )


def test_an_image_is_used_at_most_once() -> None:
    panels = [*HALF_PLAN]
    panels[0] = Panel(section=PanelSection.CALL_TO_ACTION, headline="Act", image_id="img-1")
    panels[2] = Panel(section=PanelSection.WHO_WE_ARE, headline="Who", image_id="img-1")
    with pytest.raises(ValueError, match="more than once"):
        check_plan(
            plan(FoldType.HALF, panels),
            get_fold_spec(FoldType.HALF),
            {"img-1"},
            contact_available=False,
        )
