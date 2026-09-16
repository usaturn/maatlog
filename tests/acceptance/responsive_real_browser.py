"""Browser helpers for real responsive-image builds (issue #217, task F/T4).

Every site these helpers touch comes from a real ``python -m sphinx`` build
driven by ``fixtures.responsive_real_build`` -- no HTML or view injection.
The page is observed through Chromium only: images are scrolled into view and
decoded, ``sizes`` is evaluated against the real CSS, and ``currentSrc`` is
compared with the resolved candidate set. Observation dicts are produced
*before* assertions run so a failure still leaves its evidence on disk.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict
from urllib.parse import urljoin, urlsplit

from acceptance.responsive_image_site import (
    ImageRecord,
    assert_slot,
    evaluate_sizes,
    measure_images,
)
from fixtures.responsive_real_build import RealProject, create_project

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Request, Route

#: Marker attribute the base theme emits on every managed ``<img>``.
MANAGED_MARKER: str = "w-v1"
MANAGED_SELECTOR: str = f'img[data-maatlog-srcset="{MANAGED_MARKER}"]'

Color = Literal["light", "dark"]


def page_path(builder: str, docname: str) -> str:
    if docname == "index":
        return "index.html"
    return f"{docname}.html" if builder == "html" else f"{docname}/index.html"


def build_sites(root: Path, *, page_size: int = 20) -> dict[tuple[str, bool], RealProject]:
    sites: dict[tuple[str, bool], RealProject] = {}
    for builder in ("html", "dirhtml"):
        for enabled in (False, True):
            project = create_project(
                root / f"{builder}-{int(enabled)}",
                builder=builder,
                enabled=enabled,
                page_size=page_size,
            )
            result = project.build()
            assert result.returncode == 0, result.stdout + result.stderr
            sites[builder, enabled] = project
    return sites


def new_context(
    browser: Browser,
    *,
    width: int,
    height: int = 900,
    dpr: float = 1,
    color: Color = "light",
) -> BrowserContext:
    """A fresh context for one observation; service workers stay blocked."""
    return browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=dpr,
        color_scheme=color,
        service_workers="block",
    )


@contextmanager
def open_page(context: BrowserContext, url: str) -> Generator[Page, None, None]:
    """Open *url* in a fresh page of *context* and always close it."""
    page = context.new_page()
    try:
        page.goto(url, wait_until="load")
        yield page
    finally:
        page.close()


_DECODE_JS = """async (selector) => {
  const images = [...document.querySelectorAll(selector)].filter((img) => {
    const raw = img.getAttribute('src') || img.currentSrc || '';
    if (!raw) return false;
    try { return new URL(raw, location.href).origin === location.origin; }
    catch { return false; }
  });
  for (const image of images) {
    image.scrollIntoView({block: 'center'});
    await image.decode();
    if (!image.complete || image.naturalWidth <= 0) {
      throw new Error('image did not decode: ' + (image.currentSrc || image.src));
    }
  }
  window.scrollTo(0, 0);
  return images.length;
}"""


def decode_images(page: Page, selector: str) -> int:
    """Scroll same-origin ``img`` matching *selector* into view and decode each.

    Returns how many images were decoded; decode failures propagate so a 404
    or a broken candidate can never pass silently. Remote images are skipped:
    the fixture's ``https://example.test`` placeholder cannot resolve here.
    """
    result = page.evaluate(_DECODE_JS, selector)
    return int(result)


def decode_managed(page: Page) -> None:
    page.evaluate("""async () => {
      const images = [...document.querySelectorAll('img[data-maatlog-srcset="w-v1"]')];
      if (!images.length) throw new Error('no managed images');
      for (const image of images) {
        image.scrollIntoView({block: 'center'});
        await image.decode();
        if (!image.complete || image.naturalWidth <= 0) throw new Error(image.currentSrc);
      }
      window.scrollTo(0, 0);
    }""")


def decode_fallback(page: Page) -> int:
    """Decode every unmanaged same-origin image (fallback ``src`` images)."""
    return decode_images(page, "img:not([data-maatlog-srcset])")


def page_overflow(page: Page) -> float:
    """Horizontal overflow in CSS px; must stay at or below 1."""
    return float(page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth"))


def candidate_urls(page: Page) -> list[str]:
    """Every fetchable URL of every managed image (srcset candidates + src)."""
    raw = page.evaluate(
        "() => [...document.querySelectorAll('img[data-maatlog-srcset=\"w-v1\"]')]"
        ".flatMap((img) => {"
        "const urls = (img.getAttribute('srcset') || '')"
        ".split(',')"
        ".map((part) => part.trim().split(' ')[0])"
        ".filter(Boolean);"
        "const src = img.getAttribute('src');"
        "if (src) urls.push(src);"
        "return urls;"
        "})"
    )
    return [str(url) for url in raw]


def resolved_candidates(record: ImageRecord, page_url: str) -> set[str]:
    """Absolute URLs of every candidate the managed image may pick."""
    urls: set[str] = set()
    if record["src"]:
        urls.add(urljoin(page_url, record["src"]))
    for part in (record["srcset"] or "").split(","):
        tokens = part.strip().split()
        if tokens:
            urls.add(urljoin(page_url, tokens[0]))
    return urls


_GRID_INDEX_JS = """() => [...document.querySelectorAll('img')].map((img) => {
  const card = img.closest('.maatlog-post-card');
  const grid = card && card.closest('.maatlog-post-grid');
  if (!grid) return -1;
  return [...grid.querySelectorAll('.maatlog-post-card')].indexOf(card);
})"""


class GeometryObservation(TypedDict):
    """One managed image's slot measurement, kept for the observation JSON."""

    docname: str
    slug: str | None
    css_class: str
    sizes: str
    evaluated_length: str
    evaluated_sizes: float
    precision: str
    viewport_width: int
    rendered_width: float
    slot_error: float
    current_src: str
    current_src_in_candidates: bool
    complete: bool
    natural_width: int
    natural_height: int
    loading: str | None
    fetchpriority: str | None
    grid_index: int
    in_initial_viewport: bool
    overflow: float


def capture_geometry(
    page: Page,
    *,
    viewport_width: int,
    precision: str,
    docname: str = "",
) -> list[GeometryObservation]:
    """Measure every managed image on the current page; asserts nothing.

    The caller serialises the returned observations first and runs
    ``assert_geometry`` afterwards, so a slot failure still leaves evidence.
    """
    viewport = page.viewport_size or {"width": viewport_width, "height": 900}
    viewport_height = float(viewport["height"])
    overflow = page_overflow(page)
    # _GRID_INDEX_JS maps every <img> in document order, matching measure_images.
    grid_indexes = [int(index) for index in page.evaluate(_GRID_INDEX_JS)]
    observations: list[GeometryObservation] = []
    for record_index, record in enumerate(measure_images(page)):
        if record["marker"] != MANAGED_MARKER:
            continue
        assert record["sizes"] is not None, record["src"]
        evaluated_length, evaluated = evaluate_sizes(page, record["sizes"])
        candidates = resolved_candidates(record, page.url)
        rendered = record["rect"]["width"]
        observations.append(
            GeometryObservation(
                docname=docname,
                slug=record["slug"],
                css_class=record["css_class"],
                sizes=record["sizes"],
                evaluated_length=evaluated_length,
                evaluated_sizes=evaluated,
                precision=precision,
                viewport_width=viewport_width,
                rendered_width=rendered,
                slot_error=abs(evaluated - rendered),
                current_src=record["current_src"],
                current_src_in_candidates=record["current_src"] in candidates,
                complete=record["complete"],
                natural_width=record["natural_width"],
                natural_height=record["natural_height"],
                loading=record["loading"],
                fetchpriority=record["fetchpriority"],
                grid_index=grid_indexes[record_index],
                in_initial_viewport=(
                    record["rect"]["y"] + record["rect"]["height"] > 0 and record["rect"]["y"] < viewport_height
                ),
                overflow=overflow,
            )
        )
    return observations


def assert_geometry(observation: GeometryObservation) -> None:
    """Slot/decode/candidate gate for one captured observation."""
    assert observation["complete"] and observation["natural_width"] > 0, observation["current_src"]
    assert observation["evaluated_sizes"] > 0, observation["sizes"]
    assert observation["current_src_in_candidates"], observation["current_src"]
    assert_slot(
        {
            "rendered_width": observation["rendered_width"],
            "evaluated_sizes": observation["evaluated_sizes"],
            "precision": observation["precision"],
            "viewport_width": observation["viewport_width"],
        }
    )


_CARD_STATE_JS = """() => [...document.querySelectorAll('.maatlog-post-card')].map((card) => {
  const img = card.querySelector('img[data-maatlog-srcset]');
  return {
    slug: card.getAttribute('data-slug'),
    variant: card.getAttribute('data-maatlog-card-variant') || '',
    grid_index: card.closest('.maatlog-post-grid') === null
      ? -1
      : [...card.closest('.maatlog-post-grid').querySelectorAll('.maatlog-post-card')].indexOf(card),
    has_image: img !== null,
    loading: img ? img.getAttribute('loading') : null,
    fetchpriority: img ? img.getAttribute('fetchpriority') : null,
  };
})"""


class CardState(TypedDict):
    slug: str | None
    variant: str
    grid_index: int
    has_image: bool
    loading: str | None
    fetchpriority: str | None


def card_states(page: Page) -> list[CardState]:
    """Per-card managed-image state in document order (featured + grids)."""
    return [CardState(**entry) for entry in page.evaluate(_CARD_STATE_JS)]


class ManagedState(TypedDict):
    css_class: str
    loading: str | None
    fetchpriority: str | None
    top: float
    bottom: float


def managed_states(page: Page) -> list[ManagedState]:
    """Class/loading/fetchpriority/viewport offsets of every managed image."""
    raw = page.evaluate(
        "() => [...document.querySelectorAll('img[data-maatlog-srcset=\"w-v1\"]')]"
        ".map((img) => ({"
        "css_class: img.getAttribute('class') || '',"
        "loading: img.getAttribute('loading'),"
        "fetchpriority: img.getAttribute('fetchpriority'),"
        "top: img.getBoundingClientRect().top,"
        "bottom: img.getBoundingClientRect().bottom,"
        "}))"
    )
    return [ManagedState(**entry) for entry in raw]


# ---------------------------------------------------------------------------
# Infinite Scroll helpers (real generated cards only).
# ---------------------------------------------------------------------------

#: Records every ``maatlog:content-added`` event (fetched URL + appended slugs).
COLLECT_APPENDS_JS = """window.__maatlogAppends = [];
document.addEventListener('maatlog:content-added', (event) => {
  window.__maatlogAppends.push({
    url: event.detail.url,
    slugs: event.detail.cards.map((card) => card.getAttribute('data-slug')),
  });
});"""


def card_slugs(page: Page) -> list[str | None]:
    return list(
        page.evaluate(
            "() => [...document.querySelectorAll('.maatlog-post-card')].map((card) => card.getAttribute('data-slug'))"
        )
    )


class AppendedBatch(TypedDict):
    """One ``maatlog:content-added`` event: the fetched page URL + card slugs."""

    url: str
    slugs: list[str | None]


def appended_batches(page: Page) -> list[AppendedBatch]:
    """The ``maatlog:content-added`` events seen so far (url + slugs)."""
    raw = page.evaluate("() => window.__maatlogAppends")
    return [AppendedBatch(url=str(entry["url"]), slugs=list(entry["slugs"])) for entry in raw]


def fetched_page_file(outdir: Path, fetched_url: str) -> Path:
    """Map a fetched archive-page URL back to its file inside *outdir*."""
    path = urlsplit(fetched_url).path.lstrip("/")
    if path.endswith("/"):
        path += "index.html"
    target = (outdir / path).resolve()
    assert target.is_relative_to(outdir.resolve()), fetched_url
    assert target.is_file(), fetched_url
    return target


class _CardImages(HTMLParser):
    """Map ``data-slug`` article cards to their first managed ``<img>`` attrs."""

    def __init__(self) -> None:
        super().__init__()
        self.cards: dict[str, dict[str, str]] = {}
        self._slug: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        if tag == "article" and "maatlog-post-card" in attr.get("class", ""):
            self._slug = attr.get("data-slug")
        elif tag == "img" and self._slug is not None and attr.get("data-maatlog-srcset"):
            self.cards.setdefault(self._slug, attr)

    def handle_endtag(self, tag: str) -> None:
        if tag == "article":
            self._slug = None


def card_images_in(page_file: Path) -> dict[str, dict[str, str]]:
    """Managed ``<img>`` attributes of every card on one emitted page."""
    parser = _CardImages()
    parser.feed(page_file.read_text(encoding="utf-8"))
    return parser.cards


def expected_srcset(srcset: str, page_url: str) -> str:
    """Resolve each ``w`` candidate of *srcset* against *page_url*."""
    parts: list[str] = []
    for part in srcset.split(","):
        tokens = part.strip().split()
        if tokens:
            parts.append(" ".join([urljoin(page_url, tokens[0]), *tokens[1:]]))
    return ", ".join(parts)


def local_candidate_basename(url: str) -> str:
    """Basename of an (already absolute) candidate URL."""
    return urlsplit(url).path.rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------
# Task 5: real transfer bytes, image-hold reservation and LCP observation.
#
# Byte measurement never goes through network routes and never substitutes
# candidate files: ``record_transfers`` only observes what Chromium really
# fetched. ``hold_images`` routes are used solely in the reserved-box tests,
# where no bytes are measured.
# ---------------------------------------------------------------------------


class ImageTransfer(TypedDict):
    """One finished image request: encoded body + headers + decoded length."""

    url: str
    status: int
    body_bytes: int
    header_bytes: int
    decoded_body_bytes: int


class ImageTransferFailure(TypedDict):
    """One ``requestfailed`` image request."""

    url: str
    failure: str


class TransferSamples(list[ImageTransfer]):
    """``record_transfers`` target.

    Finished requests land in the list itself so byte sums stay clean;
    ``requestfailed`` entries land in ``failures`` and record-time
    exceptions in ``record_errors`` -- both persisted and asserted by the
    caller, never silently swallowed. ``in_flight`` tracks image requests
    that have started but not finished, for quiescence waits.
    """

    def __init__(self) -> None:
        super().__init__()
        self.failures: list[ImageTransferFailure] = []
        self.record_errors: list[str] = []
        self.in_flight: set[Request] = set()


def record_transfers(page: Page, samples: TransferSamples) -> None:
    """Record real encoded bytes for every image request on *page*.

    ``requestfinished`` -> ``request.sizes()`` ``responseBodySize`` (encoded)
    + ``responseHeadersSize`` + decoded body length + URL + status.
    ``requestfailed`` -> ``samples.failures`` (callers must treat it as a
    test failure). Recording errors are appended to ``samples.record_errors``
    instead of being raised inside the event handler, where a raise would
    only reach Playwright's dispatcher; the caller persists then asserts.
    """

    def started(request: Request) -> None:
        if request.resource_type == "image":
            samples.in_flight.add(request)

    def finished(request: Request) -> None:
        if request.resource_type != "image":
            return
        samples.in_flight.discard(request)
        try:
            response = request.response()
            assert response is not None, request.url
            sizes = request.sizes()
            samples.append(
                ImageTransfer(
                    url=request.url,
                    status=response.status,
                    body_bytes=sizes["responseBodySize"],
                    header_bytes=sizes["responseHeadersSize"],
                    decoded_body_bytes=len(response.body()),
                )
            )
        except Exception as exc:
            samples.record_errors.append(f"{request.url}: {exc!r}")

    def failed(request: Request) -> None:
        if request.resource_type != "image":
            return
        samples.in_flight.discard(request)
        samples.failures.append(ImageTransferFailure(url=request.url, failure=request.failure or "unknown"))

    page.on("request", started)
    page.on("requestfinished", finished)
    page.on("requestfailed", failed)


def settle_transfers(
    page: Page,
    samples: TransferSamples,
    *,
    stable_ms: float = 200,
    timeout_ms: float = 15000,
) -> bool:
    """Wait until no image request is in flight and the sample list has not
    grown for *stable_ms*. ``wait_for_timeout`` slices keep Playwright's
    event processing moving. Returns False on timeout."""
    deadline = time.monotonic() + timeout_ms / 1000
    last_count = -1
    last_change = time.monotonic()
    while time.monotonic() < deadline:
        page.wait_for_timeout(50)
        if samples.in_flight or len(samples) != last_count:
            last_count = len(samples)
            last_change = time.monotonic()
            continue
        if (time.monotonic() - last_change) * 1000 >= stable_ms:
            return True
    return False


_DECODE_IN_VIEW_JS = """async () => {
  const images = [...document.querySelectorAll('img')].filter((img) => {
    const box = img.getBoundingClientRect();
    return box.bottom > 0 && box.top < window.innerHeight;
  });
  const results = [];
  for (const image of images) {
    try {
      await image.decode();
      results.push({current_src: image.currentSrc || image.src,
        complete: image.complete, natural_width: image.naturalWidth});
    } catch (exc) {
      results.push({current_src: image.currentSrc || image.src, error: String(exc)});
    }
  }
  return results;
}"""


def decode_in_viewport(page: Page) -> list[dict[str, object]]:
    """Decode every ``img`` intersecting the viewport; no scrolling.

    Returns per-image outcome dicts; decode rejections are recorded in the
    entries (``error`` key) so the caller can persist then assert.
    """
    return [dict(entry) for entry in page.evaluate(_DECODE_IN_VIEW_JS)]


class ImageState(TypedDict):
    """Snapshot of one ``img``: identity, fetch state, viewport position."""

    css_class: str
    marker: str | None
    slug: str | None
    variant: str | None
    grid_index: int
    src: str | None
    current_src: str
    loading: str | None
    fetchpriority: str | None
    complete: bool
    natural_width: int
    natural_height: int
    top: float
    bottom: float
    width: float
    height: float
    in_viewport: bool


_IMAGE_STATES_JS = """() => [...document.querySelectorAll('img')].map((img) => {
  const box = img.getBoundingClientRect();
  const card = img.closest('.maatlog-post-card');
  const grid = card && card.closest('.maatlog-post-grid');
  return {
    css_class: img.getAttribute('class') || '',
    marker: img.getAttribute('data-maatlog-srcset'),
    slug: card ? card.getAttribute('data-slug') : null,
    variant: card ? (card.getAttribute('data-maatlog-card-variant') || 'card') : null,
    grid_index: grid ? [...grid.querySelectorAll('.maatlog-post-card')].indexOf(card) : -1,
    src: img.getAttribute('src'),
    current_src: img.currentSrc,
    loading: img.getAttribute('loading'),
    fetchpriority: img.getAttribute('fetchpriority'),
    complete: img.complete,
    natural_width: img.naturalWidth,
    natural_height: img.naturalHeight,
    top: box.top,
    bottom: box.bottom,
    width: box.width,
    height: box.height,
    in_viewport: box.bottom > 0 && box.top < window.innerHeight,
  };
})"""


def image_states(page: Page) -> list[ImageState]:
    """Snapshot every ``img`` on the page in document order."""
    return [ImageState(**entry) for entry in page.evaluate(_IMAGE_STATES_JS)]


def _hold_matching(page: Page, hold: Callable[[Request], bool]) -> Callable[[], None]:
    """Queue routes whose request satisfies *hold*; the result releases them.

    The route only queues matching requests; DOM, CSS and fonts keep loading
    so the reserved layout can stabilize while the pixels stay absent.
    """
    pending: list[Route] = []
    released = False

    def route_image(route: Route) -> None:
        if not released and hold(route.request):
            pending.append(route)
        else:
            route.continue_()

    def release() -> None:
        nonlocal released
        released = True
        while pending:
            pending.pop(0).continue_()

    page.route("**/*", route_image)
    return release


def hold_images(page: Page) -> Callable[[], None]:
    """Hold every image response until the returned callable releases them."""
    return _hold_matching(page, lambda request: request.resource_type == "image")


def hold_variant_images(page: Page) -> Callable[[], None]:
    """Hold only managed-variant (``/_images/maatlog/``) image responses.

    Used for pages that mix managed images with an unreserved plain ``<img>``
    (``posts/p01``'s pinned unmanaged body image): the fallback loads before
    the release window opens, so the measured interval only covers the
    managed reservation instead of an unrelated unreserved growth.
    """
    return _hold_matching(
        page,
        lambda request: request.resource_type == "image" and "/_images/maatlog/" in urlsplit(request.url).path,
    )


#: layout-shift + largest-contentful-paint observers, installed via
#: ``add_init_script`` before navigation. ``sources`` entries keep
#: tag/id/class and previous/current rects -- ``entry.toJSON()`` alone
#: would lose the DOM attribution.
PERFORMANCE_OBSERVER_JS = """window.__ri = {shifts: [], lcp: [], release: null};
new PerformanceObserver(list => {
  for (const entry of list.getEntries()) {
    window.__ri.shifts.push({
      time: entry.startTime, value: entry.value, recentInput: entry.hadRecentInput,
      sources: (entry.sources || []).map(source => ({
        tag: source.node && source.node.tagName,
        id: source.node && source.node.id,
        cls: source.node && source.node.className,
        previous: source.previousRect, current: source.currentRect
      }))
    });
  }
}).observe({type: 'layout-shift', buffered: true});
new PerformanceObserver(list => {
  for (const entry of list.getEntries()) {
    window.__ri.lcp.push({
      time: entry.startTime, url: entry.url, size: entry.size,
      tag: entry.element && entry.element.tagName,
      loading: entry.element && entry.element.getAttribute('loading')
    });
  }
}).observe({type: 'largest-contentful-paint', buffered: true});"""


class ShiftSource(TypedDict):
    tag: str | None
    id: str | None
    cls: object
    previous: object
    current: object


class LayoutShiftEvent(TypedDict):
    time: float
    value: float
    recentInput: bool
    sources: list[ShiftSource]


class LcpEvent(TypedDict):
    time: float
    url: str | None
    size: float
    tag: str | None
    loading: str | None


class RiEvents(TypedDict):
    """Contents of ``window.__ri`` written by ``PERFORMANCE_OBSERVER_JS``."""

    shifts: list[LayoutShiftEvent]
    lcp: list[LcpEvent]
    release: float | None


def ri_events(page: Page) -> RiEvents:
    """Read ``window.__ri`` back. Fails if the observer was never installed."""
    raw = page.evaluate("() => window.__ri")
    assert raw is not None, "PERFORMANCE_OBSERVER_JS was not installed"
    return RiEvents(shifts=list(raw["shifts"]), lcp=list(raw["lcp"]), release=raw["release"])


def observer_types(page: Page) -> list[str]:
    """``PerformanceObserver.supportedEntryTypes`` -- Chromium must support both."""
    return [str(entry) for entry in page.evaluate("() => PerformanceObserver.supportedEntryTypes")]


_LAYOUT_STABLE_JS = """async () => {
  const pending = [...document.querySelectorAll('link[rel="stylesheet"]')].filter(
    (link) => link.sheet === null && (!link.media || link.media === '' || matchMedia(link.media).matches)
  );
  if (pending.length) return false;
  await document.fonts.ready;
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  return document.fonts.status === 'loaded';
}"""


def wait_layout_stable(page: Page, *, timeout_ms: float = 10000) -> bool:
    """Wait for stylesheets + fonts + two frames; images may still be held."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if page.evaluate(_LAYOUT_STABLE_JS):
            return True
        page.wait_for_timeout(50)
    return False


_RESERVED_BOX_JS = """(selector) => {
  const element = document.querySelector(selector);
  if (!element) throw new Error('not found: ' + selector);
  const box = element.getBoundingClientRect();
  const img = element instanceof HTMLImageElement ? element : null;
  return {x: box.x, y: box.y, width: box.width, height: box.height,
    complete: img ? img.complete : null,
    naturalWidth: img ? img.naturalWidth : null,
    currentSrc: img ? img.currentSrc : null};
}"""


def measure_reserved_boxes(page: Page, selector: str) -> dict[str, object]:
    """Bounding box (+ load state for ``img``) of the first *selector* match.

    Works for downstream marker elements too: non-image elements report
    ``complete``/``naturalWidth``/``currentSrc`` as null.
    """
    return dict(page.evaluate(_RESERVED_BOX_JS, selector))


_DECODE_TARGET_JS = """async (selector) => {
  const image = document.querySelector(selector);
  if (!image) throw new Error('not found: ' + selector);
  await image.decode();
  return {complete: image.complete, naturalWidth: image.naturalWidth,
    currentSrc: image.currentSrc};
}"""


def decode_target(page: Page, selector: str) -> dict[str, object]:
    """``img.decode()`` the first *selector* match; rejections propagate."""
    return dict(page.evaluate(_DECODE_TARGET_JS, selector))


def two_frames(page: Page) -> None:
    """Resolve after two animation frames (post-release layout settle)."""
    page.evaluate("() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))")


def served_file(outdir: Path, url: str) -> Path:
    """Map a served URL back to its file inside *outdir*."""
    target = (outdir / urlsplit(url).path.lstrip("/")).resolve()
    assert target.is_relative_to(outdir.resolve()), url
    assert target.is_file(), url
    return target
