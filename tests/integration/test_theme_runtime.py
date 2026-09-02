"""テーマ JavaScript の配信契約。"""

from __future__ import annotations

import re

import pytest
from conftest import ProjectFactory

RUNTIME_PROJECT = {
    "about.rst": "About\n=====\n\nA plain page.\n",
}


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_official_themes_ship_the_theme_javascript(make_project: ProjectFactory, theme: str) -> None:
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()

    assert result.asset("_static/maatlog.js").exists()


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_is_render_blocking_in_the_head(make_project: ProjectFactory, theme: str) -> None:
    # 保存済みテーマを初期描画前に反映するため、defer も module もあってはならない。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    page = result.html("about.html")
    head = page.text[: page.text.index("</head>")]

    match = re.search(r"<script src=\"([^\"]*maatlog\.js[^\"]*)\"\s*>\s*</script>", head)
    assert match is not None, "maatlog.js の <script> が head にない"
    assert "defer" not in match.group(0)
    assert "async" not in match.group(0)
    assert "type=" not in match.group(0)


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_url_carries_a_cache_busting_version(make_project: ProjectFactory, theme: str) -> None:
    from maatlog.version import PACKAGE_VERSION

    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()

    assert f"_static/maatlog.js?v={PACKAGE_VERSION}" in result.html("about.html").text


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_runs_before_the_pygments_dark_link_is_needed(
    make_project: ProjectFactory, theme: str
) -> None:
    # JS は #pygments_dark_css の media を書き換える。link が script より前にあること。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    text = result.html("about.html").text

    assert text.index("pygments_dark_css") < text.index("maatlog.js")


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_marks_the_document_and_resolves_the_theme(make_project: ProjectFactory, theme: str) -> None:
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")

    assert 'classList.add("maatlog-js")' in script
    assert "maatlog-theme" in script
    assert "pygments_dark_css" in script


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_marks_the_toc_heading_in_view(make_project: ProjectFactory, theme: str) -> None:
    # TOC の現在位置は aria-current="true" で表す（Sidebar の "page" とは別の意味）。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")

    assert ".maatlog-toc-headings" in script
    assert "aria-current" in script
    assert "IntersectionObserver" in script


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_toc_scrollspy_is_progressive_enhancement(make_project: ProjectFactory, theme: str) -> None:
    # IntersectionObserver が無い環境では何もせずに戻る。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")

    assert 'typeof IntersectionObserver !== "function"' in script
