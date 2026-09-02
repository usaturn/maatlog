"""バナーのテーマ切替ボタンの HTML 契約。"""

from __future__ import annotations

import pytest
from conftest import ProjectFactory

TOGGLE_PROJECT = {
    "about.rst": "About\n=====\n\nA plain page.\n",
}


def _page(make_project: ProjectFactory, theme: str):
    return make_project(files=TOGGLE_PROJECT, theme=theme).build().html("about.html")


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_banner_renders_a_native_toggle_button(make_project: ProjectFactory, theme: str) -> None:
    button = _page(make_project, theme).select_one('.maatlog-theme-toggle[data-maatlog-component="theme-toggle"]')

    assert button is not None
    # ネイティブ button ならキーボード操作（Tab / Enter / Space）が標準で効く。
    assert button["type"] == "button"


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_toggle_reports_its_state_to_assistive_technology(make_project: ProjectFactory, theme: str) -> None:
    button = _page(make_project, theme).select_one(".maatlog-theme-toggle")

    assert button is not None
    assert button["aria-pressed"] == "false"


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_toggle_has_an_accessible_name_that_is_not_an_icon(make_project: ProjectFactory, theme: str) -> None:
    page = _page(make_project, theme)

    assert page.select_one(".maatlog-theme-toggle-label") is not None
    assert "Dark theme" in page.text


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_toggle_signals_state_with_shape_not_colour_alone(make_project: ProjectFactory, theme: str) -> None:
    page = _page(make_project, theme)

    assert page.select_one(".maatlog-theme-toggle-icon-light") is not None
    assert page.select_one(".maatlog-theme-toggle-icon-dark") is not None


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_icons_are_hidden_from_assistive_technology(make_project: ProjectFactory, theme: str) -> None:
    icons = _page(make_project, theme).select(".maatlog-theme-toggle-icon")

    assert len(icons) == 2
    assert all(icon["aria-hidden"] == "true" for icon in icons)


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_banner_groups_search_and_toggle(make_project: ProjectFactory, theme: str) -> None:
    page = _page(make_project, theme)

    assert page.select_one(".maatlog-banner-actions .maatlog-theme-toggle") is not None
    assert page.select_one(".maatlog-banner-actions .maatlog-banner-search") is not None


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_toggle_is_hidden_until_the_theme_runtime_runs(make_project: ProjectFactory, theme: str) -> None:
    css = (
        make_project(files=TOGGLE_PROJECT, theme=theme)
        .build()
        .asset("_static/maatlog.css")
        .read_text(encoding="utf-8")
    )

    assert ".maatlog-theme-toggle {" in css
    assert ".maatlog-js .maatlog-theme-toggle {" in css


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_runtime_wires_the_toggle(make_project: ProjectFactory, theme: str) -> None:
    script = (
        make_project(files=TOGGLE_PROJECT, theme=theme).build().asset("_static/maatlog.js").read_text(encoding="utf-8")
    )

    assert "DOMContentLoaded" in script
    assert "aria-pressed" in script
    assert '"click"' in script
