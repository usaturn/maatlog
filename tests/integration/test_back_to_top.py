"""Issue #61: Back to Top のマークアップ、CSS 契約、runtime 登録。"""

from __future__ import annotations

import re

import pytest
from conftest import HtmlPage, ProjectFactory

BACK_TO_TOP_PROJECT = {
    "about.rst": "About\n=====\n\nA plain page.\n",
}


def _html(make_project: ProjectFactory, theme: str, page: str = "about.html") -> HtmlPage:
    return make_project(files=BACK_TO_TOP_PROJECT, theme=theme).build().html(page)


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_page_ships_exactly_one_back_to_top_button(make_project: ProjectFactory, theme: str) -> None:
    page = _html(make_project, theme)

    buttons = page.select('[data-maatlog-component="back-to-top"]')

    assert len(buttons) == 1


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_button_starts_hidden_and_is_labelled(make_project: ProjectFactory, theme: str) -> None:
    button = _html(make_project, theme).select_one(".maatlog-back-to-top")

    assert button is not None
    assert button.get("type") == "button"
    # JavaScript 無効時に出てはならないので、初期状態は hidden。
    assert "hidden" in button
    assert button.get("aria-label")


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_button_icon_is_hidden_from_assistive_technology(make_project: ProjectFactory, theme: str) -> None:
    icon = _html(make_project, theme).select_one(".maatlog-back-to-top .maatlog-back-to-top-icon")

    assert icon is not None
    assert icon.get("aria-hidden") == "true"
    assert icon.get("focusable") == "false"


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_button_sits_outside_the_layout_element(make_project: ProjectFactory, theme: str) -> None:
    # position: fixed が祖先の containing block 化に巻き込まれないよう、
    # レイアウト要素の外側に出す。
    page = _html(make_project, theme)

    assert page.select_one('[data-maatlog-component="layout"] .maatlog-back-to-top') is None


def _css(make_project: ProjectFactory, theme: str) -> str:
    return (
        make_project(files=BACK_TO_TOP_PROJECT, theme=theme)
        .build()
        .asset("_static/maatlog.css")
        .read_text(encoding="utf-8")
    )


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_css_pins_the_button_to_the_lower_fixed_ui_band(make_project: ProjectFactory, theme: str) -> None:
    css = _css(make_project, theme)

    assert "--maatlog-z-back-to-top: 30;" in css
    assert "--maatlog-back-to-top-size:" in css
    assert ".maatlog-back-to-top {" in css
    assert "z-index: var(--maatlog-z-back-to-top, 30);" in css


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_css_keeps_the_button_clear_of_device_safe_areas(make_project: ProjectFactory, theme: str) -> None:
    css = _css(make_project, theme)

    assert "env(safe-area-inset-bottom, 0px)" in css
    assert "env(safe-area-inset-right, 0px)" in css


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_css_hides_the_button_while_the_mobile_drawer_is_open(make_project: ProjectFactory, theme: str) -> None:
    # ドロワー展開中はページがスクロールできないうえ、backdrop と重なる。
    css = _css(make_project, theme)

    assert "html.maatlog-sidebar-open .maatlog-back-to-top" in css


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_back_to_top_layer_stays_below_the_sidebar_band(make_project: ProjectFactory, theme: str) -> None:
    css = _css(make_project, theme)
    back_to_top = re.search(r"--maatlog-z-back-to-top:\s*(\d+);", css)
    backdrop = re.search(r"--maatlog-z-sidebar-backdrop:\s*(\d+);", css)

    assert back_to_top is not None
    assert backdrop is not None
    assert int(back_to_top.group(1)) < int(backdrop.group(1))


def _runtime(make_project: ProjectFactory) -> str:
    return (
        make_project(files=BACK_TO_TOP_PROJECT, theme="maatlog-default")
        .build()
        .asset("_static/maatlog.js")
        .read_text(encoding="utf-8")
    )


def test_runtime_registers_the_back_to_top_enhancer(make_project: ProjectFactory) -> None:
    script = _runtime(make_project)

    assert 'registerEnhancer("back-to-top"' in script
    assert "selector: '[data-maatlog-component=\"back-to-top\"]'" in script


def test_runtime_uses_the_600px_threshold(make_project: ProjectFactory) -> None:
    script = _runtime(make_project)

    assert "BACK_TO_TOP_THRESHOLD = 600" in script


def test_runtime_listens_to_scroll_passively_and_throttles_with_raf(make_project: ProjectFactory) -> None:
    # 性能要件: passive listener + rAF、DOM 更新は状態変化時のみ。
    script = _runtime(make_project)

    assert '"scroll", schedule, { passive: true }' in script
    assert "requestAnimationFrame(update)" in script


def test_runtime_respects_reduced_motion_on_click(make_project: ProjectFactory) -> None:
    script = _runtime(make_project)

    assert "(prefers-reduced-motion: reduce)" in script
    assert 'behavior: reduced ? "auto" : "smooth"' in script


def test_theme_ships_a_single_runtime_file(make_project: ProjectFactory) -> None:
    # 機能別 script を増やさない契約。
    static_dir = make_project(files=BACK_TO_TOP_PROJECT, theme="maatlog-default").build().asset("_static")

    assert sorted(path.name for path in static_dir.glob("maatlog*.js")) == ["maatlog.js"]
