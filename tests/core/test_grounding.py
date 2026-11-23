import pytest

from pagifyx.core.grounding import check_grounding, unsupported_details
from pagifyx.core.models import Design, FoldType, Overview, Panel, PanelSection, Preset


def plan_with(body: str) -> Overview:
    return Overview(
        fold=FoldType.HALF,
        design=Design(preset=Preset.PAPER, primary="#1F4E79"),
        panels=[Panel(section=PanelSection.WHO_WE_ARE, headline="About us", body=body)],
    )


def test_numbers_on_the_website_pass_even_with_different_separators() -> None:
    plan = plan_with("Trusted by 1,000 teams and 4.5 stars.")
    assert unsupported_details(plan, ["Used by 1000 teams, rated 4.5 stars"]) == []


def test_a_number_missing_from_every_source_is_reported() -> None:
    plan = plan_with("Save 40% today.")
    assert unsupported_details(plan, ["Simple budgeting for families"]) == ["40"]


def test_an_email_must_appear_in_a_source() -> None:
    plan = plan_with("Write to hello@example.com.")
    assert unsupported_details(plan, ["Contact: hello@example.com"]) == []
    assert unsupported_details(plan, ["Contact us online"]) == ["hello@example.com"]


def test_check_grounding_raises_with_the_details_listed() -> None:
    with pytest.raises(ValueError, match="not on the website or in the form: 499"):
        check_grounding(plan_with("Only £499 this month."), ["Budgeting for families"])


def test_text_without_numbers_always_passes() -> None:
    check_grounding(plan_with("Plain words, no figures."), [])
