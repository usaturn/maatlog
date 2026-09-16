"""Infinite Scroll resolves managed responsive-image candidates (issue #216, Task 3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from acceptance.server import serve_directory
from playwright.sync_api import sync_playwright


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_imported_candidates_use_fetched_page(tmp_path: Path, builder: str) -> None:
    from acceptance.responsive_image_site import write_scroll_site

    path = write_scroll_site(tmp_path, builder=builder, srcset="../images/a%20b.png 480w, ../images/a%2Cb.png 960w")
    with serve_directory(tmp_path) as base, sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(base + path)
        page.wait_for_selector(".maatlog-infinite-sentinel", state="attached")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        image = page.locator('[data-slug="page-two"] img')
        image.wait_for(state="attached")
        fetched = base + ("nested/blog/page/2.html" if builder == "html" else "nested/blog/page/2/")
        expected = page.evaluate(
            "u => [new URL('../images/a%20b.png',u).href+' 480w',"
            "new URL('../images/a%2Cb.png',u).href+' 960w'].join(', ')",
            fetched,
        )
        assert image.get_attribute("srcset") == expected
        assert image.get_attribute("fetchpriority") != "high"
        browser.close()


# ---------------------------------------------------------------------------
# Case table (plan Task 3): unknown grammars stay byte-identical, valid
# grammars resolve each candidate against the fetched page.
# ---------------------------------------------------------------------------

from acceptance.responsive_image_site import write_scroll_site  # noqa: E402
from playwright.sync_api import Page, Request, Route  # noqa: E402


def _allow_only_page_two(page: Page, base: str) -> None:
    """Let Infinite Scroll fetch page 2 once, then abort page 3+.

    Keeps single-append assertions stable: without this, the sentinel can
    autofill through page 3 before the page-2 checks run.
    """

    def gate(route: Route, request: Request) -> None:
        if request.resource_type not in {"fetch", "xhr"}:
            route.continue_()
            return
        url = request.url
        if "page/2" in url:
            route.continue_()
        elif "page/3" in url:
            route.abort()
        else:
            route.continue_()

    page.route(f"{base}nested/blog/page/**", gate)


def _open_and_load_page_two(page: Page, base: str, path: str) -> None:
    page.goto(base + path)
    page.wait_for_selector(".maatlog-infinite-sentinel", state="attached")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.locator('[data-slug="page-two"] img').wait_for(state="attached")


def _fetched_page_two(base: str, builder: str) -> str:
    return base + ("nested/blog/page/2.html" if builder == "html" else "nested/blog/page/2/")


def _fetched_page_three(base: str, builder: str) -> str:
    return base + ("nested/blog/page/3.html" if builder == "html" else "nested/blog/page/3/")


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_percent_encodings_all_resolve(tmp_path: Path, builder: str) -> None:
    """%20 / %2C / %25 candidates each resolve against the fetched page."""
    srcset = "../images/a%20b.png 480w, ../images/a%2Cb.png 960w, ../images/a%25b.png 1200w"
    path = write_scroll_site(tmp_path, builder=builder, srcset=srcset)
    with serve_directory(tmp_path) as base, sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            _allow_only_page_two(page, base)
            _open_and_load_page_two(page, base, path)
            fetched = _fetched_page_two(base, builder)
            expected = page.evaluate(
                "u => [new URL('../images/a%20b.png',u).href+' 480w',"
                "new URL('../images/a%2Cb.png',u).href+' 960w',"
                "new URL('../images/a%25b.png',u).href+' 1200w'].join(', ')",
                fetched,
            )
            image = page.locator('[data-slug="page-two"] img')
            assert image.get_attribute("srcset") == expected
            assert image.get_attribute("fetchpriority") == "auto"
            assert image.get_attribute("loading") == "eager"
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_absolute_urls_reapply_to_the_same_string(tmp_path: Path, builder: str) -> None:
    """Already-absolute http(s) candidates are managed but idempotent."""
    srcset = "https://example.invalid/a.png 480w, https://example.invalid/b.png 960w"
    path = write_scroll_site(tmp_path, builder=builder, srcset=srcset)
    with serve_directory(tmp_path) as base, sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()

            def abort_foreign_images(route: Route, request: Request) -> None:
                if request.resource_type == "image":
                    route.abort()
                else:
                    route.continue_()

            # Never touch the network for the foreign candidates.
            page.route(
                "https://example.invalid/*",
                abort_foreign_images,
            )
            _allow_only_page_two(page, base)
            _open_and_load_page_two(page, base, path)
            image = page.locator('[data-slug="page-two"] img')
            assert image.get_attribute("srcset") == srcset
            # Rewritten (not ignored): the managed high hint still drops.
            assert image.get_attribute("fetchpriority") == "auto"
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_srcset_only_root_is_rewritten(tmp_path: Path, builder: str) -> None:
    """An img without src still rewrites, including the pagination root img."""
    srcset = "../images/a.png 480w, ../images/b.png 960w"
    path = write_scroll_site(tmp_path, builder=builder, srcset=srcset, src=None)
    with serve_directory(tmp_path) as base, sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            _allow_only_page_two(page, base)
            _open_and_load_page_two(page, base, path)
            fetched = _fetched_page_two(base, builder)
            expected = page.evaluate(
                "u => [new URL('../images/a.png',u).href+' 480w',"
                "new URL('../images/b.png',u).href+' 960w'].join(', ')",
                fetched,
            )
            card_image = page.locator('[data-slug="page-two"] img')
            assert card_image.get_attribute("src") is None
            assert card_image.get_attribute("srcset") == expected
            assert card_image.get_attribute("fetchpriority") == "auto"
            # The page-2 pagination carries the same img as a direct child;
            # adoptPagination rewrites it via the root-element path.
            root_image = page.locator(".maatlog-pagination img")
            assert root_image.count() >= 1
            assert root_image.first.get_attribute("srcset") == expected
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_source_element_is_never_rewritten(tmp_path: Path, builder: str) -> None:
    """<source> with the same managed srcset stays relative while <img> resolves."""
    srcset = "../images/a%20b.png 480w, ../images/a%2Cb.png 960w"
    path = write_scroll_site(tmp_path, builder=builder, srcset=srcset)
    with serve_directory(tmp_path) as base, sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            _allow_only_page_two(page, base)
            _open_and_load_page_two(page, base, path)
            fetched = _fetched_page_two(base, builder)
            expected = page.evaluate(
                "u => [new URL('../images/a%20b.png',u).href+' 480w',"
                "new URL('../images/a%2Cb.png',u).href+' 960w'].join(', ')",
                fetched,
            )
            assert page.locator('[data-slug="page-two"] img').get_attribute("srcset") == expected
            assert page.locator('[data-slug="page-two"] source').get_attribute("srcset") == srcset
        finally:
            browser.close()


_UNKNOWN_CASES: list[tuple[str, str | None, str]] = [
    # (srcset, marker, description) — every one must stay byte-identical.
    ("data:image/png;base64,iVBORw0KGgo= 480w", None, "unmarked data URL"),
    ("data:image/png;base64,iVBORw0KGgo= 480w", "w-v1", "marked data URL"),
    ("../images/a.png 1x, ../images/b.png 2x", "w-v1", "x descriptors"),
    ("", "w-v1", "empty"),
    ("../images/a.png 0w", "w-v1", "zero width"),
    ("../images/a.png -480w", "w-v1", "negative width"),
    ("../images/a.png 480.5w", "w-v1", "float width"),
    ("../images/a.png 480w, ../images/b.png 480w", "w-v1", "duplicate width"),
    ("../images/a.png 9007199254740993w", "w-v1", "unsafe integer width"),
    ("../images/a%2Gb.png 480w", "w-v1", "broken percent escape"),
    ("../images/a.png 480w, garbage!! 960w", "w-v1", "mixed invalid candidate"),
    ("../images/a.png?x=1 480w", "w-v1", "query string"),
    ("../images/a.png#frag 480w", "w-v1", "fragment"),
    ("../images/a.png 480w", "w-v2", "other marker version"),
    ("../images/a.png 480w", None, "valid grammar without marker"),
]


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
@pytest.mark.parametrize(
    ("srcset", "marker", "case"),
    [(srcset, marker, case) for srcset, marker, case in _UNKNOWN_CASES],
    ids=[case for _, _, case in _UNKNOWN_CASES],
)
def test_unknown_srcset_stays_byte_identical(
    tmp_path: Path, builder: str, srcset: str, marker: str | None, case: str
) -> None:
    del case
    path = write_scroll_site(tmp_path, builder=builder, srcset=srcset, marker=marker)
    with serve_directory(tmp_path) as base, sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            _allow_only_page_two(page, base)
            _open_and_load_page_two(page, base, path)
            assert page.locator('[data-slug="page-two"] img').get_attribute("srcset") == srcset
            assert page.locator('[data-slug="page-two"] source').get_attribute("srcset") == srcset
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_managed_invalid_still_drops_high_unmanaged_keeps_high(tmp_path: Path, builder: str) -> None:
    """fetchpriority follows the marker, not the srcset grammar result."""
    valid = "../images/a.png 480w"
    invalid = "../images/a.png 0w"
    with serve_directory(tmp_path) as base, sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            # Managed but invalid: srcset stays, high still drops to auto.
            path = write_scroll_site(tmp_path, builder=builder, srcset=invalid, marker="w-v1")
            page = browser.new_page()
            _allow_only_page_two(page, base)
            _open_and_load_page_two(page, base, path)
            managed = page.locator('[data-slug="page-two"] img')
            assert managed.get_attribute("srcset") == invalid
            assert managed.get_attribute("fetchpriority") == "auto"
            page.close()

            # Unmanaged valid: srcset stays and high stays (not our grammar).
            path = write_scroll_site(tmp_path, builder=builder, srcset=valid, marker=None)
            page = browser.new_page()
            _allow_only_page_two(page, base)
            _open_and_load_page_two(page, base, path)
            unmanaged = page.locator('[data-slug="page-two"] img')
            assert unmanaged.get_attribute("srcset") == valid
            assert unmanaged.get_attribute("fetchpriority") == "high"
            page.close()
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_third_page_resolves_against_its_own_url(tmp_path: Path, builder: str) -> None:
    """Chained appends keep resolving (and linking) against each fetched page."""
    srcset = "../images/a%20b.png 480w, ../images/a%2Cb.png 960w"
    path = write_scroll_site(tmp_path, builder=builder, srcset=srcset)
    with serve_directory(tmp_path) as base, sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(base + path)
            page.wait_for_selector(".maatlog-infinite-sentinel", state="attached")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.locator('[data-slug="page-two"] img').wait_for(state="attached")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.locator('[data-slug="page-three"] img').wait_for(state="attached")
            # The last page has no next link, so loading stops there.
            page.wait_for_selector(".maatlog-infinite-sentinel", state="detached")
            assert page.locator(".maatlog-pagination-next").count() == 0
            for slug in ("page-two", "page-three"):
                fetched = (
                    _fetched_page_two(base, builder) if slug == "page-two" else _fetched_page_three(base, builder)
                )
                expected = page.evaluate(
                    "u => [new URL('../images/a%20b.png',u).href+' 480w',"
                    "new URL('../images/a%2Cb.png',u).href+' 960w'].join(', ')",
                    fetched,
                )
                image = page.locator(f'[data-slug="{slug}"] img')
                assert image.get_attribute("srcset") == expected
                assert image.get_attribute("fetchpriority") == "auto"
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_same_origin_redirect_uses_final_url(tmp_path: Path, builder: str) -> None:
    """Candidates resolve against response.url; both URLs are recorded."""
    from fixtures.responsive_image_fixtures import make_test_png

    srcset = "a.png 480w"
    path = write_scroll_site(tmp_path, builder=builder, srcset=srcset, src="hero.png")
    with serve_directory(tmp_path) as base, sync_playwright() as pw:
        # Mirror page 2 under a different directory so the requested and final
        # bases disagree; the copied card keeps slug "page-two".
        if builder == "html":
            source = tmp_path / "nested" / "blog" / "page" / "2.html"
            target = tmp_path / "nested" / "rerouted" / "page2.html"
            requested_url = base + "nested/blog/page/2.html"
            final_url = base + "nested/rerouted/page2.html"
        else:
            source = tmp_path / "nested" / "blog" / "page" / "2" / "index.html"
            target = tmp_path / "nested" / "rerouted" / "page2" / "index.html"
            requested_url = base + "nested/blog/page/2/"
            final_url = base + "nested/rerouted/page2/"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        payload = make_test_png(64, 36)
        (target.parent / "a.png").write_bytes(payload)
        (target.parent / "hero.png").write_bytes(payload)

        browser = pw.chromium.launch()
        try:
            page = browser.new_page()

            def redirect(route: Route, request: Request) -> None:
                if request.resource_type in {"fetch", "xhr"} and request.url == requested_url:
                    route.fulfill(status=302, headers={"location": final_url}, body="")
                else:
                    route.continue_()

            page.route(f"{base}nested/**", redirect)
            page.add_init_script(
                """window.__lastAddedUrl = null;
                  document.addEventListener("maatlog:content-added",
                    (event) => { window.__lastAddedUrl = event.detail.url; });"""
            )
            page.goto(base + path)
            page.wait_for_selector(".maatlog-infinite-sentinel", state="attached")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.locator('[data-slug="page-two"] img').wait_for(state="attached")
            page.wait_for_function("() => window.__lastAddedUrl !== null")
            expected = page.evaluate(
                "u => new URL('a.png', u).href + ' 480w'",
                final_url,
            )
            assert page.locator('[data-slug="page-two"] img').get_attribute("srcset") == expected
            # Without a redirect the event value would be the requested URL.
            assert page.evaluate("() => window.__lastAddedUrl") == final_url
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_foreign_origin_redirect_is_dropped(tmp_path: Path, builder: str) -> None:
    """A cross-origin final URL takes the existing error path: no import."""
    srcset = "../images/a.png 480w"
    path = write_scroll_site(tmp_path, builder=builder, srcset=srcset)
    with serve_directory(tmp_path) as base, sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            requested_url = _fetched_page_two(base, builder)
            foreign_html = (
                "<!doctype html><html><body>"
                '<section class="maatlog-archive" data-maatlog-component="archive">'
                '<div class="maatlog-post-list"><div class="maatlog-post-grid">'
                '<article class="maatlog-post-card" data-maatlog-component="post-card"'
                ' data-slug="foreign"><h2>Foreign</h2></article>'
                "</div></div></section></body></html>"
            )

            def redirect(route: Route, request: Request) -> None:
                if request.resource_type in {"fetch", "xhr"} and request.url == requested_url:
                    route.fulfill(
                        status=302,
                        headers={"location": "https://example.invalid/foreign.html"},
                        body="",
                    )
                else:
                    route.continue_()

            def foreign(route: Route, request: Request) -> None:
                route.fulfill(status=200, content_type="text/html", body=foreign_html)

            page.route(f"{base}nested/**", redirect)
            page.route("https://example.invalid/*", foreign)
            page.goto(base + path)
            page.wait_for_selector(".maatlog-infinite-sentinel", state="attached")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            # The loader gives up without importing: one card, no sentinel.
            page.wait_for_selector(".maatlog-infinite-sentinel", state="detached")
            assert page.locator(".maatlog-post-card").count() == 1
            assert page.locator('[data-slug="foreign"]').count() == 0
            assert page.locator('[data-slug="page-two"]').count() == 0
            # Ordinary pagination survives for manual navigation.
            assert page.locator(".maatlog-pagination-next").count() == 1
        finally:
            browser.close()
