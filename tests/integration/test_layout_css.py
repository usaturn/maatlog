"""The stylesheets that ship with the official themes."""

from __future__ import annotations

import pytest
from conftest import ProjectFactory

LAYOUT_PROJECT = {
    "about.rst": "About\n=====\n\nA plain page.\n",
}

NEW_CUSTOM_PROPERTIES = (
    "--maatlog-nav-width",
    "--maatlog-toc-width",
    "--maatlog-banner-background",
    "--maatlog-banner-height",
)


def _stylesheet(make_project: ProjectFactory, theme: str) -> str:
    result = make_project(files=LAYOUT_PROJECT, theme=theme).build()
    return result.asset("_static/maatlog.css").read_text(encoding="utf-8")


def _css_rule(css: str, selector: str) -> str:
    start = css.index(f"{selector} {{")
    return css[start : css.index("}", start) + 1]


def test_default_keeps_required_shell_component_styles(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")

    assert "left: -9999px" in _css_rule(css, ".maatlog-skip-link")
    assert "z-index: 1" in _css_rule(css, ".maatlog-skip-link:focus")
    assert "margin: 0" in _css_rule(css, ".maatlog-banner-title")
    assert "color: var(--maatlog-color-muted" in _css_rule(css, ".maatlog-banner-tagline")
    assert "list-style: none" in _css_rule(css, ".maatlog-toc-posts")


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
@pytest.mark.parametrize("prop", NEW_CUSTOM_PROPERTIES)
def test_new_custom_properties_are_declared(make_project: ProjectFactory, theme: str, prop: str) -> None:
    assert prop in _stylesheet(make_project, theme)


def test_base_neutralises_the_basic_theme_float(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-base")

    assert ".maatlog-layout" in css
    assert ".maatlog-layout-main .documentwrapper" in css
    assert "float: none" in css


def test_base_styles_the_skip_link(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-base")

    assert ".maatlog-skip-link" in css


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_literal_blocks_scroll_within_main_content(make_project: ProjectFactory, theme: str) -> None:
    css = _stylesheet(make_project, theme)

    rule = _css_rule(css, ".maatlog-layout-main pre")
    assert "max-width: 100%" in rule
    assert "overflow: auto hidden" in rule


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_highlight_blocks_scroll_within_main_content(make_project: ProjectFactory, theme: str) -> None:
    css = _stylesheet(make_project, theme)

    rule = _css_rule(css, ".maatlog-layout-main .highlight")
    assert "overflow-x: auto" in rule


def test_default_lays_out_three_columns(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")

    assert ".maatlog-layout" in css
    assert "var(--maatlog-nav-width" in css
    assert "var(--maatlog-toc-width" in css
    assert "grid-template-columns" in css


def test_default_makes_the_sidebars_sticky(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")

    assert "position: sticky" in css


def test_default_has_both_breakpoints(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")

    assert "@media (width <= 64rem)" in css
    assert "@media (width <= 48rem)" in css


def test_default_uses_overflow_wrap_without_deprecated_word_break(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")

    assert "overflow-wrap: anywhere" in css
    assert "word-break: break-word" not in css


def test_default_no_longer_reserves_a_body_sidebar_column(make_project: ProjectFactory) -> None:
    # サイドバーはレイアウト左カラムへ出たので、本文内グリッドから sidebar 領域を落とす。
    css = _stylesheet(make_project, "maatlog-default")

    assert "body sidebar" not in css
    assert "grid-area: sidebar" not in css


def test_default_ships_no_javascript(make_project: ProjectFactory) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()

    assert not result.asset("_static/maatlog.js").exists()
