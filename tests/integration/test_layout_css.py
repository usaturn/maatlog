"""The stylesheets that ship with the official themes."""

from __future__ import annotations

import pytest
from conftest import ProjectFactory

LAYOUT_PROJECT = {
    "about.rst": "About\n=====\n\nA plain page.\n",
}

NEW_CUSTOM_PROPERTIES = (
    "--maatlog-main-width",
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


def _css_rules(css: str, selector: str) -> list[str]:
    """``selector`` を含むすべてのルール本体（グループセレクタも含む）。"""
    rules: list[str] = []
    needle = f"{selector} {{"
    position = 0
    while True:
        start = css.find(needle, position)
        if start == -1:
            return rules
        end = css.index("}", start)
        rules.append(css[start : end + 1])
        position = end


def _media_block(css: str, query: str) -> str:
    """``.maatlog-layout`` を含む ``@media (<query>) { ... }`` ブロックを返す。"""
    return _media_block_containing(css, query, ".maatlog-layout")


def _media_block_containing(css: str, query: str, marker: str) -> str:
    """``marker`` を含む ``@media (<query>) { ... }`` ブロックを返す。"""
    needle = f"@media ({query}) {{"
    position = 0
    while True:
        start = css.find(needle, position)
        if start == -1:
            msg = f"no @media ({query}) block contains {marker}"
            raise AssertionError(msg)
        depth = 0
        for end in range(css.index("{", start), len(css)):
            if css[end] == "{":
                depth += 1
            elif css[end] == "}":
                depth -= 1
                if depth == 0:
                    block = css[start : end + 1]
                    if marker in block:
                        return block
                    position = end + 1
                    break
        else:
            msg = f"unbalanced @media block: {query}"
            raise AssertionError(msg)


def _normalise(text: str) -> str:
    """連続する空白を1つに潰す（改行位置に依存しない比較用）。"""
    return " ".join(text.split())


def _compact(text: str) -> str:
    """空白をすべて除去する（``calc()`` の改行に依存しない比較用）。"""
    return "".join(text.split())


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


def test_default_wide_layout_gives_spare_width_to_main(
    make_project: ProjectFactory,
) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-layout")
    columns = "grid-template-columns:minmax(0,var(--maatlog-nav-width,15rem))minmax(0,1fr);"

    assert columns in _compact(rule)
    assert 'grid-template-areas: "nav main";' in _normalise(rule)
    assert "max-width: none;" in rule


def test_default_toc_state_adds_a_right_track_without_capping_main(
    make_project: ProjectFactory,
) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    base = _css_rule(css, ".maatlog-layout")
    with_toc = _css_rule(css, ".maatlog-layout-has-toc")
    base_columns = "grid-template-columns:minmax(0,var(--maatlog-nav-width,15rem))minmax(0,1fr);"
    toc_columns = (
        "grid-template-columns:minmax(0,var(--maatlog-nav-width,15rem))"
        "minmax(0,1fr)minmax(0,var(--maatlog-toc-width,14rem));"
    )

    assert base_columns in _compact(base)
    assert toc_columns in _compact(with_toc)
    assert 'grid-template-areas: "nav main toc";' in _normalise(with_toc)
    assert css.index(".maatlog-layout-has-toc {") > css.index(".maatlog-layout {")


def test_default_sizes_sidebars_to_their_tracks(
    make_project: ProjectFactory,
) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    nav = _css_rule(css, ".maatlog-nav")
    toc = _css_rule(css, ".maatlog-toc")

    assert "box-sizing: border-box;" in nav
    assert "width: 100%;" in nav
    assert "max-width: var(--maatlog-nav-width, 15rem);" in nav
    assert "box-sizing: border-box;" in toc
    assert "width: 100%;" in toc
    assert "max-width: var(--maatlog-toc-width, 14rem);" in toc


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


def test_medium_breakpoint_places_the_toc_only_when_there_is_one(
    make_project: ProjectFactory,
) -> None:
    block = _media_block(_stylesheet(make_project, "maatlog-default"), "width <= 64rem")

    assert 'grid-template-areas: "nav main";' in _normalise(_css_rule(block, ".maatlog-layout"))
    assert 'grid-template-areas: "nav toc" "nav main";' in _normalise(_css_rule(block, ".maatlog-layout-has-toc"))
    assert block.index(".maatlog-layout-has-toc {") > block.index(".maatlog-layout {")
    assert "position: static" in _css_rule(block, ".maatlog-toc")


def test_narrow_breakpoint_stacks_both_toc_states(make_project: ProjectFactory) -> None:
    block = _media_block(_stylesheet(make_project, "maatlog-default"), "width <= 48rem")

    assert 'grid-template-areas: "main" "nav";' in _normalise(_css_rule(block, ".maatlog-layout"))
    assert 'grid-template-areas: "toc" "main" "nav";' in _normalise(_css_rule(block, ".maatlog-layout-has-toc"))
    assert block.index(".maatlog-layout-has-toc {") > block.index(".maatlog-layout {")
    assert "position: static" in _css_rule(block, ".maatlog-nav")
    assert "border-top: 1px solid" in _css_rule(block, ".maatlog-nav")
    assert "padding: var(--maatlog-space-md" in _css_rule(block, ".maatlog-banner")


def test_default_no_longer_reserves_a_body_sidebar_column(make_project: ProjectFactory) -> None:
    # サイドバーはレイアウト左カラムへ出たので、本文内グリッドから sidebar 領域を落とす。
    css = _stylesheet(make_project, "maatlog-default")

    assert "body sidebar" not in css
    assert "grid-area: sidebar" not in css


def test_default_ships_no_javascript(make_project: ProjectFactory) -> None:
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()

    assert not result.asset("_static/maatlog.js").exists()


def test_post_list_is_limited_to_the_content_width(make_project: ProjectFactory) -> None:
    # maatlog:post-list は通常ページでは .body 直下に出るため、テーマ側で行長を揃える。
    css = _stylesheet(make_project, "maatlog-default")
    rules = [_normalise(rule) for rule in _css_rules(css, ".maatlog-post-list")]

    assert rules, ".maatlog-post-list のルールが見つからない"
    assert any("width: 100%;" in rule for rule in rules)
    assert any("max-width: var(--maatlog-content-width, 42rem);" in rule for rule in rules)
    assert any("margin-inline: auto;" in rule for rule in rules)
    # 既存のアーカイブ内グリッド配置と下マージン契約は維持する。
    assert any("grid-area: body;" in rule for rule in rules)
    assert any("margin-bottom: 0;" in rule for rule in rules)


def test_default_lets_post_body_fill_the_main_column(
    make_project: ProjectFactory,
) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-post-body")

    assert "width: 100%;" in rule
    assert "max-width: none;" in rule
    assert ".maatlog-layout-page-normal .body > section > :not(.maatlog-post-list)" not in css


def test_normal_and_post_page_post_lists_fill_the_main_column(
    make_project: ProjectFactory,
) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    desktop = css.split("@media", 1)[0]
    rule = _css_rule(desktop, ".maatlog-layout-page-normal .maatlog-post-list")

    assert ".maatlog-layout-page-post .maatlog-post-list" in desktop
    assert ".maatlog-layout-page-normal .body > section > .maatlog-post-list" not in desktop
    assert "width: 100%;" in rule
    assert "max-width: none;" in rule


def test_medium_breakpoint_resets_normal_post_list_breakout(
    make_project: ProjectFactory,
) -> None:
    block = _media_block(_stylesheet(make_project, "maatlog-default"), "width <= 64rem")
    rule = _css_rule(
        block,
        ".maatlog-layout-page-normal .body > section > .maatlog-post-list",
    )

    assert "width: 100%;" in rule
    assert "max-width: none;" in rule


def test_narrow_breakpoint_keeps_post_containers_inside_main(
    make_project: ProjectFactory,
) -> None:
    block = _media_block_containing(
        _stylesheet(make_project, "maatlog-default"),
        "width <= 48rem",
        ".maatlog-archive",
    )
    rule = _css_rule(block, ".maatlog-archive")

    assert "max-width: 100%;" in rule
