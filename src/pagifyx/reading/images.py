"""Rules for which images suit a brochure, and whether python-docx can embed them."""

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlparse

from docx.image.image import Image

MIN_IMAGE_WIDTH = 400
MAX_IMAGES = 8

# Substrings that mark tracking, icon, and placeholder images regardless of size.
_EXCLUDED_MARKERS = ("favicon", "pixel", "tracking", "beacon", "spacer")


@dataclass(frozen=True)
class ImageCandidate:
    """An image element as found on a page, before any filtering."""

    url: str
    width: int
    height: int
    alt: str


def select_images(
    candidates: Iterable[ImageCandidate],
    *,
    limit: int = MAX_IMAGES,
    min_width: int = MIN_IMAGE_WIDTH,
) -> list[ImageCandidate]:
    """Keep large, non-icon raster images, de-duplicated, largest first, capped at `limit`."""
    kept: list[ImageCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = candidate.url.lower()
        if candidate.url in seen or url.startswith("data:"):
            continue
        if urlparse(url).path.endswith(".svg") or candidate.width < min_width:
            continue
        if any(marker in url for marker in _EXCLUDED_MARKERS):
            continue
        seen.add(candidate.url)
        kept.append(candidate)
    kept.sort(key=lambda c: c.width * c.height, reverse=True)
    return kept[:limit]


def sniff_image_type(data: bytes) -> str | None:
    """Return 'png' or 'jpeg' for the formats python-docx embeds reliably, else None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    return None


def is_embeddable(data: bytes) -> bool:
    """True if the bytes are a PNG or JPEG that python-docx can parse and embed."""
    if sniff_image_type(data) is None:
        return False
    try:
        Image.from_blob(data)
    except Exception:
        # Any parse failure means python-docx cannot embed the image, so it is unusable.
        return False
    return True
