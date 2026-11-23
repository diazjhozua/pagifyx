"""Downloads and stores the images and logo a brochure uses, inside a session's assets folder."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from pagifyx.reading.images import ImageCandidate, is_embeddable, sniff_image_type

MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class ImageAsset:
    """A downloaded image. `image_id` is the handle the LLM uses to place it."""

    image_id: str
    path: Path
    alt: str
    width: int
    height: int


async def fetch_bytes(client: httpx.AsyncClient, url: str) -> bytes | None:
    """Download a resource. Returns None on any failure, so one bad URL never stops a read."""
    try:
        response = await client.get(url)
    except httpx.HTTPError:
        return None
    if response.status_code != 200 or len(response.content) > MAX_DOWNLOAD_BYTES:
        return None
    return response.content


def store_logo(dest: Path, data: bytes, stem: str = "logo") -> Path | None:
    """Write a logo that python-docx can embed. Returns None when the bytes are unusable."""
    kind = sniff_image_type(data)
    if kind is None or not is_embeddable(data):
        return None
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{stem}.{kind}"
    path.write_bytes(data)
    return path


async def download_images(
    client: httpx.AsyncClient,
    candidates: Sequence[ImageCandidate],
    dest: Path,
    *,
    prefix: str = "",
) -> list[ImageAsset]:
    """Download candidates in order, keeping only images python-docx can embed.

    `prefix` is added to each file name, so a new read never overwrites files from an earlier one.
    """
    dest.mkdir(parents=True, exist_ok=True)
    assets: list[ImageAsset] = []
    for candidate in candidates:
        data = await fetch_bytes(client, candidate.url)
        if data is None:
            continue
        kind = sniff_image_type(data)
        if kind is None or not is_embeddable(data):
            continue
        image_id = f"img-{len(assets) + 1}"
        path = dest / f"{prefix}{image_id}.{kind}"
        path.write_bytes(data)
        assets.append(
            ImageAsset(
                image_id=image_id,
                path=path,
                alt=candidate.alt,
                width=candidate.width,
                height=candidate.height,
            )
        )
    return assets
