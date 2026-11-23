"""Browser-based website reader.

Reads the homepage plus up to MAX_NAV_PAGES same-domain pages linked from the navigation,
honoring robots.txt. Returns raw facts and a logo screenshot. It writes no files.
"""

import base64
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from pagifyx.core.brand import LogoHint, choose_logo
from pagifyx.reading.images import ImageCandidate

logger = logging.getLogger(__name__)

USER_AGENT = "PagifyxBot/0.1 (local brochure generator; honors robots.txt)"
MAX_NAV_PAGES = 5
MIN_HOMEPAGE_CHARS = 200
MAX_PAGE_CHARS = 20_000
NAV_TIMEOUT_MS = 30_000
IDLE_TIMEOUT_MS = 10_000
VIEWPORT = {"width": 1280, "height": 900}
LOGO_SCALE = 8  # device pixels per CSS pixel when the logo is captured
LOGO_ONLY_CSS = (
    "*:not([data-pagifyx-logo]):not([data-pagifyx-logo] *) { background: transparent !important; }"
    " html, body { background: transparent !important; }"
    " [data-pagifyx-logo] { box-shadow: none !important; }"
)
_SKIPPED_EXTENSIONS = (
    ".pdf",
    ".zip",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".mp3",
    ".mp4",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
)

# Gathers everything the reader needs from one rendered page in a single round trip.
_EXTRACT_JS = r"""
() => {
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const meta = (key) => {
    const el = document.querySelector(`meta[name="${key}"], meta[property="${key}"]`);
    return el ? clean(el.getAttribute('content')) : '';
  };
  // Brand color comes from surfaces (header, buttons) and headings. Links are excluded
  // because browsers give them default colors that say nothing about the brand.
  const colorCounts = {};
  const fontCounts = {};
  for (const el of document.querySelectorAll('header, nav, button, [class*="btn" i]')) {
    const bg = getComputedStyle(el).backgroundColor;
    colorCounts[bg] = (colorCounts[bg] || 0) + 1;
  }
  for (const el of document.querySelectorAll('h1, h2')) {
    const color = getComputedStyle(el).color;
    colorCounts[color] = (colorCounts[color] || 0) + 1;
  }
  for (const el of document.querySelectorAll('h1, h2, p, nav a')) {
    const family = getComputedStyle(el).fontFamily;
    fontCounts[family] = (fontCounts[family] || 0) + 1;
  }
  const logoSelector = [
    'header img', 'header svg', 'nav img', 'nav svg',
    '[class*="logo" i] img', '[class*="logo" i] svg', 'img[alt*="logo" i]',
  ].join(', ');
  // A logo is often a small icon inside a colored tile. Climb to the outermost small box that
  // paints its own background, so the tile is captured and not only the icon inside it.
  const logoMark = (el) => {
    let mark = el;
    for (let node = el.parentElement; node && node !== document.body; node = node.parentElement) {
      const box = node.getBoundingClientRect();
      if (box.width > 120 || box.height > 120) break;
      const style = getComputedStyle(node);
      if (style.backgroundColor !== 'rgba(0, 0, 0, 0)' || style.backgroundImage !== 'none') {
        mark = node;
      }
    }
    return mark;
  };
  const logoPairs = [];
  for (const el of [...document.querySelectorAll(logoSelector)].slice(0, 6)) {
    const mark = logoMark(el);
    if (!logoPairs.some((pair) => pair.mark === mark)) logoPairs.push({ el, mark });
  }
  const logoCandidates = logoPairs.map(({ el, mark }, i) => {
    mark.setAttribute('data-pagifyx-logo', String(i));
    const hint = [el.getAttribute('alt'), el.getAttribute('class'), el.getAttribute('src')]
      .filter(Boolean).join(' ').toLowerCase();
    return { element_id: String(i), hint: hint };
  });
  return {
    title: clean(document.title),
    lang: document.documentElement.lang || '',
    meta_description: meta('description'),
    og_image: meta('og:image'),
    text: clean(document.body ? document.body.innerText : ''),
    links: [...document.querySelectorAll('nav a[href], header a[href], footer a[href]')]
      .map((a) => a.href),
    images: [...document.images].map((img) => ({
      url: img.currentSrc || img.src,
      width: img.naturalWidth,
      height: img.naturalHeight,
      alt: img.alt || '',
    })),
    color_counts: colorCounts,
    font_counts: fontCounts,
    logo_candidates: logoCandidates,
  };
}
"""


class ScrapeError(Exception):
    """The site could not be read. The message is safe to show the user."""


@dataclass(frozen=True)
class PageSnapshot:
    url: str
    title: str
    meta_description: str
    text: str
    links: tuple[str, ...]
    images: tuple[ImageCandidate, ...]


@dataclass
class SiteSnapshot:
    """Everything read from the website. Style and logo come from the homepage."""

    lang: str
    pages: list[PageSnapshot]
    color_counts: dict[str, int]
    font_counts: dict[str, int]
    og_image: str | None
    logo_png: bytes | None = None

    @property
    def images(self) -> list[ImageCandidate]:
        return [image for page in self.pages for image in page.images]


def normalize_url(raw: str) -> str | None:
    """Return an http(s) URL without fragment, query, or trailing slash, else None."""
    try:
        parsed = urlparse(raw.strip())
    except ValueError:  # malformed host, such as "http://["
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    path = parsed.path.rstrip("/") or "/"
    if path.lower().endswith(_SKIPPED_EXTENSIONS):
        return None
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", "", ""))


def coerce_start_url(raw: str) -> str:
    """Accept 'example.com' or a full URL and return a normalized https URL."""
    candidate = raw.strip()
    if not candidate:
        raise ScrapeError("Enter a website address.")
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    normalized = normalize_url(candidate)
    if normalized is None:
        raise ScrapeError("That does not look like a valid http or https address.")
    return normalized


def _host_key(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def select_nav_links(
    links: Iterable[str],
    start_url: str,
    is_allowed: Callable[[str], bool],
    limit: int = MAX_NAV_PAGES,
) -> list[str]:
    """Pick up to `limit` unique same-domain pages, skipping any robots.txt disallows."""
    start = normalize_url(start_url)
    if start is None:
        return []
    host = _host_key(start)
    seen = {start}
    chosen: list[str] = []
    for raw in links:
        url = normalize_url(raw)
        if url is None or url in seen or _host_key(url) != host:
            continue
        seen.add(url)
        if not is_allowed(url):
            continue
        chosen.append(url)
        if len(chosen) == limit:
            break
    return chosen


def _disallow_all() -> RobotFileParser:
    parser = RobotFileParser()
    parser.parse(["User-agent: *", "Disallow: /"])
    return parser


async def _load_robots(start_url: str) -> RobotFileParser | None:
    """Return the parsed robots.txt, or None when it places no restriction.

    Per RFC 9309, a 4xx response means there is no robots file, so everything is allowed.
    A 5xx response or an unreachable file means the rules cannot be checked, so nothing is read.
    """
    robots_url = urljoin(start_url, "/robots.txt")
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=10, follow_redirects=True
        ) as client:
            response = await client.get(robots_url)
    except httpx.HTTPError as exc:
        logger.warning("robots.txt unreachable at %s (%s); not reading the site", robots_url, exc)
        return _disallow_all()
    if response.status_code >= 500:
        logger.warning(
            "robots.txt returned %d at %s; not reading the site", response.status_code, robots_url
        )
        return _disallow_all()
    if response.status_code != 200:
        return None
    parser = RobotFileParser()
    parser.parse(response.text.splitlines())
    return parser


async def _launch(playwright: Playwright) -> Browser:
    try:
        return await playwright.chromium.launch(headless=True)
    except PlaywrightError as exc:
        raise ScrapeError(
            "Chromium is not installed. Run: uv run playwright install chromium"
        ) from exc


async def _open(context: BrowserContext, url: str, is_allowed: Callable[[str], bool]) -> Page:
    """Open and render a page. Errors, and redirects into disallowed paths, raise ScrapeError."""
    page = await context.new_page()
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        if response is None or response.status >= 400:
            status = response.status if response is not None else "no response"
            raise ScrapeError(f"{url} returned {status}.")
        if not is_allowed(page.url):
            raise ScrapeError(f"{page.url} was reached by redirect and robots.txt disallows it.")
        try:
            await page.wait_for_load_state("networkidle", timeout=IDLE_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            logger.debug("networkidle timed out for %s; using rendered DOM", url)
    except Exception:
        await page.close()
        raise
    return page


async def _extract(page: Page) -> dict[str, Any]:
    raw: dict[str, Any] = await page.evaluate(_EXTRACT_JS)
    return raw


def _snapshot(url: str, raw: dict[str, Any]) -> PageSnapshot:
    images = tuple(
        ImageCandidate(
            url=item["url"],
            width=int(item["width"]),
            height=int(item["height"]),
            alt=item["alt"],
        )
        for item in raw["images"]
        if item["url"]
    )
    return PageSnapshot(
        url=url,
        title=raw["title"],
        meta_description=raw["meta_description"],
        text=raw["text"][:MAX_PAGE_CHARS],
        links=tuple(raw["links"]),
        images=images,
    )


async def _capture_logo(page: Page, raw: dict[str, Any]) -> bytes | None:
    """Screenshot the logo mark on a transparent background, at LOGO_SCALE density."""
    hints = [
        LogoHint(element_id=str(item["element_id"]), hint=item["hint"])
        for item in raw["logo_candidates"]
    ]
    chosen = choose_logo(hints)
    if chosen is None:
        return None
    locator = page.locator(f'[data-pagifyx-logo="{chosen.element_id}"]').first
    try:
        await locator.scroll_into_view_if_needed(timeout=NAV_TIMEOUT_MS)
        box = await locator.evaluate(
            """el => {
                const r = el.getBoundingClientRect();
                return {x: r.left + window.scrollX, y: r.top + window.scrollY,
                        width: r.width, height: r.height};
            }"""
        )
        await page.add_style_tag(content=LOGO_ONLY_CSS)
        cdp = await page.context.new_cdp_session(page)
        await cdp.send(
            "Emulation.setDefaultBackgroundColorOverride",
            {"color": {"r": 0, "g": 0, "b": 0, "a": 0}},
        )
        shot = await cdp.send(
            "Page.captureScreenshot",
            {
                "format": "png",
                "clip": {**box, "scale": LOGO_SCALE},
                "captureBeyondViewport": True,
            },
        )
        return base64.b64decode(shot["data"])
    except PlaywrightError as exc:
        logger.warning("Logo screenshot failed: %s", exc)
        return None


async def _read_homepage(
    context: BrowserContext, url: str, is_allowed: Callable[[str], bool]
) -> SiteSnapshot:
    page = await _open(context, url, is_allowed)
    try:
        raw = await _extract(page)
        home = _snapshot(url, raw)
        if len(home.text) < MIN_HOMEPAGE_CHARS:
            raise ScrapeError(
                "The homepage had too little readable text. The site may block automated "
                "browsers or render only with scripts that did not run."
            )
        logo_png = await _capture_logo(page, raw)
    finally:
        await page.close()
    return SiteSnapshot(
        lang=raw["lang"],
        pages=[home],
        color_counts=dict(raw["color_counts"]),
        font_counts=dict(raw["font_counts"]),
        og_image=raw["og_image"] or None,
        logo_png=logo_png,
    )


async def _read_page(
    context: BrowserContext, url: str, is_allowed: Callable[[str], bool]
) -> PageSnapshot:
    page = await _open(context, url, is_allowed)
    try:
        return _snapshot(url, await _extract(page))
    finally:
        await page.close()


async def _crawl_nav(
    context: BrowserContext,
    snapshot: SiteSnapshot,
    start_url: str,
    is_allowed: Callable[[str], bool],
) -> None:
    """Add linked same-domain pages. One page that fails is skipped, not fatal."""
    for link in select_nav_links(snapshot.pages[0].links, start_url, is_allowed):
        try:
            snapshot.pages.append(await _read_page(context, link, is_allowed))
        except (ScrapeError, PlaywrightError) as exc:
            logger.warning("Skipping %s: %s", link, exc)


async def scrape_site(raw_url: str) -> SiteSnapshot:
    """Read the homepage and up to MAX_NAV_PAGES linked same-domain pages."""
    start = coerce_start_url(raw_url)
    robots = await _load_robots(start)

    def is_allowed(url: str) -> bool:
        return robots is None or robots.can_fetch(USER_AGENT, url)

    if not is_allowed(start):
        raise ScrapeError("robots.txt does not allow reading this site, or could not be checked.")
    try:
        async with async_playwright() as playwright:
            browser = await _launch(playwright)
            try:
                context = await browser.new_context(
                    user_agent=USER_AGENT, viewport=VIEWPORT, device_scale_factor=2
                )
                snapshot = await _read_homepage(context, start, is_allowed)
                await _crawl_nav(context, snapshot, start, is_allowed)
            finally:
                await browser.close()
    except PlaywrightError as exc:
        raise ScrapeError(f"The browser failed while reading the site: {exc}") from exc
    return snapshot
