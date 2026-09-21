"""Fixed loading/fetchpriority attributes on the fake built site (issue #316).

These checks replace the viewport-independent attribute assertions that
``tests/acceptance/test_responsive_image_loading.py`` used to run in a real
browser (``test_loading_attributes_follow_spec`` and
``test_seventh_grid_images_are_lazy``). The generated HTML carries the same
evidence, so the same fake build is inspected through ``HtmlPage`` selectors
that keep the section/card parent-child relationship instead of matching
bare substrings. Rendering- or network-dependent checks (viewport
intersection, currentSrc, DPR, real bytes, lazy requests, reserved area,
JS-disabled, dark/light) stay in the browser suite.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from acceptance.built_sites import BuiltSite, BuiltSites
from acceptance.responsive_image_site import build_archive_site, build_image_site, site_page
from conftest import HtmlPage

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


@pytest.fixture(scope="module")
def loading_built_sites(tmp_path_factory: pytest.TempPathFactory) -> Generator[BuiltSites]:
    """Worker-local build cache; each fake site is built only when a test asks for it."""
    with BuiltSites(tmp_path_factory.mktemp("loading-attrs")) as sites:
        yield sites


@pytest.fixture(scope="module")
def main_site(loading_built_sites: BuiltSites) -> BuiltSite:
    return build_image_site(loading_built_sites, builder="html", theme="maatlog-default", responsive=True)


@pytest.fixture(scope="module")
def plain_site(loading_built_sites: BuiltSites) -> BuiltSite:
    return build_image_site(
        loading_built_sites,
        builder="html",
        theme="maatlog-default",
        responsive=True,
        featured_count=0,
    )


@pytest.fixture(scope="module")
def nine_site(loading_built_sites: BuiltSites) -> BuiltSite:
    return build_archive_site(
        loading_built_sites, builder="html", theme="maatlog-default", responsive=True, post_count=9
    )


def _page(site: BuiltSite, name: str) -> HtmlPage:
    return HtmlPage((site.outdir / site_page(site.builder, name)).read_text(encoding="utf-8"))


def _managed(attrs: list[dict[str, str]]) -> list[dict[str, str]]:
    return [a for a in attrs if a.get("data-maatlog-srcset") == "w-v1"]


def _loadings(attrs: list[dict[str, str]]) -> list[str | None]:
    return [a.get("loading") for a in attrs]


@pytest.mark.parametrize("page_name", LOADING_PAGES)
def test_at_most_one_high_per_page(main_site: BuiltSite, page_name: str) -> None:
    page = _page(main_site, page_name)
    imgs = page.select("img")
    assert sum(a.get("fetchpriority") == "high" for a in imgs) <= 1, page_name


def test_home_featured_lead_high_and_latest_boundary(main_site: BuiltSite) -> None:
    """Home: one lead card carries the single high; the 7th+ latest go lazy."""
    page = _page(main_site, "home")
    assert page.select(".maatlog-pagination-next") == []

    lead = page.select("[data-maatlog-card-variant='lead'] img")
    assert len(lead) == 1
    assert lead[0]["loading"] == "eager"
    assert lead[0]["fetchpriority"] == "high"

    featured = _managed(page.select("[data-maatlog-component='featured'] img"))
    assert len(featured) == 3
    assert _loadings(featured) == ["eager"] * 3

    latest = _managed(page.select("[data-maatlog-component='latest'] .maatlog-post-card img"))
    assert len(latest) == 9
    assert _loadings(latest) == ["eager"] * 6 + ["lazy"] * 3

    assert len(_managed(page.select("img"))) == 12


def test_archive_featured_and_latest_boundary(main_site: BuiltSite) -> None:
    """Legacy archive: featured slice plus a 9-card latest grid, all below high."""
    page = _page(main_site, "archive")

    featured = _managed(page.select("[data-maatlog-component='featured'] img"))
    assert len(featured) == 3
    assert _loadings(featured) == ["eager"] * 3
    assert all(a.get("fetchpriority") != "high" for a in featured)

    latest = _managed(page.select("[data-maatlog-component='latest'] .maatlog-post-card img"))
    assert len(latest) == 9
    assert _loadings(latest) == ["eager"] * 6 + ["lazy"] * 3

    managed = _managed(page.select("img"))
    assert len(managed) == 12
    assert _loadings(managed) == ["eager"] * 9 + ["lazy"] * 3
    assert all(a.get("fetchpriority") != "high" for a in managed)


def test_post_top_and_hero_share_one_high(main_site: BuiltSite) -> None:
    """post1 (top+hero): the top image wins the single high slot."""
    page = _page(main_site, "post1")
    imgs = page.select("img")
    assert len(imgs) == 2
    managed = _managed(imgs)
    assert len(managed) == 2
    (top,) = page.select("img.maatlog-post-top-image-img")
    (hero,) = page.select("img.maatlog-post-hero-image")
    assert top["loading"] == "eager"
    assert top["fetchpriority"] == "high"
    assert hero["loading"] == "eager"
    assert hero["fetchpriority"] == "auto"


def test_post_top_only_keeps_hero_fallback(main_site: BuiltSite) -> None:
    """post2 (top only): the top image is managed/high; the hero stays a plain fallback."""
    page = _page(main_site, "post2")
    assert len(_managed(page.select("img"))) == 1
    (top,) = _managed(page.select("img.maatlog-post-top-image-img"))
    assert top["loading"] == "eager"
    assert top["fetchpriority"] == "high"
    (hero,) = page.select("img.maatlog-post-hero-image")
    assert hero["src"]
    assert "srcset" not in hero
    assert "loading" not in hero
    assert "fetchpriority" not in hero
    assert "data-maatlog-srcset" not in hero


def test_post_hero_only_is_high(main_site: BuiltSite) -> None:
    """post3 (hero only): the representative image takes the high slot."""
    page = _page(main_site, "post3")
    assert len(_managed(page.select("img"))) == 1
    (hero,) = _managed(page.select("img.maatlog-post-hero-image"))
    assert hero["loading"] == "eager"
    assert hero["fetchpriority"] == "high"
    assert page.select("img.maatlog-post-top-image-img") == []


def test_post_without_images_has_no_managed(main_site: BuiltSite) -> None:
    """post4 (none): no managed markup at all."""
    page = _page(main_site, "post4")
    assert _managed(page.select("img")) == []
    assert page.select("img.maatlog-post-top-image-img") == []
    assert page.select("img.maatlog-post-hero-image") == []


def test_profile_cards_are_all_eager_without_high(main_site: BuiltSite) -> None:
    """Profile: every authored-post card is managed, eager, and never high."""
    page = _page(main_site, "profile")
    assert len(page.select("img")) == 6
    cards = page.select("[data-maatlog-component='profile-posts'] img")
    assert len(cards) == 6
    for attrs in cards:
        assert attrs.get("data-maatlog-srcset") == "w-v1", attrs.get("class")
        assert attrs.get("loading") == "eager", attrs.get("class")
        assert attrs.get("fetchpriority") != "high", attrs.get("class")


def test_showcase_post_list_keeps_single_src_fallback(main_site: BuiltSite) -> None:
    """Directive post-list cards keep single-src fallbacks: no marker, no loading."""
    page = _page(main_site, "showcase")
    assert len(page.select("img")) == 3
    cards = page.select("[data-maatlog-component='post-list'] img")
    assert len(cards) == 3
    for attrs in cards:
        assert attrs["src"]
        assert "srcset" not in attrs
        assert "data-maatlog-srcset" not in attrs
        assert "loading" not in attrs
        assert "fetchpriority" not in attrs


def test_plain_archive_first_six_eager(plain_site: BuiltSite) -> None:
    """featured_count=0 archive: twelve managed cards, first six eager."""
    page = _page(plain_site, "archive")
    managed = _managed(page.select("img"))
    assert len(managed) == 12
    assert _loadings(managed) == ["eager"] * 6 + ["lazy"] * 6
    assert all(a.get("fetchpriority") != "high" for a in managed)


def test_nine_post_archive_first_six_eager(nine_site: BuiltSite) -> None:
    """Nine-post single-page archive: first six eager, last three lazy."""
    page = _page(nine_site, "archive")
    managed = _managed(page.select("img"))
    assert len(managed) == 9
    assert _loadings(managed) == ["eager"] * 6 + ["lazy"] * 3
    assert all(a.get("fetchpriority") != "high" for a in managed)
