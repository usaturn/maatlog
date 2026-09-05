"""Issue #65: mobile sidebar DOM hooks, CSS gate, and runtime enhancer."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ProjectFactory

ROOT = Path(__file__).resolve().parents[2]

SIDEBAR_PROJECT = {
    "about.rst": "About\n=====\n\nA plain page.\n",
}


def _page(make_project: ProjectFactory, theme: str = "maatlog-default"):
    return make_project(files=SIDEBAR_PROJECT, theme=theme).build().html("about.html")


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_sidebar_has_stable_id(make_project: ProjectFactory, theme: str) -> None:
    page = _page(make_project, theme)
    sidebar = page.select_one(".maatlog-sidebar[data-maatlog-component='sidebar']")

    assert sidebar is not None
    assert sidebar.get("id") == "maatlog-sidebar"
    assert 'id="maatlog-sidebar"' in page.text


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_banner_has_sidebar_toggle(make_project: ProjectFactory, theme: str) -> None:
    toggle = _page(make_project, theme).select_one(".maatlog-sidebar-toggle")

    assert toggle is not None
    assert toggle.get("type") == "button"
    assert toggle.get("data-maatlog-toggle") == "sidebar"
    assert toggle.get("aria-controls") == "maatlog-sidebar"
    assert toggle.get("aria-expanded") == "false"
    assert toggle.get("aria-label")
    # The runtime swaps the label on open/close; it must reuse the translated
    # strings from the template instead of hardcoding English.
    assert toggle.get("data-maatlog-label-open") == toggle.get("aria-label")
    assert toggle.get("data-maatlog-label-close")


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_toggle_lives_in_banner_actions(make_project: ProjectFactory, theme: str) -> None:
    page = _page(make_project, theme)

    assert page.select_one(".maatlog-banner-actions .maatlog-sidebar-toggle") is not None


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_built_css_gates_drawer_on_maatlog_js(make_project: ProjectFactory, theme: str) -> None:
    css = (
        make_project(files=SIDEBAR_PROJECT, theme=theme)
        .build()
        .asset("_static/maatlog.css")
        .read_text(encoding="utf-8")
    )

    assert "--maatlog-z-sidebar-backdrop" in css
    assert "--maatlog-z-sidebar-drawer" in css
    assert "--maatlog-z-sidebar-toggle" in css
    assert "--maatlog-sidebar-drawer-width" in css
    assert ".maatlog-sidebar-toggle" in css
    assert ".maatlog-js .maatlog-sidebar-toggle" in css
    assert "html.maatlog-sidebar-open .maatlog-sidebar-toggle" in css
    assert "maatlog-sidebar-backdrop" in css
    assert "html.maatlog-sidebar-open" in css


def test_base_and_default_css_sources_define_drawer_contract() -> None:
    for rel in (
        "src/maatlog/themes/maatlog-base/static/maatlog.css",
        "src/maatlog/themes/maatlog-default/static/maatlog.css",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "--maatlog-z-sidebar-backdrop" in text
        assert "--maatlog-z-sidebar-drawer" in text
        assert "--maatlog-z-sidebar-toggle" in text
        assert ".maatlog-js .maatlog-sidebar-toggle" in text
        assert "html.maatlog-sidebar-open .maatlog-sidebar-toggle" in text
        assert "maatlog-sidebar-backdrop" in text
        assert "html.maatlog-sidebar-open" in text


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_runtime_registers_mobile_sidebar_enhancer(make_project: ProjectFactory, theme: str) -> None:
    script = (
        make_project(files=SIDEBAR_PROJECT, theme=theme)
        .build()
        .asset("_static/maatlog.js")
        .read_text(encoding="utf-8")
    )

    assert 'registerEnhancer("mobile-sidebar"' in script
    assert "enhanceMobileSidebar" in script
    assert "maatlog-sidebar-open" in script
    assert "(max-width: 48rem)" in script
