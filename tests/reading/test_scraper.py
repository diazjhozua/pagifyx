import pytest

from pagifyx.reading.scraper import ScrapeError, coerce_start_url, normalize_url, select_nav_links


def test_coerce_start_url_adds_https() -> None:
    assert coerce_start_url("  Example.com/ ") == "https://example.com/"


@pytest.mark.parametrize("raw", ["", "ftp://example.com/file", "http://["])
def test_coerce_start_url_rejects_unusable_input(raw: str) -> None:
    with pytest.raises(ScrapeError):
        coerce_start_url(raw)


def test_normalize_url_drops_fragment_query_and_asset_links() -> None:
    assert normalize_url("https://Example.com/about/?x=1#top") == "https://example.com/about"
    assert normalize_url("https://example.com/brochure.pdf") is None
    assert normalize_url("mailto:hi@example.com") is None


def test_select_nav_links_is_same_domain_unique_limited_and_robots_aware() -> None:
    links = [
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/about#team",
        "https://other.com/x",
        "https://www.example.com/services",
        "https://example.com/private",
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
        "https://example.com/d",
    ]
    picked = select_nav_links(
        links,
        "https://example.com",
        is_allowed=lambda url: not url.endswith("/private"),
    )
    assert picked == [
        "https://example.com/about",
        "https://www.example.com/services",
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]
