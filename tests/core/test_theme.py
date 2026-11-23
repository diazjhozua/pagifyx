import pytest

from pagifyx.core.fonts import FALLBACK_FONT
from pagifyx.core.theme import (
    MIN_TEXT_CONTRAST,
    ThemeOverrides,
    build_palette,
    candidate_colours,
    contrast_ratio,
    detect_font_family,
    detect_primary_color,
    first_font_family,
    parse_color,
    resolve_theme,
)


def test_parse_color_reads_rgb_and_rgba() -> None:
    assert parse_color("rgb(31, 78, 121)") == (31, 78, 121)
    assert parse_color("rgba(31, 78, 121, 0.5)") == (31, 78, 121)


def test_parse_color_ignores_transparent() -> None:
    assert parse_color("rgba(0, 0, 0, 0)") is None
    assert parse_color("transparent") is None
    assert parse_color("oklch(0.5 0.2 30 / 0)") is None


def test_parse_color_converts_oklab_to_srgb() -> None:
    assert parse_color("oklab(0.627955 0.224863 0.125846)") == pytest.approx((255, 0, 0), abs=1)
    assert parse_color("oklab(1 0 0)") == pytest.approx((255, 255, 255), abs=1)
    assert parse_color("oklab(0 0 0)") == (0, 0, 0)


def test_parse_color_converts_oklch_to_the_same_srgb_as_oklab() -> None:
    assert parse_color("oklch(0.627955 0.25769 29.2339)") == pytest.approx((255, 0, 0), abs=1)


def test_parse_color_reads_oklab_with_alpha() -> None:
    near_white = parse_color("oklab(0.977 -0.000826912 0.00288378 / 0.8)")
    assert near_white is not None
    assert min(near_white) > 225


def test_detect_primary_color_reads_oklch_from_modern_css() -> None:
    # Values captured from tydee.diazjhozua.com, which serializes its colors as oklch.
    counts = {
        "oklch(0.185 0.012 168)": 3,
        "oklch(0.977 0.003 106)": 1,
        "oklch(0.596 0.145 163.225)": 1,
    }
    primary = detect_primary_color(counts)
    assert primary is not None
    red, green, blue = (int(primary[i : i + 2], 16) for i in (1, 3, 5))
    assert green > red and green > blue


def test_detect_primary_color_skips_neutrals_and_picks_most_common_accent() -> None:
    counts = {
        "rgb(255, 255, 255)": 50,
        "rgb(20, 20, 20)": 40,
        "rgb(200, 30, 40)": 6,
        "rgb(31, 78, 121)": 9,
    }
    assert detect_primary_color(counts) == "#1F4E79"


def test_detect_primary_color_is_none_when_only_neutrals() -> None:
    assert detect_primary_color({"rgb(128, 128, 128)": 3}) is None


def test_detect_primary_color_keeps_a_true_blue_link_color() -> None:
    # Links are no longer sampled, so a brand that really uses #0000EE is not dropped.
    assert detect_primary_color({"rgb(0, 0, 238)": 4}) == "#0000EE"


def test_first_font_family_skips_generics_and_quotes() -> None:
    assert first_font_family('"Inter", Arial, sans-serif') == "Inter"
    assert first_font_family("system-ui, sans-serif") is None


def test_detect_font_family_picks_the_most_common_concrete_family() -> None:
    assert detect_font_family({'"Inter", sans-serif': 5, "Georgia, serif": 2}) == "Inter"


def test_resolve_theme_prefers_overrides() -> None:
    theme = resolve_theme(
        "#1F4E79", "", "Inter", ThemeOverrides(primary_color="#AA0000", font_family="Georgia")
    )
    assert theme.palette.primary == "#AA0000"
    assert theme.font_family == "Georgia"


def test_resolve_theme_uses_the_plan_colour_and_falls_back_on_the_font() -> None:
    theme = resolve_theme("#1F4E79", "#C0392B", None, ThemeOverrides())
    assert theme.palette.primary == "#1F4E79"
    assert theme.palette.accent == "#C0392B"
    assert theme.font_family == FALLBACK_FONT


def test_candidate_colours_lists_the_most_common_saturated_colours() -> None:
    counts = {
        "rgb(31, 78, 121)": 9,
        "rgb(200, 30, 40)": 6,
        "rgb(255, 255, 255)": 50,
        "rgb(20, 20, 20)": 40,
    }
    assert candidate_colours(counts) == ["#1F4E79", "#C81E28"]


def test_candidate_colours_falls_back_to_the_default_when_nothing_is_saturated() -> None:
    assert candidate_colours({"rgb(128, 128, 128)": 3}) == ["#1F4E79"]


def test_contrast_ratio_matches_the_wcag_extremes() -> None:
    assert round(contrast_ratio("#000000", "#FFFFFF"), 1) == 21.0
    assert contrast_ratio("#777777", "#777777") == 1.0


def test_palette_darkens_a_light_primary_until_paper_text_reads() -> None:
    palette = build_palette("#FFE100")
    assert contrast_ratio(palette.paper, palette.primary) >= MIN_TEXT_CONTRAST
    assert palette.text_on(palette.primary) == palette.paper


def test_palette_text_on_a_fill_meets_the_contrast_minimum() -> None:
    palette = build_palette("#1F4E79")
    for fill in (palette.primary, palette.paper, palette.ink):
        assert contrast_ratio(palette.text_on(fill), fill) >= MIN_TEXT_CONTRAST
