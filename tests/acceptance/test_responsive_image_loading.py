"""Real-browser priority, loading and bytes for responsive images (issue #216, Task 4).

Fresh contexts per (theme, color, width, DPR) combination; image responses
are collected without swallowing ``body()`` failures. The observation JSON
holds browser/version, theme, light/dark, viewport/DPR, currentSrc,
candidate URLs, rendered/intrinsic sizes, response bytes, HTTP status and
loading/priority.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from acceptance.responsive_image_site import (
    MAIN_WIDTHS,
    ImageRecord,
    ResponseSample,
    build_archive_site,
    build_image_site,
    collect_image_responses,
    decode_all_images,
    measure_images,
    site_page,
    write_observations,
)
from acceptance.server import serve_directory
from fixtures.responsive_image_fixtures import make_test_png
from playwright.sync_api import Browser, BrowserContext, Page, Route, sync_playwright

if TYPE_CHECKING:
    from sphinx.application import Sphinx

LOADING_PAGES = (
    "home",
    "archive",
    "post1",
    "post2",
    "post3",
    "post4",
    "profile",
    "showcase",
)
BYTES_PAGES = ("home", "archive", "post1")


@pytest.fixture(scope="module")
def browser() -> Generator[Browser, None, None]:
    with sync_playwright() as playwright:
        launched = playwright.chromium.launch()
        try:
            yield launched
        finally:
            launched.close()


def _fresh_page(
    browser: Browser,
    base: str,
    start_path: str,
    *,
    width: int,
    height: int = 900,
    dpr: int = 1,
    color: str = "light",
    javascript: bool = True,
) -> tuple[Page, list[ResponseSample], BrowserContext]:
    """Open *start_path* in a fresh context and keep response samples."""
    context = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=dpr,
        color_scheme=color,  # type: ignore[arg-type]
        java_script_enabled=javascript,
    )
    page = context.new_page()
    samples: list[ResponseSample] = []
    collect_image_responses(page, samples)
    page.goto(base + start_path, wait_until="load")
    return page, samples, context


def _close(page: Page, context: BrowserContext) -> None:
    page.close()
    context.close()


def _grid_loading(page: Page, selector: str) -> list[str | None]:
    return [record["loading"] for record in _grid_records(page, selector)]


def _grid_records(page: Page, selector: str) -> list[ImageRecord]:
    slugs = cast(
        list[str | None],
        page.evaluate(
            """(selector) => Array.from(document.querySelectorAll(selector)).map(
                 (card) => card.getAttribute('data-slug'))""",
            selector,
        ),
    )
    by_slug = {record["slug"]: record for record in measure_images(page)}
    return [by_slug[slug] for slug in slugs if slug in by_slug]


def _high_count(page: Page) -> int:
    return sum(1 for record in measure_images(page) if record["fetchpriority"] == "high")


@pytest.mark.browser
@pytest.mark.parametrize("width", MAIN_WIDTHS)
def test_loading_attributes_follow_spec(
    make_sphinx: Callable[..., Sphinx], tmp_path: Path, browser: Browser, width: int
) -> None:
    """Spec §6 roles: one high per page, first-six eager, rest lazy."""
    del tmp_path
    app = build_image_site(make_sphinx, builder="html", theme="maatlog-default", responsive=True)
    with serve_directory(Path(str(app.outdir))) as base:
        for page_name in LOADING_PAGES:
            page, _, context = _fresh_page(browser, base, site_page("html", page_name), width=width)
            try:
                assert _high_count(page) <= 1, page_name
                if page_name == "home":
                    lead = page.locator('[data-maatlog-card-variant="lead"] img')
                    assert lead.count() <= 1
                    if lead.count() == 1:
                        assert lead.first.get_attribute("loading") == "eager"
                        assert lead.first.get_attribute("fetchpriority") == "high"
                    latest_loading = _grid_loading(page, '[data-maatlog-component="latest"] .maatlog-post-card')
                    assert latest_loading[:6] == ["eager"] * min(6, len(latest_loading))
                    assert all(value == "lazy" for value in latest_loading[6:]), latest_loading
                elif page_name == "archive":
                    # Legacy slice: 3 eager featured + 6 eager + 3 lazy remainder.
                    loadings = [record["loading"] for record in measure_images(page) if record["marker"] == "w-v1"]
                    assert loadings == ["eager"] * 9 + ["lazy"] * 3, (page_name, width)
                    assert _high_count(page) == 0, page_name
                elif page_name == "post1":
                    by_class = {record["css_class"]: record for record in measure_images(page)}
                    assert by_class["maatlog-post-top-image-img"]["fetchpriority"] == "high"
                    assert by_class["maatlog-post-hero-image"]["fetchpriority"] == "auto"
                    assert all(record["loading"] == "eager" for record in by_class.values()), page_name
                elif page_name == "post2":
                    (top,) = [record for record in measure_images(page) if record["marker"] == "w-v1"]
                    assert top["css_class"] == "maatlog-post-top-image-img"
                    assert top["fetchpriority"] == "high"
                elif page_name == "post3":
                    (hero,) = [record for record in measure_images(page) if record["marker"] == "w-v1"]
                    assert hero["css_class"] == "maatlog-post-hero-image"
                    assert hero["fetchpriority"] == "high"
                elif page_name == "post4":
                    assert [record for record in measure_images(page) if record["marker"] == "w-v1"] == []
                elif page_name == "profile":
                    for record in measure_images(page):
                        assert record["marker"] == "w-v1", (page_name, record["slug"])
                        assert record["loading"] == "eager", (page_name, record["slug"])
                        assert record["fetchpriority"] != "high", (page_name, record["slug"])
                elif page_name == "showcase":
                    # Directive post-list cards keep the single-src fallback:
                    # no marker, no loading/fetchpriority attributes.
                    showcase_records = measure_images(page)
                    assert len(showcase_records) == 3, page_name
                    for record in showcase_records:
                        assert record["marker"] is None, (page_name, record["slug"])
                        assert record["loading"] is None, (page_name, record["slug"])
                        assert record["fetchpriority"] is None, (page_name, record["slug"])
                        assert record["src"], (page_name, record["slug"])
            finally:
                _close(page, context)


@pytest.mark.browser
@pytest.mark.parametrize("width", MAIN_WIDTHS)
@pytest.mark.parametrize("dpr", [1, 2])
def test_bytes_and_current_src(
    make_sphinx: Callable[..., Sphinx], tmp_path: Path, browser: Browser, width: int, dpr: int
) -> None:
    """Fresh-context DPR runs: currentSrc is a candidate, image URLs stay in-set, no 404."""
    app = build_image_site(make_sphinx, builder="html", theme="maatlog-default", responsive=True)
    with serve_directory(Path(str(app.outdir))) as base:
        observations: list[dict[str, object]] = []
        for page_name in BYTES_PAGES:
            page, samples, context = _fresh_page(browser, base, site_page("html", page_name), width=width, dpr=dpr)
            try:
                decode_all_images(page)
                records = measure_images(page)
                assert records, page_name
                by_url = {sample["url"]: sample for sample in samples}
                for record in records:
                    if record["marker"] != "w-v1":
                        continue
                    candidate_hrefs = _candidate_hrefs(page, record["srcset"] or "")
                    assert record["current_src"] in candidate_hrefs, (page_name, record["slug"])
                    assert record["complete"] and record["natural_width"] > 0
                    current = by_url.get(record["current_src"])
                    assert current is not None, (page_name, record["slug"])
                    assert current["status"] == 200, current
                    assert current["bytes"] > 0, current
                    observations.append(
                        {
                            "browser": "chromium",
                            "browser_version": browser.version,
                            "theme": "maatlog-default",
                            "color_scheme": "light",
                            "viewport": {"width": width, "height": 900},
                            "dpr": dpr,
                            "page": page_name,
                            "slug": record["slug"],
                            "current_src": record["current_src"],
                            "candidates": candidate_hrefs,
                            "rendered": dict(record["rect"]),
                            "intrinsic": {
                                "width": record["natural_width"],
                                "height": record["natural_height"],
                            },
                            "response_bytes": current["bytes"],
                            "http_status": current["status"],
                            "loading": record["loading"],
                            "fetchpriority": record["fetchpriority"],
                        }
                    )
                known_hrefs = [href for record in records for href in _candidate_hrefs(page, record["srcset"] or "")]
                known_srcs = [record["current_src"] for record in records]
                for sample in samples:
                    assert sample["status"] == 200, sample
                    assert sample["url"] in known_hrefs or sample["url"] in known_srcs, sample["url"]
            finally:
                _close(page, context)
    write_observations(tmp_path / "responsive-image-observations.json", observations)


def _candidate_hrefs(page: Page, srcset: str) -> list[str]:
    parts = [part.strip().split()[0] for part in srcset.split(",") if part.strip()]
    return cast(
        list[str],
        page.evaluate(
            "(urls) => urls.map((relative) => new URL(relative, document.baseURI).href)",
            parts,
        ),
    )


@pytest.mark.browser
def test_on_bytes_smaller_than_off(make_sphinx: Callable[..., Sphinx], tmp_path: Path, browser: Browser) -> None:
    """390px/DPR1 default lead: the chosen candidate is smaller than the OFF full image."""
    del tmp_path
    on_app = build_image_site(make_sphinx, builder="html", theme="maatlog-default", responsive=True)
    off_app = build_image_site(make_sphinx, builder="html", theme="maatlog-default", responsive=False)
    with serve_directory(Path(str(on_app.outdir))) as on_base:
        with serve_directory(Path(str(off_app.outdir))) as off_base:
            on_page, on_samples, on_context = _fresh_page(browser, on_base, site_page("html", "home"), width=390)
            try:
                decode_all_images(on_page)
                lead = on_page.locator('[data-maatlog-card-variant="lead"] img')
                assert lead.count() == 1
                current_src = lead.first.evaluate("(img) => img.currentSrc")
                on_bytes = next(sample["bytes"] for sample in on_samples if sample["url"] == current_src)
            finally:
                _close(on_page, on_context)
            off_page, off_samples, off_context = _fresh_page(browser, off_base, site_page("html", "home"), width=390)
            try:
                decode_all_images(off_page)
                lead_img = off_page.locator('[data-maatlog-card-variant="lead"] img')
                assert lead_img.count() == 1
                assert lead_img.first.get_attribute("srcset") is None
                off_src = lead_img.first.evaluate("(img) => img.currentSrc")
                off_bytes = next(sample["bytes"] for sample in off_samples if sample["url"] == off_src)
            finally:
                _close(off_page, off_context)
    assert on_bytes < off_bytes, (on_bytes, off_bytes)
    # Pin the selected candidate without magic numbers: the 390px/DPR1 lead
    # slot (~244px) must resolve to the 480w file, not the full-size image.
    assert off_bytes == len(make_test_png(1600, 900)), off_bytes
    assert on_bytes == len(make_test_png(480, 270)), on_bytes


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1280, 3840])
@pytest.mark.parametrize("height", [720, 900])
def test_viewport_intersection_is_eager(
    make_sphinx: Callable[..., Sphinx], tmp_path: Path, browser: Browser, width: int, height: int
) -> None:
    """Images intersecting the initial viewport are never lazy."""
    del tmp_path
    app = build_image_site(make_sphinx, builder="html", theme="maatlog-default", responsive=True)
    nine = build_archive_site(make_sphinx, builder="html", theme="maatlog-default", responsive=True, post_count=9)
    with serve_directory(Path(str(app.outdir))) as base:
        with serve_directory(Path(str(nine.outdir))) as nine_base:
            _assert_intersection_eager(browser, base, "home", width, height)
            _assert_intersection_eager(browser, base, "archive", width, height)
            if height == 900 and width in (1280, 2560, 3840):
                _assert_intersection_eager(browser, nine_base, "archive", width, height)


def _assert_intersection_eager(browser: Browser, base: str, page_name: str, width: int, height: int) -> None:
    page, _, context = _fresh_page(browser, base, site_page("html", page_name), width=width, height=height)
    try:
        entries = page.evaluate(
            """(viewportHeight) => Array.from(document.querySelectorAll('img')).map((img) => {
                const rect = img.getBoundingClientRect();
                return {
                    loading: img.getAttribute('loading'),
                    slug: img.closest('[data-slug]')?.getAttribute('data-slug'),
                    top: rect.top, bottom: rect.bottom,
                    intersects: rect.top < viewportHeight && rect.bottom > 0,
                };
            })""",
            height,
        )
        for entry in cast(list[dict[str, object]], entries):
            if entry["intersects"]:
                assert entry["loading"] == "eager", (width, height, page_name, entry)
    finally:
        _close(page, context)


@pytest.mark.browser
def test_seventh_grid_images_are_lazy(make_sphinx: Callable[..., Sphinx], tmp_path: Path, browser: Browser) -> None:
    """The 7th+ grid images stay lazy so EAGER-everything cannot regress."""
    del tmp_path
    app = build_image_site(make_sphinx, builder="html", theme="maatlog-default", responsive=True)
    plain = build_image_site(
        make_sphinx,
        builder="html",
        theme="maatlog-default",
        responsive=True,
        featured_count=0,
    )
    nine = build_archive_site(make_sphinx, builder="html", theme="maatlog-default", responsive=True, post_count=9)
    with serve_directory(Path(str(app.outdir))) as base:
        with serve_directory(Path(str(plain.outdir))) as plain_base:
            with serve_directory(Path(str(nine.outdir))) as nine_base:
                page, _, context = _fresh_page(browser, base, site_page("html", "home"), width=1280)
                try:
                    assert page.locator(".maatlog-infinite-sentinel").count() == 0
                    latest = _grid_loading(page, '[data-maatlog-component="latest"] .maatlog-post-card')
                    assert len(latest) == 9, latest
                    assert latest[:6] == ["eager"] * 6
                    assert latest[6:] == ["lazy"] * 3
                finally:
                    _close(page, context)
                legacy_page, _, legacy_context = _fresh_page(browser, base, site_page("html", "archive"), width=1280)
                try:
                    remainder = _grid_loading(legacy_page, '[data-maatlog-component="latest"] .maatlog-post-card')
                    assert len(remainder) == 9, remainder
                    assert remainder[:6] == ["eager"] * 6
                    assert remainder[6:] == ["lazy"] * 3
                finally:
                    _close(legacy_page, legacy_context)
                archive_page, _, archive_context = _fresh_page(
                    browser, plain_base, site_page("html", "archive"), width=1280
                )
                try:
                    loadings = [
                        record["loading"] for record in measure_images(archive_page) if record["marker"] == "w-v1"
                    ]
                    assert len(loadings) == 12, loadings
                    assert loadings[:6] == ["eager"] * 6
                    assert loadings[6:] == ["lazy"] * 6
                finally:
                    _close(archive_page, archive_context)
                nine_page, _, nine_context = _fresh_page(browser, nine_base, site_page("html", "archive"), width=1280)
                try:
                    loadings = [
                        record["loading"] for record in measure_images(nine_page) if record["marker"] == "w-v1"
                    ]
                    assert loadings == ["eager"] * 6 + ["lazy"] * 3, loadings
                finally:
                    _close(nine_page, nine_context)


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1280])
def test_no_js_renders_images(
    make_sphinx: Callable[..., Sphinx], tmp_path: Path, browser: Browser, width: int
) -> None:
    """Without JS the representative images still arrive with bytes."""
    del tmp_path
    app = build_image_site(make_sphinx, builder="html", theme="maatlog-default", responsive=True)
    with serve_directory(Path(str(app.outdir))) as base:
        for page_name in ("home", "post1"):
            page, samples, context = _fresh_page(
                browser, base, site_page("html", page_name), width=width, javascript=False
            )
            try:
                page.wait_for_load_state("load")
                assert page.locator('img[data-maatlog-srcset="w-v1"]').count() >= 1, page_name
                image_samples = [sample for sample in samples if sample["status"] == 200]
                assert image_samples, page_name
                assert all(sample["bytes"] > 0 for sample in image_samples), page_name
            finally:
                _close(page, context)


_LAYOUT_SHIFT_SCRIPT = """window.__imageShifts = [];
   try {
     new PerformanceObserver((list) => {
       for (const entry of list.getEntries()) {
         window.__imageShifts.push(entry.toJSON());
       }
     }).observe({type: 'layout-shift', buffered: true});
   } catch (e) { window.__imageShifts = 'unsupported'; }"""

# The top image is grid auto-placed after the header/body/navigation, so the
# first in-flow element below its box is the Sphinx page footer (the header
# sits above it and the overlay/title siblings are absolutely positioned).
_TOP_BOXES_JS = """() => {
    const rectOf = (element) => {
        const rect = element.getBoundingClientRect();
        return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
    };
    const bySelector = (selector) => rectOf(document.querySelector(selector));
    return {
        wrapper: bySelector('.maatlog-post-top-image'),
        image: bySelector('.maatlog-post-top-image-img'),
        marker: bySelector('div.footer'),
    };
}"""

_CARD_BOXES_JS = """() => {
    const rectOf = (element) => {
        const rect = element.getBoundingClientRect();
        return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
    };
    const img = document.querySelector('[data-maatlog-card-variant="lead"] img');
    return {image: rectOf(img), marker: rectOf(img.nextElementSibling)};
}"""


def _boxes_with_held_images(
    page: Page,
    base: str,
    start_path: str,
    *,
    ready_selector: str,
    decode_selector: str,
    snapshot_js: str,
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """Snapshot boxes with image responses held, release, and re-measure after decode."""
    held: list[Route] = []
    page.route(
        "**/*",
        lambda route, request: held.append(route) if request.resource_type == "image" else route.continue_(),
    )
    page.goto(base + start_path, wait_until="domcontentloaded")
    page.wait_for_selector(ready_selector, state="attached")
    before = cast(dict[str, dict[str, float]], page.evaluate(snapshot_js))
    for route in held:
        route.continue_()
    page.wait_for_function(
        """(selector) => {
            const img = document.querySelector(selector);
            return img && img.complete && img.naturalWidth > 0;
        }""",
        arg=decode_selector,
        timeout=15000,
    )
    after = cast(dict[str, dict[str, float]], page.evaluate(snapshot_js))
    return before, after


def _assert_box_reserved(
    before: dict[str, dict[str, float]], after: dict[str, dict[str, float]], *, boxes: tuple[str, ...]
) -> None:
    for key in boxes:
        for dim in ("width", "height"):
            assert abs(after[key][dim] - before[key][dim]) <= 1, (key, dim, before, after)
    # Non-tautology guard: the marker must sit below the image box, never inside it.
    assert before["marker"]["y"] >= before["image"]["y"] + before["image"]["height"] - 1, before
    assert abs(after["marker"]["y"] - before["marker"]["y"]) <= 1, (before, after)


@pytest.mark.browser
def test_region_reservation(make_sphinx: Callable[..., Sphinx], tmp_path: Path, browser: Browser) -> None:
    """Held image responses keep the reserved box; decode moves nothing by >1px."""
    app = build_image_site(make_sphinx, builder="html", theme="maatlog-default", responsive=True)
    shifts: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    with serve_directory(Path(str(app.outdir))) as base:
        context = browser.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
        try:
            page = context.new_page()
            try:
                page.add_init_script(_LAYOUT_SHIFT_SCRIPT)
                before, after = _boxes_with_held_images(
                    page,
                    base,
                    site_page("html", "post1"),
                    ready_selector=".maatlog-post-top-image-img",
                    decode_selector=".maatlog-post-top-image-img",
                    snapshot_js=_TOP_BOXES_JS,
                )
                _assert_box_reserved(before, after, boxes=("wrapper", "image"))
                records.append({"case": "post-top", "before": before, "after": after})
                raw_shifts = page.evaluate("() => window.__imageShifts")
                if isinstance(raw_shifts, list):
                    shifts = cast(list[dict[str, object]], raw_shifts)
            finally:
                page.close()
            card_page = context.new_page()
            try:
                before, after = _boxes_with_held_images(
                    card_page,
                    base,
                    site_page("html", "home"),
                    ready_selector='[data-maatlog-card-variant="lead"] img',
                    decode_selector='[data-maatlog-card-variant="lead"] img',
                    snapshot_js=_CARD_BOXES_JS,
                )
                _assert_box_reserved(before, after, boxes=("image",))
                marker_tag = card_page.evaluate(
                    """() => {
                        const img = document.querySelector('[data-maatlog-card-variant="lead"] img');
                        return img.nextElementSibling.tagName;
                    }""",
                )
                records.append({"case": "lead-card", "marker_tag": marker_tag, "before": before, "after": after})
            finally:
                card_page.close()
        finally:
            context.close()
    write_observations(
        tmp_path / "responsive-image-observations.json",
        [{"page": "post1/home", "width": 1280, "layout_shifts": shifts, "cases": records}],
    )


@pytest.mark.browser
def test_base_and_dark_spots(make_sphinx: Callable[..., Sphinx], tmp_path: Path, browser: Browser) -> None:
    """Base loading roles match; dark mode keeps priority and decodes."""
    del tmp_path
    base_app = build_image_site(make_sphinx, builder="html", theme="maatlog-base", responsive=True)
    dark_app = build_image_site(make_sphinx, builder="html", theme="maatlog-default", responsive=True)
    with serve_directory(Path(str(base_app.outdir))) as base:
        with serve_directory(Path(str(dark_app.outdir))) as dark_base:
            page, _, context = _fresh_page(browser, base, site_page("html", "home"), width=1280)
            try:
                for record in measure_images(page):
                    if record["marker"] == "w-v1":
                        assert record["sizes"] == "100vw", record["slug"]
                assert _high_count(page) == 1
            finally:
                _close(page, context)
            dark_page, dark_samples, dark_context = _fresh_page(
                browser, dark_base, site_page("html", "home"), width=1280, color="dark"
            )
            try:
                decode_all_images(dark_page)
                assert _high_count(dark_page) == 1
                assert dark_samples, "expected image responses in dark mode"
                assert all(sample["status"] == 200 for sample in dark_samples)
            finally:
                _close(dark_page, dark_context)
