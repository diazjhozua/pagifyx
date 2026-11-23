"""Theme: the visual system of a website (palette and font), detected and then overridable.

Brand (name, tagline, logo) lives in brand.py and models.py. Keep the two apart.
"""

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pagifyx.core.fonts import resolve_font

DEFAULT_PRIMARY_COLOR = "#1F4E79"
MIN_TEXT_CONTRAST = 4.5

_GENERIC_FONTS = frozenset(
    {
        "serif",
        "sans-serif",
        "monospace",
        "cursive",
        "fantasy",
        "system-ui",
        "ui-serif",
        "ui-sans-serif",
        "ui-monospace",
        "emoji",
        "math",
        "inherit",
        "initial",
    }
)

_RGB_PATTERN = re.compile(
    r"rgba?\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)"
    r"\s*(?:,\s*(\d+(?:\.\d+)?)\s*)?\)"
)

_OKLAB_PATTERN = re.compile(
    r"ok(lab|lch)\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)"
    r"(?:\s*/\s*(\d+(?:\.\d+)?%?))?\s*\)"
)


@dataclass(frozen=True)
class Palette:
    """Colour roles for one brochure. Text on any fill is picked to meet MIN_TEXT_CONTRAST."""

    ink: str  # body text on paper
    paper: str  # page background
    primary: str  # cover and call-to-action fills, and headlines on paper
    accent: str  # rules and highlights

    def text_on(self, fill: str) -> str:
        """The text colour (paper or ink) with the stronger contrast against `fill`."""
        if contrast_ratio(self.paper, fill) >= contrast_ratio(self.ink, fill):
            return self.paper
        return self.ink


@dataclass(frozen=True)
class Theme:
    """Resolved visual system used to paint a brochure."""

    font_family: str
    palette: Palette


@dataclass
class ThemeOverrides:
    """User-entered theme values. A blank field keeps the value the plan chose."""

    primary_color: str = ""
    font_family: str = ""


def resolve_theme(
    primary: str, accent: str, detected_font: str | None, overrides: ThemeOverrides
) -> Theme:
    """Apply overrides first. Fall back to the site font only when this machine has it."""
    return Theme(
        font_family=overrides.font_family or resolve_font(detected_font),
        palette=build_palette(overrides.primary_color or primary, accent),
    )


def build_palette(primary: str, accent: str = "") -> Palette:
    """Derive readable colour roles from one website colour.

    The primary darkens until paper-coloured text meets MIN_TEXT_CONTRAST on it, so the same
    colour works as a cover fill and as a headline colour.
    """
    paper = mix(primary, "#FFFFFF", 0.95)
    ink = mix(primary, "#000000", 0.85)
    fill = primary
    for _ in range(40):
        if contrast_ratio(paper, fill) >= MIN_TEXT_CONTRAST:
            break
        fill = mix(fill, "#000000", 0.05)
    return Palette(ink=ink, paper=paper, primary=fill, accent=accent or mix(fill, "#FFFFFF", 0.4))


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def mix(color: str, toward: str, weight: float) -> str:
    """Blend `color` toward `toward`. Weight 0 keeps `color`; weight 1 gives `toward`."""
    start, end = hex_to_rgb(color), hex_to_rgb(toward)
    return to_hex(tuple(round(a + (b - a) * weight) for a, b in zip(start, end, strict=True)))


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    """WCAG contrast ratio between two #RRGGBB colours, from 1 to 21."""
    lighter, darker = sorted(
        (_relative_luminance(hex_to_rgb(first)), _relative_luminance(hex_to_rgb(second))),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def parse_color(value: str) -> tuple[int, int, int] | None:
    """Parse a computed color to 8-bit sRGB. Fully transparent colors return None.

    Modern CSS makes getComputedStyle return oklab()/oklch() values, so both are converted.
    """
    value = value.strip()
    rgb_match = _RGB_PATTERN.fullmatch(value)
    if rgb_match is not None:
        alpha = rgb_match.group(4)
        if alpha is not None and float(alpha) == 0:
            return None
        red, green, blue = (round(float(part)) for part in rgb_match.group(1, 2, 3))
        return red, green, blue
    oklab_match = _OKLAB_PATTERN.fullmatch(value)
    if oklab_match is None:
        return None
    kind, first, second, third, alpha = oklab_match.groups()
    if alpha is not None and float(alpha.rstrip("%")) == 0:
        return None
    lightness = float(first)
    if kind == "lch":
        chroma, hue = float(second), math.radians(float(third))
        a, b = chroma * math.cos(hue), chroma * math.sin(hue)
    else:
        a, b = float(second), float(third)
    return _oklab_to_srgb(lightness, a, b)


def _oklab_to_srgb(lightness: float, a: float, b: float) -> tuple[int, int, int]:
    """Convert OKLab to 8-bit sRGB using Bjorn Ottosson's published matrices."""
    cube_l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    cube_m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    cube_s = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    linear_red = 4.0767416621 * cube_l - 3.3077115913 * cube_m + 0.2309699292 * cube_s
    linear_green = -1.2684380046 * cube_l + 2.6097574011 * cube_m - 0.3413193965 * cube_s
    linear_blue = -0.0041960863 * cube_l - 0.7034186147 * cube_m + 1.7076147010 * cube_s
    red, green, blue = (
        round(255 * _srgb_encode(channel)) for channel in (linear_red, linear_green, linear_blue)
    )
    return red, green, blue


def _srgb_encode(linear: float) -> float:
    """Apply the sRGB transfer curve. Out-of-gamut values are clamped to the 0-1 range."""
    clamped = min(max(linear, 0.0), 1.0)
    if clamped <= 0.0031308:
        return 12.92 * clamped
    return 1.055 * clamped ** (1 / 2.4) - 0.055


def is_neutral(rgb: tuple[int, int, int]) -> bool:
    """True for greys, near-black, and near-white. These make poor brand accents."""
    spread = max(rgb) - min(rgb)
    return spread < 24 or max(rgb) < 40 or min(rgb) > 225


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def first_font_family(stack: str) -> str | None:
    """Return the first concrete family in a CSS font-family list."""
    for part in stack.split(","):
        name = part.strip().strip("\"'").strip()
        if name and name.lower() not in _GENERIC_FONTS:
            return name
    return None


def _most_common(pairs: Iterable[tuple[str | None, int]]) -> str | None:
    totals: Counter[str] = Counter()
    for key, count in pairs:
        if key is not None:
            totals[key] += count
    return totals.most_common(1)[0][0] if totals else None


def _saturated_hex(value: str) -> str | None:
    rgb = parse_color(value)
    if rgb is None or is_neutral(rgb):
        return None
    return to_hex(rgb)


def detect_primary_color(color_counts: Mapping[str, int]) -> str | None:
    """Most frequent saturated color across sampled surfaces, as #RRGGBB."""
    return _most_common((_saturated_hex(value), count) for value, count in color_counts.items())


def detect_font_family(font_counts: Mapping[str, int]) -> str | None:
    """Most frequent concrete font family across sampled elements."""
    return _most_common((first_font_family(stack), count) for stack, count in font_counts.items())


def candidate_colours(color_counts: Mapping[str, int], limit: int = 4) -> list[str]:
    """The most frequent saturated colours on the site, most common first.

    The plan picks its primary and accent from this list. Falls back to the default colour.
    """
    totals: Counter[str] = Counter()
    for value, count in color_counts.items():
        hex_value = _saturated_hex(value)
        if hex_value is not None:
            totals[hex_value] += count
    picked = [colour for colour, _ in totals.most_common(limit)]
    return picked or [DEFAULT_PRIMARY_COLOR]
