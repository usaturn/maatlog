"""Real-browser priority, loading and bytes for responsive images (issue #216, Task 4).

Fresh contexts per (theme, color, width, DPR) combination; image responses
are collected without swallowing ``body()`` failures. The observation JSON
holds browser/version, theme, light/dark, viewport/DPR, currentSrc,
candidate URLs, rendered/intrinsic sizes, response bytes, HTTP status and
loading/priority.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from acceptance.built_sites import BuiltSite, BuiltSites
from acceptance.responsive_image_site import (
    ResponseSample,
    build_archive_site,
    build_image_site,
    collect_image_responses,
    decode_all_images,
    measure_images,
    site_page,
    write_observations,
)
from fixtures.responsive_image_fixtures import make_test_png
from playwright.sync_api import Browser, BrowserContext, Page, Route

BYTES_PAGES = ("home", "archive", "post1")


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


def _high_count(page: Page) -> int:
    return sum(1 for record in measure_images(page) if record["fetchpriority"] == "high")


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1280, 3840])
@pytest.mark.parametrize("dpr", [1, 2])
def test_bytes_and_current_src(
    built_sites: BuiltSites, tmp_path: Path, shared_browser: Browser, width: int, dpr: int
) -> None:
    """Fresh-context DPR runs: currentSrc is a candidate, image URLs stay in-set, no 404.

    The six main widths are covered on the real builds by
    test_responsive_real_performance.py::test_transfer_observation_matrix;
    here the narrow/medium/widest widths keep the injected-view site's own
    candidate selection under both densities.
    """
    built = build_image_site(built_sites, builder="html", theme="maatlog-default", responsive=True)
    base = built.base_url
    observations: list[dict[str, object]] = []
    for page_name in BYTES_PAGES:
        page, samples, context = _fresh_page(
            shared_browser, base, site_page(built.builder, page_name), width=width, dpr=dpr
        )
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
                if dpr == 2:
                    # At DPR 2 the chosen candidate must carry roughly twice the
                    # CSS pixels of the slot; a chopped candidate list fails
                    # this. natural_width is density-normalized back to the
                    # slot, so read the w descriptor off srcset instead -- and
                    # only where the source (the HTML width attr) has the
                    # pixels for it.
                    source_width = int(record["width_attr"] or "0")
                    if source_width >= record["rect"]["width"] * 1.5:
                        chosen_w = _candidate_widths(page, record["srcset"] or "")[record["current_src"]]
                        assert chosen_w >= record["rect"]["width"] * 1.5, (page_name, record["slug"])
                assert record["complete"] and record["natural_width"] > 0
                current = by_url.get(record["current_src"])
                assert current is not None, (page_name, record["slug"])
                assert current["status"] == 200, current
                assert current["bytes"] > 0, current
                observations.append(
                    {
                        "browser": "chromium",
                        "browser_version": shared_browser.version,
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


def _candidate_widths(page: Page, srcset: str) -> dict[str, int]:
    """Map each resolved candidate URL to its ``w`` descriptor width."""
    descriptors: list[tuple[str, int]] = []
    for part in srcset.split(","):
        tokens = part.strip().split()
        if len(tokens) == 2 and tokens[1].endswith("w"):
            descriptors.append((tokens[0], int(tokens[1][:-1])))
    resolved = cast(
        list[str],
        page.evaluate(
            "(urls) => urls.map((relative) => new URL(relative, document.baseURI).href)",
            [raw_url for raw_url, _ in descriptors],
        ),
    )
    return {url: width for url, (_, width) in zip(resolved, descriptors, strict=True)}


@pytest.mark.browser
def test_on_bytes_smaller_than_off(built_sites: BuiltSites, shared_browser: Browser) -> None:
    """390px/DPR1 default lead: the chosen candidate is smaller than the OFF full image."""
    on_built = build_image_site(built_sites, builder="html", theme="maatlog-default", responsive=True)
    off_built = build_image_site(built_sites, builder="html", theme="maatlog-default", responsive=False)
    on_page, on_samples, on_context = _fresh_page(
        shared_browser, on_built.base_url, site_page(on_built.builder, "home"), width=390
    )
    try:
        decode_all_images(on_page)
        lead = on_page.locator('[data-maatlog-card-variant="lead"] img')
        assert lead.count() == 1
        current_src = lead.first.evaluate("(img) => img.currentSrc")
        on_bytes = next(sample["bytes"] for sample in on_samples if sample["url"] == current_src)
    finally:
        _close(on_page, on_context)
    off_page, off_samples, off_context = _fresh_page(
        shared_browser, off_built.base_url, site_page(off_built.builder, "home"), width=390
    )
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
    built_sites: BuiltSites, shared_browser: Browser, width: int, height: int
) -> None:
    """Images intersecting the initial viewport are never lazy."""
    built = build_image_site(built_sites, builder="html", theme="maatlog-default", responsive=True)
    nine = build_archive_site(built_sites, builder="html", theme="maatlog-default", responsive=True, post_count=9)
    _assert_intersection_eager(shared_browser, built, "home", width, height)
    _assert_intersection_eager(shared_browser, built, "archive", width, height)
    if height == 900 and width in (1280, 2560, 3840):
        _assert_intersection_eager(shared_browser, nine, "archive", width, height)


def _assert_intersection_eager(browser: Browser, built: BuiltSite, page_name: str, width: int, height: int) -> None:
    page, _, context = _fresh_page(
        browser, built.base_url, site_page(built.builder, page_name), width=width, height=height
    )
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
@pytest.mark.parametrize("width", [390, 1280])
def test_no_js_renders_images(built_sites: BuiltSites, shared_browser: Browser, width: int) -> None:
    """Without JS the representative images still arrive with bytes."""
    built = build_image_site(built_sites, builder="html", theme="maatlog-default", responsive=True)
    for page_name in ("home", "post1"):
        page, samples, context = _fresh_page(
            shared_browser, built.base_url, site_page(built.builder, page_name), width=width, javascript=False
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
def test_region_reservation(built_sites: BuiltSites, tmp_path: Path, shared_browser: Browser) -> None:
    """Held image responses keep the reserved box; decode moves nothing by >1px."""
    built = build_image_site(built_sites, builder="html", theme="maatlog-default", responsive=True)
    base = built.base_url
    shifts: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    context = shared_browser.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
    try:
        page = context.new_page()
        try:
            page.add_init_script(_LAYOUT_SHIFT_SCRIPT)
            before, after = _boxes_with_held_images(
                page,
                base,
                site_page(built.builder, "post1"),
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
                site_page(built.builder, "home"),
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
def test_base_and_dark_spots(built_sites: BuiltSites, shared_browser: Browser) -> None:
    """Base loading roles match; dark mode keeps priority and decodes."""
    base_built = build_image_site(built_sites, builder="html", theme="maatlog-base", responsive=True)
    dark_built = build_image_site(built_sites, builder="html", theme="maatlog-default", responsive=True)
    page, _, context = _fresh_page(
        shared_browser, base_built.base_url, site_page(base_built.builder, "home"), width=1280
    )
    try:
        for record in measure_images(page):
            if record["marker"] == "w-v1":
                assert record["sizes"] == "100vw", record["slug"]
        assert _high_count(page) == 1
    finally:
        _close(page, context)
    dark_page, dark_samples, dark_context = _fresh_page(
        shared_browser, dark_built.base_url, site_page(dark_built.builder, "home"), width=1280, color="dark"
    )
    try:
        decode_all_images(dark_page)
        assert _high_count(dark_page) == 1
        assert dark_samples, "expected image responses in dark mode"
        assert all(sample["status"] == 200 for sample in dark_samples)
    finally:
        _close(dark_page, dark_context)
