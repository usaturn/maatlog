"""Real-browser geometry for real responsive-image builds (issue #217, task F/T4).

Sites come from real ``python -m sphinx`` runs via
``fixtures.responsive_real_build`` -- nothing is injected into the output.
The slot expectations never copy the policy formulas: each page only chooses
its precision class (``exact`` for the default theme's real card/post
layouts, ``fallback`` for standalone/base/override surfaces).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final

import pytest
from acceptance.built_sites import BuiltSite
from acceptance.real_built_sites import RealSites
from acceptance.responsive_image_site import MAIN_WIDTHS, WIDTHS, write_observations
from acceptance.responsive_real_browser import (
    MANAGED_SELECTOR,
    CardState,
    Color,
    GeometryObservation,
    ManagedState,
    assert_geometry,
    capture_geometry,
    card_states,
    decode_fallback,
    decode_managed,
    managed_states,
    new_context,
    open_page,
    page_overflow,
    page_path,
)
from playwright.sync_api import Browser

#: Pages whose managed images use the default theme's exact slot formulas.
EXACT_PAGES: Final = ("index", "nested/blog", "posts/p01")
#: Standalone-presentation pages: the conservative ``100vw`` fallback.
FALLBACK_PAGES: Final = ("listing", "nested/blog/author/alice")
BOUNDARY_WIDTHS: Final = [width for width in WIDTHS if width not in MAIN_WIDTHS]


def _observe_pages(
    browser: Browser,
    site: BuiltSite,
    *,
    pages: Iterable[tuple[str, str]],
    out: Path,
    meta: Mapping[str, object] | None = None,
    width: int,
    height: int = 900,
    dpr: float = 1,
    color: Color = "light",
) -> list[GeometryObservation]:
    """Visit *pages* on the built site and capture slot observations.

    Evidence is written to *out* after every page -- once right after the
    pre-decode snapshot and again once the records are refreshed post-decode --
    so a decode failure or a later assert never destroys the observations.
    """
    observations: list[GeometryObservation] = []

    def _persist() -> None:
        write_observations(out, [{**(meta or {}), **dict(o)} for o in observations])

    context = new_context(browser, width=width, height=height, dpr=dpr, color=color)
    try:
        for docname, precision in pages:
            with open_page(context, site.base_url + page_path(site.builder, docname)) as page:
                start = len(observations)
                observations.extend(capture_geometry(page, viewport_width=width, precision=precision, docname=docname))
                _persist()
                decode_managed(page)
                decode_fallback(page)
                observations[start:] = capture_geometry(
                    page, viewport_width=width, precision=precision, docname=docname
                )
                _persist()
    finally:
        context.close()
    return observations


def _assert_all(observations: list[GeometryObservation]) -> None:
    assert observations, "no managed images observed"
    for observation in observations:
        assert observation["overflow"] <= 1, observation["docname"]
        assert_geometry(observation)
        # The spec'd "first-6 eager then lazy" rule wins over the generic
        # "initial viewport is never lazy" check: at 2560px the three-column
        # archive grid shows grid_index 6-8 above the 900px fold while spec
        # still mandates lazy for them (recorded in the task-4 report).
        if observation["in_initial_viewport"] and observation["grid_index"] < 6:
            assert observation["loading"] == "eager", (
                observation["docname"],
                observation["slug"],
                observation["loading"],
            )


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
@pytest.mark.parametrize("width", MAIN_WIDTHS)
def test_main_viewports_geometry(
    real_sites: RealSites,
    tmp_path: Path,
    shared_browser: Browser,
    builder: str,
    width: int,
) -> None:
    """Every usage decodes and keeps its slot at the six main widths.

    DPR is observed by the transfer matrix (candidate choice is a bytes
    concern, not a CSS-pixel slot concern) and the dark scheme has its own
    spot test, so neither is crossed with builder x width here.
    """
    site = real_sites.standard(builder, enabled=True)
    pages = [(docname, "exact") for docname in EXACT_PAGES] + [(docname, "fallback") for docname in FALLBACK_PAGES]
    meta = {
        "builder": builder,
        "theme": "maatlog-default",
        "color_scheme": "light",
        "dpr": 1,
        "viewport": {"width": width, "height": 900},
    }
    observations = _observe_pages(
        shared_browser,
        site,
        pages=pages,
        out=tmp_path / "observations.json",
        meta=meta,
        width=width,
    )
    _assert_all(observations)


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1280])
def test_color_scheme_geometry_spot(
    real_sites: RealSites,
    tmp_path: Path,
    shared_browser: Browser,
    width: int,
) -> None:
    """Dark mode must not move a slot.

    The dark rules in maatlog.css only redefine colour custom properties and
    the theme-toggle icon display, so this is a guard against a future dark
    rule touching geometry -- kept as a spot check instead of a factor
    crossed with builder, DPR and width.
    """
    site = real_sites.standard("html", enabled=True)
    pages = [(docname, "exact") for docname in EXACT_PAGES] + [(docname, "fallback") for docname in FALLBACK_PAGES]
    observations = _observe_pages(
        shared_browser,
        site,
        pages=pages,
        out=tmp_path / "observations.json",
        meta={"builder": "html", "color_scheme": "dark", "dpr": 1},
        width=width,
        color="dark",
    )
    _assert_all(observations)


@pytest.mark.browser
@pytest.mark.parametrize("width", BOUNDARY_WIDTHS)
def test_boundary_widths_geometry(
    real_sites: RealSites,
    tmp_path: Path,
    shared_browser: Browser,
    width: int,
) -> None:
    """Threshold +-1px widths keep the exact slots on home and archive.

    Relative-URL resolution is the only builder-dependent behaviour on these
    pages and it is asserted by test_main_viewports_geometry,
    test_no_javascript_decodes, test_off_builds_decode and
    test_top_roles_and_priority, so the sweep runs on html only.
    """
    site = real_sites.standard("html", enabled=True)
    observations = _observe_pages(
        shared_browser,
        site,
        pages=(("index", "exact"), ("nested/blog", "exact")),
        out=tmp_path / "observations.json",
        meta={"builder": "html", "viewport_width": width},
        width=width,
    )
    _assert_all(observations)


@pytest.mark.browser
@pytest.mark.parametrize("featured", [1, 3])
def test_featured_count_geometry(
    real_sites: RealSites,
    tmp_path: Path,
    shared_browser: Browser,
    featured: int,
) -> None:
    """Featured strips of 1 vs 3 cards keep exact slots and lead order.

    ``maatlog_featured_posts`` pads to FEATURED_LIMIT=3 whenever enough posts
    exist, so the 1-card featured strip needs the single-post site.
    """
    site = real_sites.standard("html", enabled=True) if featured == 3 else real_sites.archive_count(1)
    observations = _observe_pages(
        shared_browser,
        site,
        pages=(("index", "exact"),),
        out=tmp_path / "observations.json",
        width=1280,
    )
    _assert_all(observations)
    states: list[CardState] = []
    context = new_context(shared_browser, width=1280)
    try:
        with open_page(context, site.base_url + page_path("html", "index")) as page:
            states = card_states(page)
            write_observations(
                tmp_path / "featured-cards.json",
                [{"expected_featured": featured, "cards": states}],
            )
    finally:
        context.close()
    featured_cards = [s for s in states if s["variant"] in ("lead", "secondary")]
    assert len(featured_cards) == featured
    assert featured_cards[0]["variant"] == "lead"
    assert featured_cards[0]["slug"] == "p01"
    if featured == 3:
        assert [s["slug"] for s in featured_cards] == ["p01", "p02", "p03"]


@pytest.mark.browser
def test_no_rail_geometry(real_sites: RealSites, tmp_path: Path, shared_browser: Browser) -> None:
    """The no-rail post layout still keeps exact slots."""
    site = real_sites.no_rail()
    observations: list[GeometryObservation] = []
    has_rail = True
    out = tmp_path / "observations.json"

    def _persist() -> None:
        write_observations(out, [{"has_rail": has_rail, **dict(o)} for o in observations])

    context = new_context(shared_browser, width=1280)
    try:
        with open_page(context, site.base_url + page_path("html", "posts/p01")) as page:
            has_rail = "maatlog-layout-has-rail" in (page.content() or "")
            observations = capture_geometry(page, viewport_width=1280, precision="exact", docname="posts/p01")
            _persist()
            decode_managed(page)
            observations = capture_geometry(page, viewport_width=1280, precision="exact", docname="posts/p01")
            _persist()
    finally:
        context.close()
    assert not has_rail, "post page unexpectedly rendered with a rail"
    _assert_all(observations)


@pytest.mark.browser
@pytest.mark.parametrize("count", [1, 2, 4, 9])
def test_archive_count_geometry(
    real_sites: RealSites,
    tmp_path: Path,
    shared_browser: Browser,
    count: int,
) -> None:
    """1/2/4/9-card archive grids keep exact slots and newest-first order."""
    site = real_sites.archive_count(count)
    observations: list[GeometryObservation] = []
    cards: list[CardState] = []
    sentinel_count = -1
    out = tmp_path / "observations.json"

    def _persist() -> None:
        write_observations(
            out,
            [
                {
                    "expected_count": count,
                    "card_count": len(cards),
                    "sentinel_count": sentinel_count,
                    "slugs": [s["slug"] for s in cards],
                    "images": observations,
                }
            ],
        )

    context = new_context(shared_browser, width=1280)
    try:
        with open_page(context, site.base_url + page_path("html", "nested/blog")) as page:
            cards = card_states(page)
            sentinel_count = page.locator(".maatlog-infinite-sentinel").count()
            observations = capture_geometry(page, viewport_width=1280, precision="exact", docname="nested/blog")
            _persist()
            decode_managed(page)
            observations = capture_geometry(page, viewport_width=1280, precision="exact", docname="nested/blog")
            _persist()
    finally:
        context.close()
    assert len(cards) == count
    assert sentinel_count == 0
    assert [s["slug"] for s in cards] == [f"p{index:02d}" for index in range(count, 0, -1)]
    assert len(observations) == count
    _assert_all(observations)


@pytest.mark.browser
def test_base_theme_fallback_geometry(real_sites: RealSites, tmp_path: Path, shared_browser: Browser) -> None:
    """maatlog-base emits the conservative ``100vw`` slot everywhere."""
    observations = _observe_pages(
        shared_browser,
        real_sites.base_theme(),
        pages=(
            ("index", "fallback"),
            ("nested/blog", "fallback"),
            ("posts/p01", "fallback"),
        ),
        out=tmp_path / "observations.json",
        meta={"theme": "maatlog-base"},
        width=1280,
    )
    _assert_all(observations)
    assert all(o["sizes"] == "100vw" for o in observations)


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_managed_card_keeps_ratio_in_narrow_container(
    real_sites: RealSites, shared_browser: Browser, theme: str
) -> None:
    """A width/height-bearing managed image shrinks with its card at 16:9."""
    site = real_sites.base_theme() if theme == "maatlog-base" else real_sites.standard("html", enabled=True)
    context = new_context(shared_browser, width=1280)
    try:
        with open_page(context, site.base_url + page_path("html", "nested/blog")) as page:
            card = page.locator(".maatlog-post-card:has(img[data-maatlog-srcset])").first
            card.evaluate("(element) => { element.style.width = '180px'; }")
            image = card.locator("img[data-maatlog-srcset]")
            image.evaluate("(element) => element.decode()")
            size = image.evaluate(
                "(element) => ({width: element.getBoundingClientRect().width, "
                "height: element.getBoundingClientRect().height})"
            )
            assert 0 < size["width"] <= 180
            assert abs(size["height"] - size["width"] * 9 / 16) <= 1, size
    finally:
        context.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_managed_top_image_still_fills_its_crop_frame(
    real_sites: RealSites, shared_browser: Browser, theme: str
) -> None:
    """The generic image rule must not override the top image's height: 100%."""
    site = real_sites.base_theme() if theme == "maatlog-base" else real_sites.standard("html", enabled=True)
    context = new_context(shared_browser, width=390)
    try:
        with open_page(context, site.base_url + page_path("html", "posts/p01")) as page:
            image = page.locator(".maatlog-post-top-image-img[data-maatlog-srcset]")
            image.evaluate("(element) => element.decode()")
            sizes = image.evaluate(
                "(element) => ({imageHeight: element.getBoundingClientRect().height, "
                "frameHeight: element.parentElement.getBoundingClientRect().height})"
            )
            assert abs(sizes["imageHeight"] - sizes["frameHeight"]) <= 1, sizes
    finally:
        context.close()


@pytest.mark.browser
def test_third_party_override_geometry(real_sites: RealSites, tmp_path: Path, shared_browser: Browser) -> None:
    """The override policy (321px post-top / 123px else) reaches the browser."""
    site = real_sites.override_theme()
    policy: dict[str, list[dict[str, str | None]]] = {}
    observations: list[GeometryObservation] = []
    out = tmp_path / "observations.json"
    context = new_context(shared_browser, width=1280)
    try:
        for docname in ("posts/p01", "index"):
            with open_page(context, site.base_url + page_path("html", docname)) as page:
                decode_managed(page)
                records = capture_geometry(page, viewport_width=1280, precision="fallback", docname=docname)
                observations.extend(records)
                policy[docname] = [{"css_class": record["css_class"], "sizes": record["sizes"]} for record in records]
                write_observations(out, [dict(o) for o in observations])
                write_observations(tmp_path / "override-policy.json", [policy])
    finally:
        context.close()
    for record in observations:
        expected = 321.0 if record["css_class"] == "maatlog-post-top-image-img" else 123.0
        assert record["sizes"] == f"{expected:.0f}px", record["sizes"]
        assert abs(record["evaluated_sizes"] - expected) <= 1
        assert record["loading"] == "eager"
        assert record["fetchpriority"] == "auto"
        assert record["current_src_in_candidates"]


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
@pytest.mark.parametrize("width", [390, 1280])
def test_no_javascript_decodes(
    real_sites: RealSites,
    tmp_path: Path,
    shared_browser: Browser,
    builder: str,
    width: int,
) -> None:
    """With JavaScript disabled every managed image still decodes."""
    site = real_sites.standard(builder, enabled=True)
    observations: list[dict[str, object]] = []
    managed_counts: dict[str, int] = {}
    sentinel_counts: dict[str, int] = {}
    out = tmp_path / "observations.json"
    context = shared_browser.new_context(
        viewport={"width": width, "height": 900},
        java_script_enabled=False,
        service_workers="block",
    )
    try:
        for docname in ("index", "nested/blog", "posts/p01"):
            with open_page(context, site.base_url + page_path(builder, docname)) as page:
                managed_counts[docname] = page.locator(MANAGED_SELECTOR).count()
                sentinel_counts[docname] = page.locator(".maatlog-infinite-sentinel").count()
                observations.append(
                    {
                        "builder": builder,
                        "docname": docname,
                        "viewport": {"width": width, "height": 900},
                        "managed_count": managed_counts[docname],
                        "fallback_count": page.locator("img:not([data-maatlog-srcset])").count(),
                        "sentinel_count": sentinel_counts[docname],
                    }
                )
                write_observations(out, observations)
                decode_managed(page)
                decode_fallback(page)
    finally:
        context.close()
    for docname in managed_counts:
        assert managed_counts[docname] > 0, docname
        assert sentinel_counts[docname] == 0, docname


def _assert_grid_loading(state: CardState) -> None:
    """The spec'd first-6-eager/then-lazy rule for one grid card."""
    if state["has_image"] and state["grid_index"] >= 0:
        expected = "eager" if state["grid_index"] < 6 else "lazy"
        assert state["loading"] == expected, (state["slug"], state["grid_index"])


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
@pytest.mark.parametrize("height", [720, 900])
def test_top_roles_and_priority(
    real_sites: RealSites,
    tmp_path: Path,
    shared_browser: Browser,
    builder: str,
    height: int,
) -> None:
    """Post-top/representative/home-lead priority roles on real output."""
    site = real_sites.standard(builder, enabled=True)
    role_pages = ("posts/p01", "top-only", "representative-only", "no-image")
    card_pages = ("index", "nested/blog", "listing", "nested/blog/author/alice")
    observations: list[dict[str, object]] = []
    image_states: dict[str, list[ManagedState]] = {}
    grid_states: dict[str, list[CardState]] = {}
    overflows: dict[str, float] = {}
    high_counts: dict[str, int] = {}
    out = tmp_path / "observations.json"
    context = new_context(shared_browser, width=1280, height=height)
    try:
        for docname in (*role_pages, *card_pages):
            with open_page(context, site.base_url + page_path(builder, docname)) as page:
                overflows[docname] = page_overflow(page)
                high_counts[docname] = page.locator('img[fetchpriority="high"]').count()
                entry: dict[str, object] = {
                    "builder": builder,
                    "docname": docname,
                    "viewport": {"width": 1280, "height": height},
                    "overflow": overflows[docname],
                    "high_count": high_counts[docname],
                }
                if docname in role_pages:
                    image_states[docname] = managed_states(page)
                    entry["images"] = image_states[docname]
                else:
                    grid_states[docname] = card_states(page)
                    entry["cards"] = grid_states[docname]
                observations.append(entry)
                write_observations(out, observations)
                if page.locator(MANAGED_SELECTOR).count():
                    decode_managed(page)
    finally:
        context.close()
    for docname in role_pages:
        assert overflows[docname] <= 1, docname
        assert high_counts[docname] <= 1, docname
        states = image_states[docname]
        for state in states:
            if state["top"] < height and state["bottom"] > 0:
                assert state["loading"] == "eager", (docname, state)
        if docname == "posts/p01":
            top = next(s for s in states if "top-image" in s["css_class"])
            hero = next(s for s in states if "hero" in s["css_class"])
            assert top["fetchpriority"] == "high"
            assert hero["fetchpriority"] == "auto"
        elif docname == "top-only":
            assert len(states) == 1 and states[0]["fetchpriority"] == "high"
        elif docname == "representative-only":
            assert len(states) == 1 and states[0]["fetchpriority"] == "high"
        else:
            assert not states
    index_states = grid_states["index"]
    assert high_counts["index"] == 1
    lead = index_states[0]
    assert lead["variant"] == "lead" and lead["fetchpriority"] == "high"
    for state in index_states:
        if state["variant"] == "secondary":
            assert state["loading"] == "eager"
            assert state["fetchpriority"] == "auto"
        _assert_grid_loading(state)
    assert high_counts["nested/blog"] == 0
    for state in grid_states["nested/blog"]:
        _assert_grid_loading(state)
    for docname in ("listing", "nested/blog/author/alice"):
        assert high_counts[docname] == 0, docname
        for state in grid_states[docname]:
            if state["has_image"]:
                assert state["loading"] == "eager", (docname, state["slug"])
                assert state["fetchpriority"] == "auto", (docname, state["slug"])


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_off_builds_decode(
    real_sites: RealSites,
    tmp_path: Path,
    shared_browser: Browser,
    builder: str,
) -> None:
    """OFF builds carry no managed images; every emitted image still decodes."""
    site = real_sites.standard(builder, enabled=False)
    observations: list[dict[str, object]] = []
    managed_counts: dict[str, int] = {}
    decoded: dict[str, int] = {}
    overflows: dict[str, float] = {}
    out = tmp_path / "observations.json"
    context = new_context(shared_browser, width=1280)
    try:
        for docname in ("index", "nested/blog", "posts/p01"):
            with open_page(context, site.base_url + page_path(builder, docname)) as page:
                managed_counts[docname] = page.locator(MANAGED_SELECTOR).count()
                overflows[docname] = page_overflow(page)
                entry: dict[str, object] = {
                    "builder": builder,
                    "docname": docname,
                    "managed_count": managed_counts[docname],
                    "fallback_count": page.locator("img:not([data-maatlog-srcset])").count(),
                    "overflow": overflows[docname],
                }
                observations.append(entry)
                write_observations(out, observations)
                decoded[docname] = decode_fallback(page)
                entry["decoded"] = decoded[docname]
                write_observations(out, observations)
    finally:
        context.close()
    for docname in managed_counts:
        assert managed_counts[docname] == 0, docname
        assert decoded[docname] > 0, docname
        assert overflows[docname] <= 1, docname
