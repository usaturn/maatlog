"""Infinite Scroll against real generated archive cards (issue #217, task F/T4).

The scroll sites are real ``python -m sphinx`` ON builds with
``maatlog_page_size=4``; the appended cards are the ones the real archive
generated for pages 2 and 3, fetched through the real runtime. Candidate
srcset URLs are checked against the fetched page's own URL (``response.url``
as reported by the ``maatlog:content-added`` event), never treated as a raw
string.
"""

from __future__ import annotations

import re
from collections.abc import Generator
from pathlib import Path
from typing import Final
from urllib.parse import urljoin, urlsplit

import pytest
from acceptance.responsive_image_site import (
    ResponseSample,
    collect_image_responses,
    write_observations,
)
from acceptance.responsive_real_browser import (
    COLLECT_APPENDS_JS,
    MANAGED_SELECTOR,
    appended_batches,
    build_sites,
    candidate_urls,
    card_images_in,
    card_slugs,
    decode_managed,
    expected_srcset,
    fetched_page_file,
    local_candidate_basename,
    new_context,
    page_path,
)
from acceptance.server import serve_directory
from fixtures.responsive_real_build import RealProject, create_project
from playwright.sync_api import Browser, Page, Request, Route, sync_playwright

#: Narrow, short viewport: the four cards of a ``page_size=4`` archive page
#: stack tall enough that the JS-created sentinel starts below
#: ``innerHeight + rootMargin(400px)`` and no autofill can fire before the
#: test scrolls (measured sentinel top ~= 1255px vs threshold 880px).
SCROLL_VIEWPORT: Final = {"width": 390, "height": 480}

#: A basename a browser can fetch without percent-escapes or delimiters.
_URI_SAFE_BASENAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


@pytest.fixture(scope="module")
def browser() -> Generator[Browser, None, None]:
    with sync_playwright() as playwright:
        launched = playwright.chromium.launch()
        try:
            yield launched
        finally:
            launched.close()


@pytest.fixture(scope="module")
def scroll_sites(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, bool], RealProject]:
    """Five-page archives (18 posts / page_size=4), one per builder."""
    return build_sites(tmp_path_factory.mktemp("real-scroll-sites"), page_size=4)


def _block_pages_beyond_three(page: Page, base: str) -> None:
    """Abort archive fetches for page 4+ so chained autofill cannot overshoot."""

    def gate(route: Route, request: Request) -> None:
        if request.resource_type in {"fetch", "xhr"} and re.search(r"/page/[4-9]", request.url):
            route.abort()
        else:
            route.continue_()

    page.route(f"{base}nested/blog/page/**", gate)


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_real_infinite_scroll_pages_two_and_three(
    scroll_sites: dict[tuple[str, bool], RealProject],
    tmp_path: Path,
    browser: Browser,
    builder: str,
) -> None:
    """Cards from real pages 2 and 3 resolve candidates against response.url."""
    project = scroll_sites[builder, True]
    entry = page_path(builder, "nested/blog")
    samples: list[ResponseSample] = []
    observations: list[dict[str, object]] = []
    all_slugs: list[str | None] = []
    high_count = -1
    out = tmp_path / "scroll-observations.json"
    with serve_directory(project.outdir) as base:
        context = new_context(browser, width=SCROLL_VIEWPORT["width"], height=SCROLL_VIEWPORT["height"])
        try:
            page = context.new_page()
            collect_image_responses(page, samples)
            page.add_init_script(COLLECT_APPENDS_JS)
            _block_pages_beyond_three(page, base)
            page.goto(base + entry, wait_until="load")
            page.wait_for_selector(".maatlog-infinite-sentinel", state="attached")
            for expected_page in (2, 3):
                before = page.locator(".maatlog-post-card").count()
                next_href = page.locator("a.maatlog-pagination-next").get_attribute("href")
                batch_entry: dict[str, object] = {
                    "builder": builder,
                    "page": expected_page,
                    "cards_before": before,
                    "next_href": next_href,
                }
                observations.append(batch_entry)
                write_observations(out, observations)
                assert next_href, f"page {expected_page} next link"
                page.locator(".maatlog-infinite-sentinel").scroll_into_view_if_needed()
                page.wait_for_function(
                    "(n) => document.querySelectorAll('.maatlog-post-card').length > n",
                    arg=before,
                )
                batches = appended_batches(page)
                batch = batches[expected_page - 2] if len(batches) >= expected_page - 1 else None
                fetched_url = batch["url"] if batch else None
                batch_entry["batch_count"] = len(batches)
                batch_entry["fetched_url"] = fetched_url
                batch_entry["expected_fetched"] = urljoin(base + entry, next_href)
                batch_entry["appended_slugs"] = batch["slugs"] if batch else []
                if batch is None or fetched_url is None:
                    batch_entry["images"] = []
                    write_observations(out, observations)
                    pytest.fail(f"page {expected_page} produced no append batch")
                emitted = card_images_in(fetched_page_file(project.outdir, fetched_url))
                appended: list[dict[str, object]] = []
                for slug in [s for s in batch["slugs"] if s is not None]:
                    original = emitted.get(slug)
                    image = page.locator(f'[data-slug="{slug}"] {MANAGED_SELECTOR}')
                    appended.append(
                        {
                            "slug": slug,
                            "emitted_srcset": original["srcset"] if original else None,
                            "emitted_src": original["src"] if original else None,
                            "expected_srcset": expected_srcset(original["srcset"], fetched_url) if original else None,
                            "expected_src": urljoin(fetched_url, original["src"]) if original else None,
                            "actual_srcset": image.get_attribute("srcset"),
                            "actual_src": image.get_attribute("src"),
                            "actual_fetchpriority": image.get_attribute("fetchpriority"),
                        }
                    )
                batch_entry["images"] = appended
                write_observations(out, observations)
                assert fetched_url == batch_entry["expected_fetched"]
                assert appended, f"page {expected_page} appended nothing"
                for image_entry in appended:
                    slug = image_entry["slug"]
                    assert image_entry["emitted_srcset"] is not None, f"{slug} not on {fetched_url}"
                    assert image_entry["actual_srcset"] == image_entry["expected_srcset"], slug
                    assert image_entry["actual_src"] == image_entry["expected_src"], slug
                    assert image_entry["actual_fetchpriority"] != "high", slug
            all_slugs = card_slugs(page)
            high_count = page.locator('img[fetchpriority="high"]').count()
            observations.append(
                {
                    "summary": "final",
                    "all_slugs": all_slugs,
                    "high_count": high_count,
                    "sample_statuses": [{"url": s["url"], "status": s["status"]} for s in samples],
                }
            )
            write_observations(out, observations)
            decode_managed(page)
            observations[-1]["sample_statuses"] = [{"url": s["url"], "status": s["status"]} for s in samples]
            write_observations(out, observations)
        finally:
            context.close()
    assert len(all_slugs) == len(set(all_slugs)), "duplicate card slugs after appends"
    assert high_count <= 1
    for sample in samples:
        assert sample["status"] == 200, sample["url"]


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_archive_pagination_without_js(
    scroll_sites: dict[tuple[str, bool], RealProject],
    tmp_path: Path,
    browser: Browser,
    builder: str,
) -> None:
    """Without JavaScript the archive paginates by plain links and decodes."""
    project = scroll_sites[builder, True]
    entry = page_path(builder, "nested/blog")
    observations: list[dict[str, object]] = []
    first_counts: dict[str, int] = {}
    second_counts: dict[str, int] = {}
    out = tmp_path / "pagination-nojs.json"
    with serve_directory(project.outdir) as base:
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            java_script_enabled=False,
            service_workers="block",
        )
        try:
            page = context.new_page()
            page.goto(base + entry, wait_until="load")
            first_counts = {
                "sentinel_count": page.locator(".maatlog-infinite-sentinel").count(),
                "card_count": page.locator(".maatlog-post-card").count(),
                "managed_count": page.locator(MANAGED_SELECTOR).count(),
            }
            observations.append(
                {
                    "builder": builder,
                    "page": 1,
                    **first_counts,
                    "next_href": page.locator("a.maatlog-pagination-next").get_attribute("href"),
                }
            )
            write_observations(out, observations)
            decode_managed(page)
            next_href = observations[0]["next_href"]
            assert isinstance(next_href, str) and next_href != "", "page 1 next link"
            page.goto(urljoin(base + entry, next_href), wait_until="load")
            second_counts = {
                "card_count": page.locator(".maatlog-post-card").count(),
                "managed_count": page.locator(MANAGED_SELECTOR).count(),
                "high_count": page.locator('img[fetchpriority="high"]').count(),
            }
            observations.append({"builder": builder, "page": 2, **second_counts})
            write_observations(out, observations)
            decode_managed(page)
        finally:
            context.close()
    assert first_counts["sentinel_count"] == 0
    assert first_counts["card_count"] == 4
    assert second_counts["card_count"] == 4
    assert second_counts["managed_count"] > 0
    assert second_counts["high_count"] == 0


@pytest.mark.browser
@pytest.mark.parametrize("source_name", ["my photo.png", "a,b.png", "日本語.png", "100%.png"])
def test_generated_basenames_are_uri_safe(tmp_path: Path, browser: Browser, source_name: str) -> None:
    """Whitespace/comma/percent/non-ASCII sources get safe public basenames."""
    project = create_project(
        tmp_path / "site",
        builder="html",
        enabled=True,
        page_size=20,
        source_name=source_name,
    )
    result = project.build()
    assert result.returncode == 0, result.stdout + result.stderr
    samples: list[ResponseSample] = []
    entries: list[dict[str, object]] = []
    out = tmp_path / "basenames.json"
    with serve_directory(project.outdir) as base:
        context = new_context(browser, width=1280)
        try:
            page = context.new_page()
            collect_image_responses(page, samples)
            page.goto(base + page_path("html", "nested/blog"), wait_until="load")
            for raw in candidate_urls(page):
                absolute = urljoin(base + "nested/blog.html", str(raw))
                basename = local_candidate_basename(absolute)
                entries.append(
                    {
                        "source_name": source_name,
                        "published_basename": basename,
                        "url": absolute,
                        "uri_safe": bool(_URI_SAFE_BASENAME.fullmatch(basename)),
                    }
                )
            write_observations(out, entries)
            decode_managed(page)
            write_observations(
                out,
                [
                    *entries,
                    {
                        "summary": "responses",
                        "sample_statuses": [{"url": s["url"], "status": s["status"]} for s in samples],
                    },
                ],
            )
        finally:
            context.close()
    assert entries, "no managed candidates observed"
    for entry in entries:
        assert entry["uri_safe"], entry["published_basename"]
    for sample in samples:
        if urlsplit(sample["url"]).path.startswith("/_images/maatlog/"):
            assert sample["status"] == 200, sample["url"]
