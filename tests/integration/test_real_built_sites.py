"""Provider tests for the lazy real-image sites (Issue #315)."""

from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen

from acceptance.built_sites import BuiltSites
from acceptance.real_built_sites import (
    archive_count_site,
    base_theme_site,
    format_site,
    named_source_site,
    no_rail_site,
    override_theme_site,
    scroll_site,
    standard_site,
)


def test_accessors_map_to_distinct_keys() -> None:
    keys = [
        standard_site("html", enabled=True)[0],
        standard_site("dirhtml", enabled=True)[0],
        scroll_site("html")[0],
        archive_count_site(1)[0],
        no_rail_site()[0],
        base_theme_site()[0],
        override_theme_site()[0],
        format_site("still.webp", enabled=True)[0],
        named_source_site("my photo.png")[0],
    ]

    assert len(keys) == len(set(keys))


def test_same_parameters_map_to_the_same_key() -> None:
    assert standard_site("html", enabled=True)[0] == standard_site("html", enabled=True)[0]


def test_scroll_site_is_selected_by_page_size() -> None:
    standard_key = standard_site("html", enabled=True)[0]
    scroll_key = scroll_site("html")[0]

    assert ("maatlog_page_size", ("int", 20)) in standard_key.config
    assert ("maatlog_page_size", ("int", 4)) in scroll_key.config
    assert standard_key != scroll_key


def test_enabled_selects_the_responsive_images_flag() -> None:
    enabled_key = standard_site("html", enabled=True)[0]
    disabled_key = standard_site("html", enabled=False)[0]

    assert enabled_key.responsive_images is True
    assert disabled_key.responsive_images is False
    assert enabled_key != disabled_key


def test_format_site_builds_and_serves(tmp_path: Path) -> None:
    """One real-build smoke test on the smallest site (3 posts, WebP source)."""
    key, build = format_site("still.webp", enabled=True)

    with BuiltSites(tmp_path) as sites:
        built = sites.get(key, build)

        assert (built.outdir / "index.html").is_file()
        with urlopen(built.base_url, timeout=10) as response:  # noqa: S310 - loopback test server
            assert response.status == 200
