"""Brand: the company identity (name, tagline, logo) and how its logo is picked from a page."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pagifyx.core.models import Contact


@dataclass(frozen=True)
class LogoHint:
    """A logo-like element on the homepage, tagged in the DOM as `element_id`."""

    element_id: str
    hint: str  # lowercased alt text, class names, and src


@dataclass
class BrandOverrides:
    """User-entered brand values. A blank field keeps the extracted value."""

    brand_name: str = ""
    tagline: str = ""
    logo_path: Path | None = None
    contact: Contact = field(default_factory=Contact)


def choose_logo(candidates: Sequence[LogoHint]) -> LogoHint | None:
    """Prefer an element that says 'logo' in its hint; otherwise the first header-level one."""
    for candidate in candidates:
        if "logo" in candidate.hint:
            return candidate
    return candidates[0] if candidates else None
