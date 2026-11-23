"""Fold layouts. A fold fixes the panel count per side. The model fills those panels."""

from collections.abc import Collection
from dataclasses import dataclass

from pagifyx.core.models import FoldType, Overview, Panel, PanelSection


@dataclass(frozen=True)
class FoldSpec:
    """Physical layout of one fold type. Both sides hold the same number of panels."""

    label: str
    description: str
    panels_per_side: int

    @property
    def panel_count(self) -> int:
        return self.panels_per_side * 2


FOLD_SPECS: dict[FoldType, FoldSpec] = {
    FoldType.HALF: FoldSpec(
        label="Half-fold",
        description="4 panels, 2 per side, folded in half.",
        panels_per_side=2,
    ),
    FoldType.TRI: FoldSpec(
        label="Tri-fold",
        description="6 panels, 3 per side, standard letter fold.",
        panels_per_side=3,
    ),
    FoldType.Z: FoldSpec(
        label="Z-fold",
        description="6 panels, 3 per side. The panels fold in opposite directions.",
        panels_per_side=3,
    ),
}


def get_fold_spec(fold: FoldType) -> FoldSpec:
    return FOLD_SPECS[fold]


def check_plan(
    overview: Overview,
    spec: FoldSpec,
    image_ids: Collection[str],
    *,
    contact_available: bool,
) -> None:
    """Raise ValueError unless the plan fits the fold, the images, and the contact rule."""
    if len(overview.panels) != spec.panel_count:
        raise ValueError(f"Use exactly {spec.panel_count} panels for a {spec.label}.")
    cover_positions = [
        index for index, panel in enumerate(overview.panels) if panel.section is PanelSection.COVER
    ]
    if cover_positions != [spec.panels_per_side - 1]:
        raise ValueError("Use exactly one Cover panel, as the last panel of the outside side.")
    contact_panels = sum(panel.section is PanelSection.CONTACT for panel in overview.panels)
    if contact_panels > 1:
        raise ValueError("Use the Contact panel at most once.")
    used_images: set[str] = set()
    for number, panel in enumerate(overview.panels, start=1):
        _check_panel(panel, number, image_ids, used_images, contact_available)


def _check_panel(
    panel: Panel,
    number: int,
    image_ids: Collection[str],
    used_images: set[str],
    contact_available: bool,
) -> None:
    if panel.section is PanelSection.CONTACT and not contact_available:
        raise ValueError("Use a Contact panel only when the website or form has contact details.")
    if panel.section is PanelSection.GALLERY:
        if panel.image_id is None:
            raise ValueError(f"Panel {number} is a Gallery panel and needs an image_id.")
    elif not panel.headline.strip():
        raise ValueError(f"Panel {number} needs a headline.")
    if panel.image_id is None:
        return
    if panel.image_id not in image_ids:
        raise ValueError(f"Panel {number} uses unknown image '{panel.image_id}'.")
    if panel.image_id in used_images:
        raise ValueError(f"Image '{panel.image_id}' is used more than once.")
    used_images.add(panel.image_id)


def face_panels(overview: Overview, spec: FoldSpec) -> tuple[list[Panel], list[Panel]]:
    """Panels for the outside and inside sides, each left to right as printed."""
    cut = spec.panels_per_side
    return list(overview.panels[:cut]), list(overview.panels[cut:])
