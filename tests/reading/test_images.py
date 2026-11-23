import struct
import zlib

from pagifyx.reading.images import ImageCandidate, is_embeddable, select_images, sniff_image_type


def candidate(url: str, width: int = 800, height: int = 600) -> ImageCandidate:
    return ImageCandidate(url=url, width=width, height=height, alt="")


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


def test_select_images_drops_icons_tracking_svg_and_small_images() -> None:
    candidates = [
        candidate("https://x.test/a.jpg"),
        candidate("https://x.test/logo.svg"),
        candidate("https://x.test/tiny.jpg", width=120),
        candidate("https://x.test/favicon-512.png"),
        candidate("https://x.test/pixel.gif"),
        candidate("data:image/png;base64,AAAA"),
    ]
    assert [c.url for c in select_images(candidates)] == ["https://x.test/a.jpg"]


def test_select_images_dedupes_sorts_by_area_and_caps_at_eight() -> None:
    candidates = [
        candidate(f"https://x.test/{i}.jpg", width=400 + i * 10, height=300) for i in range(10)
    ]
    candidates.append(candidate("https://x.test/0.jpg", width=400, height=300))
    kept = select_images(candidates)
    assert len(kept) == 8
    assert kept[0].width == 490
    assert len({c.url for c in kept}) == 8


def test_sniff_image_type_accepts_png_and_jpeg_only() -> None:
    assert sniff_image_type(b"\x89PNG\r\n\x1a\n....") == "png"
    assert sniff_image_type(b"\xff\xd8\xff\xe0....") == "jpeg"
    assert sniff_image_type(b"GIF89a") is None


def test_is_embeddable_accepts_a_real_png_and_rejects_junk() -> None:
    assert is_embeddable(make_png())
    assert not is_embeddable(b"\x89PNG\r\n\x1a\nnot really a png")
    assert not is_embeddable(b"<svg></svg>")
