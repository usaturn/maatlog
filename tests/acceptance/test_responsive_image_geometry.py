"""Real-browser geometry for responsive images (issue #216, Task 4).

Each managed image's ``sizes`` attribute is evaluated against the real CSS
(a probe ``div`` sized with the selected length) and compared with the
image's rendered width. Expectations never copy the policy's geometry
formulas: only the precision class (exact vs fallback) is chosen from the
observed theme, page and marker.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from acceptance.built_sites import BuiltSites
from acceptance.responsive_image_site import (
    MAIN_WIDTHS,
    THIRD_PARTY_THEME,
    WIDTHS,
    ImageRecord,
    assert_slot,
    build_archive_site,
    build_image_site,
    decode_all_images,
    evaluate_sizes,
    measure_images,
    site_page,
    write_observations,
)
from playwright.sync_api import Browser, Page

EXACT_PAGES = frozenset({"home", "archive", "post1"})


def _precision(theme: str, page_name: str, record: ImageRecord) -> str | None:
    """Precision class from observed values only (no geometry formulas)."""
    if record["marker"] != "w-v1" or record["sizes"] is None:
        return None
    if theme == "maatlog-default" and page_name in EXACT_PAGES:
        return "exact"
    return "fallback"


def _check_images(
    page: Page,
    *,
    theme: str,
    page_name: str,
    viewport_width: int,
) -> list[dict[str, object]]:
    """Assert slot geometry for every managed image; return observations."""
    decode_all_images(page)
    observations: list[dict[str, object]] = []
    for record in measure_images(page):
        precision = _precision(theme, page_name, record)
        entry: dict[str, object] = {
            "page": page_name,
            "slug": record["slug"],
            "css_class": record["css_class"],
            "sizes": record["sizes"],
            "precision": precision,
            "rendered": dict(record["rect"]),
            "intrinsic": {"width": record["natural_width"], "height": record["natural_height"]},
            "loading": record["loading"],
            "fetchpriority": record["fetchpriority"],
            "current_src": record["current_src"],
        }
        if record["sizes"] is None:
            # Fallback single-src image: must still decode, never 404 (checked
            # by the loading tests' response gate).
            assert record["complete"] and record["natural_width"] > 0, record["src"]
            observations.append(entry)
            continue
        evaluated_length, evaluated = evaluate_sizes(page, record["sizes"])
        assert evaluated > 0, f"sizes evaluated to 0: {record['sizes']!r}"
        entry["evaluated_length"] = evaluated_length
        entry["evaluated_sizes"] = evaluated
        observations.append(entry)
        assert precision is not None, record["src"]
        assert_slot(
            {
                "rendered_width": record["rect"]["width"],
                "evaluated_sizes": evaluated,
                "precision": precision,
                "viewport_width": viewport_width,
            }
        )
    assert observations, f"no images measured on {page_name}"
    return observations


def _card_count(page: Page) -> int:
    return int(
        page.evaluate("() => document.querySelectorAll('.maatlog-post-card').length"),
    )


def _overflow(page: Page) -> float:
    return float(
        page.evaluate(
            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth",
        )
    )


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-default", "maatlog-base"])
@pytest.mark.parametrize("width", MAIN_WIDTHS)
def test_main_widths_geometry(
    built_sites: BuiltSites,
    tmp_path: Path,
    shared_browser: Browser,
    theme: str,
    width: int,
) -> None:
    """Managed slots match the rendered width at the six main widths.

    The dark scheme only redefines colour custom properties, so geometry is
    spot-checked by test_color_scheme_geometry_spot on the real
    maatlog-default build rather than crossed with theme and width.
    test_base_and_dark_spots covers the separate base-theme loading and
    dark-mode decode paths.
    """
    built = build_image_site(built_sites, builder="html", theme=theme, responsive=True)
    context = shared_browser.new_context(
        viewport={"width": width, "height": 900},
        device_scale_factor=1,
    )
    try:
        observations: list[dict[str, object]] = []
        for page_name in ("home", "archive", "post1", "profile", "showcase"):
            expected_cards = {"home": 12, "archive": 12, "profile": 6, "showcase": 3}.get(page_name)
            page = context.new_page()
            try:
                page.goto(built.base_url + site_page(built.builder, page_name), wait_until="load")
                assert _overflow(page) <= 1, page_name
                if expected_cards is not None:
                    # No Infinite Scroll append may sneak cards in mid-measurement.
                    assert _card_count(page) == expected_cards, (page_name, width)
                    assert page.locator(".maatlog-infinite-sentinel").count() == 0, page_name
                for entry in _check_images(page, theme=theme, page_name=page_name, viewport_width=width):
                    observations.append(
                        {
                            "browser": "chromium",
                            "browser_version": shared_browser.version,
                            "theme": theme,
                            "color_scheme": "light",
                            "viewport": {"width": width, "height": 900},
                            "dpr": 1,
                            **entry,
                        }
                    )
            finally:
                page.close()
    finally:
        context.close()
    write_observations(tmp_path / "responsive-image-observations.json", observations)


@pytest.mark.browser
@pytest.mark.parametrize("featured_count", [0, 1, 2, 4])
@pytest.mark.parametrize("width", [390, 1280])
def test_featured_count_variants_geometry(
    built_sites: BuiltSites,
    shared_browser: Browser,
    featured_count: int,
    width: int,
) -> None:
    """Home Featured 0/1/2/4 and the legacy slices keep exact slots."""
    built = build_image_site(
        built_sites,
        builder="html",
        theme="maatlog-default",
        responsive=True,
        featured_count=featured_count,
    )
    context = shared_browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=1)
    try:
        for page_name in ("home", "archive"):
            page = context.new_page()
            try:
                page.goto(built.base_url + site_page(built.builder, page_name), wait_until="load")
                assert _overflow(page) <= 1, (featured_count, page_name)
                _check_images(
                    page,
                    theme="maatlog-default",
                    page_name=page_name,
                    viewport_width=width,
                )
            finally:
                page.close()
    finally:
        context.close()


@pytest.mark.browser
@pytest.mark.parametrize("post_count", [1, 2, 4, 9])
@pytest.mark.parametrize("width", [390, 1280])
def test_archive_counts_geometry(
    built_sites: BuiltSites,
    shared_browser: Browser,
    post_count: int,
    width: int,
) -> None:
    """Exact-count plain-archive grids keep exact slots with no appends."""
    built = build_archive_site(
        built_sites, builder="html", theme="maatlog-default", responsive=True, post_count=post_count
    )
    context = shared_browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=1)
    try:
        page = context.new_page()
        try:
            page.goto(built.base_url + site_page(built.builder, "archive"), wait_until="load")
            assert _overflow(page) <= 1, (post_count, width)
            assert _card_count(page) == post_count, (post_count, width)
            assert page.locator(".maatlog-infinite-sentinel").count() == 0
            managed = [record for record in measure_images(page) if record["marker"] == "w-v1"]
            assert len(managed) == post_count, (post_count, width)
            decode_all_images(page)
            for record in measure_images(page):
                if record["marker"] != "w-v1":
                    continue
                _, evaluated = evaluate_sizes(page, record["sizes"] or "")
                assert evaluated > 0, record["sizes"]
                assert_slot(
                    {
                        "rendered_width": record["rect"]["width"],
                        "evaluated_sizes": evaluated,
                        "precision": "exact",
                        "viewport_width": width,
                    }
                )
        finally:
            page.close()
    finally:
        context.close()


@pytest.mark.browser
@pytest.mark.parametrize("width", [576, 816, 1128, 2222, 2560])
def test_archive_thresholds_geometry(
    built_sites: BuiltSites,
    shared_browser: Browser,
    width: int,
) -> None:
    """Archive column thresholds keep exact slots on the 9-card grid.

    The +-1px neighbours of each threshold are swept by
    test_responsive_real_geometry.py::test_boundary_widths_geometry against
    the same theme CSS; this row keeps the 9-card plain-archive grid that
    the real fixture cannot cheaply produce.
    """
    built = build_archive_site(built_sites, builder="html", theme="maatlog-default", responsive=True, post_count=9)
    context = shared_browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=1)
    try:
        page = context.new_page()
        try:
            page.goto(built.base_url + site_page(built.builder, "archive"), wait_until="load")
            assert _overflow(page) <= 1, width
            assert _card_count(page) == 9, width
            decode_all_images(page)
            for record in measure_images(page):
                if record["marker"] != "w-v1":
                    continue
                _, evaluated = evaluate_sizes(page, record["sizes"] or "")
                assert_slot(
                    {
                        "rendered_width": record["rect"]["width"],
                        "evaluated_sizes": evaluated,
                        "precision": "exact",
                        "viewport_width": width,
                    }
                )
        finally:
            page.close()
    finally:
        context.close()


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1280, 2560])
def test_no_rail_geometry(
    built_sites: BuiltSites,
    shared_browser: Browser,
    width: int,
) -> None:
    """The no-rail layout keeps exact slots and really drops the rail."""
    built = build_image_site(
        built_sites,
        builder="html",
        theme="maatlog-default",
        responsive=True,
        has_rail=False,
    )
    context = shared_browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=1)
    try:
        for page_name in ("home", "archive", "post1"):
            page = context.new_page()
            try:
                page.goto(built.base_url + site_page(built.builder, page_name), wait_until="load")
                assert _overflow(page) <= 1, (width, page_name)
                assert "maatlog-layout-has-rail" not in (page.content() or ""), page_name
                _check_images(
                    page,
                    theme="maatlog-default",
                    page_name=page_name,
                    viewport_width=width,
                )
            finally:
                page.close()
    finally:
        context.close()


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1280])
def test_third_party_override_geometry(
    built_sites: BuiltSites,
    shared_browser: Browser,
    width: int,
) -> None:
    """The override policy value (321px post-top, else 123px) is what the browser evaluates."""
    built = build_image_site(built_sites, builder="html", theme=THIRD_PARTY_THEME, responsive=True)
    context = shared_browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=1)
    try:
        for page_name in ("home", "post1"):
            page = context.new_page()
            try:
                page.goto(built.base_url + site_page(built.builder, page_name), wait_until="load")
                decode_all_images(page)
                managed = [record for record in measure_images(page) if record["marker"] == "w-v1"]
                assert managed, page_name
                for record in managed:
                    expected = 321.0 if record["css_class"] == "maatlog-post-top-image-img" else 123.0
                    assert record["sizes"] == f"{expected:.0f}px", record["sizes"]
                    _, evaluated = evaluate_sizes(page, record["sizes"] or "")
                    assert abs(evaluated - expected) <= 1, (record["sizes"], evaluated)
                    assert record["complete"] and record["natural_width"] > 0
            finally:
                page.close()
    finally:
        context.close()


@pytest.mark.browser
def test_dirhtml_geometry_smoke(built_sites: BuiltSites, shared_browser: Browser) -> None:
    """dirhtml output keeps exact slots (builder independence spot check)."""
    built = build_image_site(built_sites, builder="dirhtml", theme="maatlog-default", responsive=True)
    context = shared_browser.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
    try:
        for page_name in ("home", "post1"):
            page = context.new_page()
            try:
                page.goto(built.base_url + site_page(built.builder, page_name), wait_until="load")
                assert _overflow(page) <= 1, page_name
                _check_images(
                    page,
                    theme="maatlog-default",
                    page_name=page_name,
                    viewport_width=1280,
                )
            finally:
                page.close()
    finally:
        context.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-default", "maatlog-base"])
def test_natural_dimensions_and_crop(built_sites: BuiltSites, shared_browser: Browser, theme: str) -> None:
    """width/height match the natural size; base keeps ratio, default keeps crop."""
    built = build_image_site(built_sites, builder="html", theme=theme, responsive=True)
    context = shared_browser.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
    try:
        page = context.new_page()
        try:
            page.goto(built.base_url + site_page(built.builder, "home"), wait_until="load")
            decode_all_images(page)
            by_slug = {record["slug"]: record for record in measure_images(page)}
            expected_naturals = {
                "post1": (1600, 900),
                "post11": (900, 1600),
                "post12": (240, 135),
            }
            for slug, (natural_width, natural_height) in expected_naturals.items():
                record = by_slug[slug]
                assert record["marker"] == "w-v1", slug
                assert (record["width_attr"], record["height_attr"]) == (
                    str(natural_width),
                    str(natural_height),
                ), slug
                # srcset images report density-corrected natural sizes
                # (file pixels divided by the selected density), so only
                # the ratio is comparable with the file geometry.
                reported_ratio = record["natural_width"] / record["natural_height"]
                assert abs(reported_ratio - natural_width / natural_height) < 0.03, slug
                rendered_ratio = record["rect"]["width"] / record["rect"]["height"]
                if theme == "maatlog-base":
                    assert abs(rendered_ratio - natural_width / natural_height) < 0.02, slug
                elif slug == "post11":
                    # Portrait candidate is cropped to the card ratio, not stretched.
                    assert abs(rendered_ratio - 16 / 9) < 0.03, (slug, rendered_ratio)
        finally:
            page.close()
    finally:
        context.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-default", "maatlog-base"])
@pytest.mark.parametrize("width", [1280, 640])
def test_display_and_top_wrapper_ratios(
    built_sites: BuiltSites, tmp_path: Path, shared_browser: Browser, theme: str, width: int
) -> None:
    """Rendered display ratios: default lead 4/3, hero 21/9, top 16/9; base keeps
    natural; the top wrapper is 16/9 above 640px and 4/3 at or below."""
    records: list[dict[str, object]] = []
    built = build_image_site(built_sites, builder="html", theme=theme, responsive=True)
    context = shared_browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=1)
    try:
        home = context.new_page()
        try:
            home.goto(built.base_url + site_page(built.builder, "home"), wait_until="load")
            decode_all_images(home)
            lead_ratio = float(
                home.locator('[data-maatlog-card-variant="lead"] img').evaluate(
                    "img => { const rect = img.getBoundingClientRect(); return rect.width / rect.height; }"
                )
            )
            records.append({"page": "home", "target": "lead", "ratio": lead_ratio})
            if theme == "maatlog-default":
                assert abs(lead_ratio - 4 / 3) < 0.03, lead_ratio
            else:
                # post10 is a landscape natural; base never crops cards.
                assert abs(lead_ratio - 16 / 9) < 0.03, lead_ratio
        finally:
            home.close()
        post = context.new_page()
        try:
            post.goto(built.base_url + site_page(built.builder, "post1"), wait_until="load")
            decode_all_images(post)
            ratios = cast(
                dict[str, float],
                post.evaluate(
                    """() => {
                        const ratioOf = (selector) => {
                            const rect = document.querySelector(selector).getBoundingClientRect();
                            return rect.width / rect.height;
                        };
                        return {
                            hero: ratioOf('.maatlog-post-hero-image'),
                            top_img: ratioOf('.maatlog-post-top-image-img'),
                            top_wrapper: ratioOf('.maatlog-post-top-image'),
                        };
                    }""",
                ),
            )
            records.append({"page": "post1", "width": width, **ratios})
            if theme == "maatlog-default":
                assert abs(ratios["hero"] - 21 / 9) < 0.03, ratios
            else:
                # Landscape representative keeps its natural ratio.
                assert abs(ratios["hero"] - 16 / 9) < 0.03, ratios
            expected_top = 16 / 9 if width > 640 else 4 / 3
            assert abs(ratios["top_img"] - expected_top) < 0.03, ratios
            assert abs(ratios["top_wrapper"] - expected_top) < 0.03, ratios
        finally:
            post.close()
    finally:
        context.close()
    write_observations(tmp_path / "responsive-image-observations.json", records)


def test_observations_record_shape(tmp_path: Path) -> None:
    """The observation writer keeps every brief-mandated field."""
    record: dict[str, object] = {
        "browser": "chromium",
        "browser_version": "x",
        "theme": "maatlog-default",
        "color_scheme": "light",
        "viewport": {"width": 390, "height": 900},
        "dpr": 1,
        "current_src": "http://127.0.0.1/_images/maatlog/hero-480.png",
        "candidates": ["http://127.0.0.1/_images/maatlog/hero-480.png"],
        "rendered": {"width": 244.0, "height": 137.0},
        "intrinsic": {"width": 480, "height": 270},
        "response_bytes": 932,
        "http_status": 200,
        "loading": "eager",
        "fetchpriority": "high",
    }
    path = write_observations(tmp_path / "responsive-image-observations.json", [record])
    assert path.is_file()


def test_assert_slot_classes() -> None:
    """The brief's slot gate, verbatim semantics, on hand values."""
    assert_slot({"rendered_width": 244.0, "evaluated_sizes": 244.0, "precision": "exact", "viewport_width": 390})
    assert_slot({"rendered_width": 310.0, "evaluated_sizes": 390.0, "precision": "fallback", "viewport_width": 390})
    with pytest.raises(AssertionError):
        assert_slot({"rendered_width": 244.0, "evaluated_sizes": 300.0, "precision": "exact", "viewport_width": 390})
    with pytest.raises(AssertionError):
        assert_slot(
            {"rendered_width": 500.0, "evaluated_sizes": 390.0, "precision": "fallback", "viewport_width": 390}
        )


def test_widths_cover_main_and_threshold_edges() -> None:
    assert MAIN_WIDTHS == [390, 768, 1280, 1920, 2560, 3840]
    assert len(WIDTHS) == 32
    for edge in (576, 768, 816, 1024, 1128, 1224, 2222, 3022):
        assert any(abs(width - edge) <= 1 for width in WIDTHS), edge
