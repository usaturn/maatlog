"""パレット追従のシンタックスハイライト（Theme API 1.6）。

パレット CSS そのものの契約は tests/integration/test_palettes.py が持つ。
ここは Pygments スタイルの解決と、書き出される CSS の切り替わりだけを見る。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import BuildResult, ProjectFactory

from maatlog.theme_api import resolve_pygments_style

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
_THEME_FIXTURE_PREFIX = f"import sys\nsys.path.insert(0, {str(_FIXTURES_DIR)!r})\n"
_THEME_FIXTURE_EXTENSIONS = ("maatlog_theme_fixtures",)

PROJECT = {"about.rst": "About\n=====\n\nBody text.\n"}


@pytest.mark.parametrize(
    ("palette", "expected"),
    [
        (None, "github-dark"),
        ("indigo", "github-dark"),
        ("github", "github-dark"),
        ("solarized", "solarized-dark"),
        ("nord", "nord-darker"),
        ("neon", "dracula"),
    ],
)
def test_resolved_style_follows_the_selected_palette(
    make_project: ProjectFactory, palette: str | None, expected: str
) -> None:
    config = {} if palette is None else {"maatlog_palette": palette}
    result = make_project(files=PROJECT, config=config).build()

    assert resolve_pygments_style(result.app) == expected


def test_an_explicit_conf_py_style_keeps_maatlog_out(make_project: ProjectFactory) -> None:
    # 作者の明示的な選択は丸ごと勝たせる。片方だけ上書きして対を壊さない。
    result = make_project(
        files=PROJECT,
        config={"maatlog_palette": "solarized", "pygments_style": "monokai"},
    ).build()

    assert resolve_pygments_style(result.app) is None


def test_a_palette_unaware_theme_resolves_no_style(make_project: ProjectFactory) -> None:
    result = make_project(
        files=PROJECT,
        theme="standalone",
        extensions=_THEME_FIXTURE_EXTENSIONS,
        conf_py_prefix=_THEME_FIXTURE_PREFIX,
    ).build()

    assert resolve_pygments_style(result.app) is None


# 各スタイルの Keyword 色。互いに重複しないので取り違えを検出できる。
KEYWORD_COLOURS = {
    "github-dark": "#ff7b72",
    "solarized-dark": "#859900",
    "nord-darker": "#81a1c1",
    "dracula": "#ff79c6",
    "monokai": "#66d9ef",
}


def _pygments_css(result: BuildResult, relative: str) -> str:
    return result.asset(f"_static/{relative}").read_text(encoding="utf-8").lower()


@pytest.mark.parametrize(
    ("palette", "style"),
    [("solarized", "solarized-dark"), ("nord", "nord-darker"), ("neon", "dracula")],
)
def test_selected_palette_rewrites_both_pygments_stylesheets(
    make_project: ProjectFactory, palette: str, style: str
) -> None:
    result = make_project(files=PROJECT, config={"maatlog_palette": palette}).build()

    for relative in ("pygments.css", "pygments_dark.css"):
        css = _pygments_css(result, relative)
        assert KEYWORD_COLOURS[style] in css, relative
        assert KEYWORD_COLOURS["github-dark"] not in css, relative


def test_the_default_palette_keeps_the_current_output(make_project: ProjectFactory) -> None:
    # 既定サイトの pygments.css は現状（github-dark）と一致する。
    result = make_project(files=PROJECT).build()

    assert KEYWORD_COLOURS["github-dark"] in _pygments_css(result, "pygments.css")


def test_the_dark_stylesheet_link_survives_the_swap(make_project: ProjectFactory) -> None:
    # maatlog.js の media 書き換えはこの <link> の id に依存する。
    result = make_project(files=PROJECT, config={"maatlog_palette": "neon"}).build()
    page = result.html("about.html")
    # conftest の HtmlPage は #id セレクタを持たない。属性セレクタで書く。
    link = page.select_one("link[id='pygments_dark_css']")

    assert link is not None
    assert link["media"] == "(prefers-color-scheme: dark)"
    assert "pygments_dark.css" in link["href"]


def test_a_declared_palette_does_not_create_a_missing_dark_highlighter(make_project: ProjectFactory) -> None:
    result = make_project(
        files=PROJECT,
        theme="no-dark-pygments",
        config={"maatlog_palette": "fancy"},
        extensions=_THEME_FIXTURE_EXTENSIONS,
        conf_py_prefix=_THEME_FIXTURE_PREFIX,
    ).build()

    assert resolve_pygments_style(result.app) == "dracula"
    assert KEYWORD_COLOURS["dracula"] in _pygments_css(result, "pygments.css")
    assert getattr(result.app.builder, "dark_highlighter", None) is None
    assert result.html("about.html").select_one("link[id='pygments_dark_css']") is None
    assert not result.asset("_static/pygments_dark.css").exists()


def test_an_explicit_conf_py_style_wins_and_dark_stays_on_theme_conf(make_project: ProjectFactory) -> None:
    result = make_project(
        files=PROJECT,
        config={"maatlog_palette": "solarized", "pygments_style": "monokai"},
    ).build()

    assert KEYWORD_COLOURS["monokai"] in _pygments_css(result, "pygments.css")
    # ダークはテーマ属性由来のまま。MaatLog は触らない。
    assert KEYWORD_COLOURS["github-dark"] in _pygments_css(result, "pygments_dark.css")


def test_a_palette_unaware_theme_keeps_its_theme_conf_style(make_project: ProjectFactory) -> None:
    result = make_project(
        files=PROJECT,
        theme="standalone",
        extensions=_THEME_FIXTURE_EXTENSIONS,
        conf_py_prefix=_THEME_FIXTURE_PREFIX,
    ).build()

    assert result.asset("_static/pygments.css").is_file()


def test_a_document_only_builder_does_not_fail(make_project: ProjectFactory) -> None:
    # 完全な HTML ビルダー以外では何もしない（既存テストと同じ text を使う）。
    result = make_project(files=PROJECT, builder="text", config={"maatlog_palette": "neon"}).build()

    assert result.app.builder.name == "text"
    assert resolve_pygments_style(result.app) is None


def _fixture_project(make_project: ProjectFactory, **config: object) -> BuildResult:
    return make_project(
        files=PROJECT,
        theme="partial-pygments",
        config=config,
        extensions=_THEME_FIXTURE_EXTENSIONS,
        conf_py_prefix=_THEME_FIXTURE_PREFIX,
    ).build()


def test_a_declared_palette_overrides_theme_conf(make_project: ProjectFactory) -> None:
    result = _fixture_project(make_project, maatlog_palette="fancy")

    assert resolve_pygments_style(result.app) == "dracula"
    assert KEYWORD_COLOURS["dracula"] in _pygments_css(result, "pygments.css")


def test_an_undeclared_palette_falls_back_to_theme_conf(make_project: ProjectFactory) -> None:
    # plain は [maatlog.pygments] に無い。theme.conf の monokai のまま。
    result = _fixture_project(make_project, maatlog_palette="plain")

    assert resolve_pygments_style(result.app) is None
    assert KEYWORD_COLOURS["monokai"] in _pygments_css(result, "pygments.css")
