"""The stylesheets that ship with the official themes."""

from __future__ import annotations

import re

import pytest
from conftest import ProjectFactory

LAYOUT_PROJECT = {
    "about.rst": "About\n=====\n\nA plain page.\n",
}

POST_LINE_LENGTH_PROJECT = {
    "post.rst": """:maatlog-post: true
:maatlog-slug: line-length
:maatlog-published-at: 2026-07-31T09:00:00Z

Title
=====

Paragraph one.

- list item
""",
}

NEW_CUSTOM_PROPERTIES = (
    "--maatlog-main-width",
    "--maatlog-nav-width",
    "--maatlog-rail-width",
    "--maatlog-author-avatar-size",
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


def _css_rules_by_selector_prefix(css: str, prefix: str) -> list[str]:
    """selector が ``prefix`` から始まるすべてのルール本体。

    ``::after`` / ``::before`` などの pseudo-element は生成コンテンツの契約が
    別にあるため対象外とし、``:hover`` 等の pseudo-class は対象に含める。
    """
    rules: list[str] = []
    position = 0
    while True:
        start = css.find(prefix, position)
        if start == -1:
            return rules
        open_brace = css.index("{", start)
        selector = css[start:open_brace].strip()
        if not selector[len(prefix) :].startswith("::"):
            end = css.index("}", open_brace)
            rules.append(css[start : end + 1])
        position = open_brace


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


def _supports_block(css: str, condition_head: str) -> str:
    """``@supports (<condition_head>...`` で始まるブロック全体を返す。"""
    needle = f"@supports ({condition_head}"
    start = css.index(needle)
    depth = 0
    for end in range(css.index("{", start), len(css)):
        if css[end] == "{":
            depth += 1
        elif css[end] == "}":
            depth -= 1
            if depth == 0:
                return css[start : end + 1]
    msg = f"unbalanced @supports block: {condition_head}"
    raise AssertionError(msg)


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


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_width_tokens_use_fluid_clamp(make_project: ProjectFactory, theme: str) -> None:
    # Issue #110: 固定 rem ではなく clamp(floor, preferred, ceiling) で wide viewport に追従する。
    css = _stylesheet(make_project, theme)
    root = _css_rule(css, ":root")

    assert re.search(r"--maatlog-content-width:\s*clamp\(", root)
    assert re.search(r"--maatlog-main-width:\s*clamp\(", root)
    assert "42rem" in root and "60rem" in root
    assert "50rem" in root and "72rem" in root


def test_base_neutralises_the_basic_theme_float(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-base")

    assert ".maatlog-layout" in css
    assert ".maatlog-layout-main .documentwrapper" in css
    assert "float: none" in css


def test_base_styles_the_skip_link(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-base")

    assert ".maatlog-skip-link" in css


POST_TAXONOMY_SELECTORS = (
    ".maatlog-post-taxonomies",
    ".maatlog-post-categories",
    ".maatlog-post-tags",
    ".maatlog-category-badge",
)


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
@pytest.mark.parametrize("selector", POST_TAXONOMY_SELECTORS)
def test_post_taxonomy_styles_are_declared(make_project: ProjectFactory, theme: str, selector: str) -> None:
    css = _stylesheet(make_project, theme)
    assert selector in css


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_post_taxonomy_containers_use_flex_gap(make_project: ProjectFactory, theme: str) -> None:
    css = _stylesheet(make_project, theme)

    taxonomies_rule = _css_rule(css, ".maatlog-post-taxonomies")
    assert "display: flex" in taxonomies_rule
    assert "gap:" in taxonomies_rule

    grouped_rules = _css_rules(css, ".maatlog-post-tags")
    assert grouped_rules
    assert any("inline-flex" in rule and "gap:" in rule for rule in grouped_rules)


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_visually_hidden_is_out_of_flow(make_project: ProjectFactory, theme: str) -> None:
    css = _stylesheet(make_project, theme)
    rule = _css_rule(css, ".maatlog-visually-hidden")

    assert "position: absolute" in rule
    assert "clip-path: inset(50%)" in rule


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


def test_default_rail_state_adds_a_right_track_without_capping_main(
    make_project: ProjectFactory,
) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    base = _css_rule(css, ".maatlog-layout")
    with_rail = _css_rule(css, ".maatlog-layout-has-rail")
    base_columns = "grid-template-columns:minmax(0,var(--maatlog-nav-width,15rem))minmax(0,1fr);"
    rail_columns = (
        "grid-template-columns:minmax(0,var(--maatlog-nav-width,15rem))"
        "minmax(0,1fr)minmax(0,var(--maatlog-rail-width,14rem));"
    )

    assert base_columns in _compact(base)
    assert rail_columns in _compact(with_rail)
    assert 'grid-template-areas: "nav main rail";' in _normalise(with_rail)
    assert css.index(".maatlog-layout-has-rail {") > css.index(".maatlog-layout {")


def test_default_sizes_sidebars_to_their_tracks(
    make_project: ProjectFactory,
) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    nav = _css_rule(css, ".maatlog-nav")
    rail = _css_rule(css, ".maatlog-right-rail")

    assert "box-sizing: border-box;" in nav
    assert "width: 100%;" in nav
    assert "max-width: var(--maatlog-nav-width, 15rem);" in nav
    assert "box-sizing: border-box;" in rail
    assert "width: 100%;" in rail
    assert "max-width: var(--maatlog-rail-width, 14rem);" in rail


def test_default_scrolls_the_toc_inside_a_sticky_rail(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rail = _css_rule(css, ".maatlog-right-rail")
    toc = _css_rule(css, ".maatlog-toc")

    assert "position: sticky" in rail
    assert "flex-direction: column" in rail
    assert "flex: 1 1 auto" in toc
    assert "overflow-y: auto" in toc
    # flex アイテムの既定 min-height: auto は内部スクロールを殺す。
    # 下限 8rem は Summary が rail 高を超えた時に TOC が 0px へ潰れるのを防ぐ。
    assert "min-height: 8rem" in toc
    assert "min-height: 0" not in toc


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


def test_medium_breakpoint_places_the_rail_above_the_content(
    make_project: ProjectFactory,
) -> None:
    block = _media_block(_stylesheet(make_project, "maatlog-default"), "width <= 64rem")

    assert 'grid-template-areas: "nav main";' in _normalise(_css_rule(block, ".maatlog-layout"))
    assert 'grid-template-areas: "nav rail" "nav main";' in _normalise(_css_rule(block, ".maatlog-layout-has-rail"))
    assert block.index(".maatlog-layout-has-rail {") > block.index(".maatlog-layout {")
    assert "position: static" in _css_rule(block, ".maatlog-right-rail")
    # rail が flex コンテナでなくなる幅では、base の下限 8rem は潰れ防止ではなく
    # 内容の下に残る下駄になる。max-height / overflow-y と同じ場所で解除する。
    assert "min-height: 0" in _css_rule(block, ".maatlog-toc")


def test_narrow_breakpoint_stacks_the_summary_after_the_content(
    make_project: ProjectFactory,
) -> None:
    block = _media_block(_stylesheet(make_project, "maatlog-default"), "width <= 48rem")
    layout = _css_rule(block, ".maatlog-layout")

    assert "display: flex" in layout
    assert "flex-direction: column" in layout
    # 横は引き伸ばし、本文は縮小可能にしないと幅広テーブルでページが広がる。
    assert "align-items: stretch" in layout
    assert "min-width: 0" in _css_rule(block, ".maatlog-layout-main")
    # rail のボックスを外し、TOC は本文の上、要約は本文の下へ分ける。
    assert "display: contents" in _css_rule(block, ".maatlog-right-rail")
    assert "order: 1" in _css_rule(block, ".maatlog-toc")
    assert "order: 2" in _css_rule(block, ".maatlog-layout-main")
    assert "order: 3" in _css_rule(block, ".maatlog-author-summary")
    assert "order: 4" in _css_rule(block, ".maatlog-nav")
    assert "position: static" in _css_rule(block, ".maatlog-nav")
    assert "border-top: 1px solid" in _css_rule(block, ".maatlog-nav")
    assert "padding: var(--maatlog-space-md" in _css_rule(block, ".maatlog-banner")


def test_default_no_longer_reserves_a_body_sidebar_column(make_project: ProjectFactory) -> None:
    # サイドバーはレイアウト左カラムへ出たので、本文内グリッドから sidebar 領域を落とす。
    css = _stylesheet(make_project, "maatlog-default")

    assert "body sidebar" not in css
    assert "grid-area: sidebar" not in css


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
    # Palette media queries sit at the top; desktop layout rules follow until a width breakpoint.
    desktop = css.split("@media (width", 1)[0]
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


def test_default_sets_the_blog_font_stack_on_the_body(make_project: ProjectFactory) -> None:
    # basic テーマ由来のブラウザ既定フォントを、ブログ向けのスタックで置き換える。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, "body")

    assert "font-family: var(--maatlog-font-sans" in rule


def test_default_post_body_fills_main_but_caps_prose_line_length(
    make_project: ProjectFactory,
) -> None:
    # コンテナは main いっぱい（既存の幅契約）。行長は子孫の prose 要素側で抑える。
    result = make_project(files=POST_LINE_LENGTH_PROJECT, theme="maatlog-default").build()
    page = result.html("post.html")
    css = result.asset("_static/maatlog.css").read_text(encoding="utf-8")
    container = _css_rule(css, ".maatlog-post-body")

    assert "width: 100%;" in container
    assert "max-width: none;" in container
    assert "line-height: 1.8" in container

    # Sphinx は本文を <section> で包む。直下子セレクタでは <p> に届かない。
    assert page.select_one(".maatlog-post-body section p") is not None

    # prettier が :is() の中を折り返しても壊れないよう、開き括弧までで探す。
    start = css.index(".maatlog-post-body :is(")
    prose = css[start : css.index("}", start)]
    assert "max-width: var(--maatlog-content-width" in prose


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_highlight_code_does_not_inherit_inline_code_spacing(
    make_project: ProjectFactory,
    theme: str,
) -> None:
    css = _stylesheet(make_project, theme)
    rule = _css_rule(css, ".maatlog-layout-main .highlight code")

    assert "padding: 0;" in rule
    assert "border-radius: 0;" in rule
    assert "font-size: 1em;" in rule


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_sticky_offset_is_derived_from_the_banner_height(make_project: ProjectFactory, theme: str) -> None:
    # sticky ヘッダの下に nav / TOC を置くための唯一の値。2 箇所に書くと必ずずれる。
    css = _stylesheet(make_project, theme)
    root = _css_rule(css, ":root")

    assert "--maatlog-sticky-top:" in root
    assert _compact("calc(var(--maatlog-banner-height) + var(--maatlog-space-md))") in _compact(root)


def test_default_sidebars_declare_no_background(make_project: ProjectFactory) -> None:
    # Issue #95: Sidebar / TOC は Main content より目立たせない。巨大な Card にしない。
    css = _stylesheet(make_project, "maatlog-default")

    assert "background: none" in _css_rule(css, ".maatlog-nav")
    assert "background: none" in _css_rule(css, ".maatlog-toc")


def test_default_banner_is_a_sticky_bar_of_a_fixed_height(make_project: ProjectFactory) -> None:
    # Issue #95: 高さ 64px 前後、上下余白なし、垂直中央揃え、Main より前面。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-banner")

    assert "position: sticky" in rule
    assert "top: 0" in rule
    assert "z-index: 10" in rule
    assert "align-items: center" in rule
    assert "min-height: var(--maatlog-banner-height)" in rule
    assert "padding: 0 var(--maatlog-space-lg)" in rule
    assert "background: var(--maatlog-banner-background)" in rule


def test_default_search_input_uses_at_least_16px_font_to_avoid_ios_zoom(make_project: ProjectFactory) -> None:
    # iOS Safari zooms the viewport when a focused input is below 16px.
    rule = _css_rule(_stylesheet(make_project, "maatlog-default"), ".maatlog-search-input")

    assert "font-size: 1rem" in rule


def test_default_sticky_sidebars_clear_the_banner(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-right-rail")

    assert "top: var(--maatlog-sticky-top)" in rule
    assert _compact("calc(100vh - var(--maatlog-sticky-top) - var(--maatlog-space-md))") in _compact(rule)


def test_default_skip_link_stays_above_the_sticky_banner(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")

    assert "z-index: 11" in _css_rule(css, ".maatlog-skip-link:focus")


def test_narrow_banner_wraps_and_restores_vertical_padding(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    block = _media_block_containing(css, "width <= 48rem", ".maatlog-banner")

    assert "flex-wrap: wrap" in block
    assert "padding: var(--maatlog-space-md)" in block


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_taxonomy_lists_have_no_bullets(make_project: ProjectFactory, theme: str) -> None:
    assert "list-style: none" in _css_rule(_stylesheet(make_project, theme), ".maatlog-taxonomy-list")


def test_default_taxonomy_items_are_navigation_rows(make_project: ProjectFactory) -> None:
    # Issue #95: bullet と下線をやめ、ラベル左・カウント右の 1 行にする。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-taxonomy-item")

    assert "display: flex" in rule
    assert "justify-content: space-between" in rule
    assert "text-decoration: none" in rule
    assert "border-radius: var(--maatlog-radius-sm)" in rule


def test_default_taxonomy_hover_and_focus_share_one_surface(make_project: ProjectFactory) -> None:
    # hover だけで状態を示さない。focus-visible でも同じ手掛かりを出す。
    # グループセレクタなので _css_rule では引けない。整形後の 1 行として突き合わせる。
    css = _normalise(_stylesheet(make_project, "maatlog-default"))

    assert (
        ".maatlog-taxonomy-item:hover, .maatlog-taxonomy-item:focus-visible "
        "{ background: var(--maatlog-color-surface-hover); color: var(--maatlog-color-text); }"
    ) in css


def test_default_taxonomy_active_item_uses_the_primary_colour(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, '.maatlog-taxonomy-item[aria-current="page"]')

    assert "color: var(--maatlog-color-primary)" in rule
    assert "background: var(--maatlog-color-surface-hover)" in rule
    assert "font-weight: 600" in rule


def test_default_taxonomy_count_is_muted(make_project: ProjectFactory) -> None:
    assert "color: var(--maatlog-color-muted)" in _css_rule(
        _stylesheet(make_project, "maatlog-default"), ".maatlog-taxonomy-count"
    )


def test_default_taxonomy_heading_is_weaker_than_body_headings(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-taxonomy h2")

    assert "font-size: 0.75rem" in rule
    assert "text-transform: uppercase" in rule
    assert "color: var(--maatlog-color-muted)" in rule


def test_default_nav_toctree_has_no_bullets(make_project: ProjectFactory) -> None:
    # 左 nav の site toctree も Sphinx 素の箇条書きにしない。
    css = _stylesheet(make_project, "maatlog-default")

    assert "list-style: none" in _css_rule(css, ".maatlog-nav-toctree ul")


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_toc_headings_have_no_bullets(make_project: ProjectFactory, theme: str) -> None:
    assert "list-style: none" in _css_rule(_stylesheet(make_project, theme), ".maatlog-toc-headings ul")


def test_default_toc_links_are_quiet_and_undecorated(make_project: ProjectFactory) -> None:
    # Issue #95: 本文より小さく、既定は muted、下線は出さない。
    # ``.maatlog-toc-headings a`` とのグループなので、後ろ側のセレクタで引く。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-toc-posts a")

    assert "text-decoration: none" in rule
    assert "color: var(--maatlog-color-muted)" in rule
    assert "font-size: 0.8125rem" in rule
    assert "border-left: 2px solid transparent" in rule


def test_default_toc_depth_is_one_indent_step(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")

    assert "padding-inline-start: var(--maatlog-space-md)" in _css_rule(css, ".maatlog-toc-headings ul ul")


def test_default_toc_active_heading_is_marked_with_a_rule(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, '.maatlog-toc-headings a[aria-current="true"]')

    assert "color: var(--maatlog-color-primary)" in rule
    assert "border-left-color: var(--maatlog-color-primary)" in rule
    assert "font-weight: 600" in rule


def test_default_banner_ground_is_translucent_where_blur_works(make_project: ProjectFactory) -> None:
    # 地を透かすのは blur が効くときだけ。片方だけでは背後の文字が透けて読めなくなる。
    css = _stylesheet(make_project, "maatlog-default")
    block = _supports_block(css, "backdrop-filter")

    assert "backdrop-filter: blur(" in block
    assert "color-mix(" in block
    assert "var(--maatlog-banner-background)" in block


def test_default_banner_keeps_an_opaque_fallback_ground(make_project: ProjectFactory) -> None:
    # @supports が通らない環境では今日と同じ不透明バナーへ落ちる。
    # スキップリンクも同じトークンを地に使うので、トークン自体は透かさない。
    css = _stylesheet(make_project, "maatlog-default")

    assert "background: var(--maatlog-banner-background)" in _css_rule(css, ".maatlog-banner")
    assert "background: var(--maatlog-banner-background" in _css_rule(css, ".maatlog-skip-link:focus")


def test_default_post_card_is_a_surface_card(make_project: ProjectFactory) -> None:
    # Sphinx 素の枠付きブロックではなく、浮いた surface として見せる。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-post-card")

    assert "background: var(--maatlog-card-background" in rule
    assert "border-radius: var(--maatlog-radius-lg" in rule
    assert "box-shadow: var(--maatlog-shadow-sm" in rule
    assert "var(--maatlog-motion-fast" in rule


def test_default_post_card_lifts_on_hover_and_focus(make_project: ProjectFactory) -> None:
    # キーボード操作でも同じ状態が見えるよう hover と focus-within を揃える。
    # グループセレクタなので _css_rule では引けない。整形後の 1 行として突き合わせる。
    css = _normalise(_stylesheet(make_project, "maatlog-default"))

    assert ".maatlog-post-card:hover, .maatlog-post-card:focus-within {" in css
    start = css.index(".maatlog-post-card:hover, .maatlog-post-card:focus-within {")
    rule = css[start : css.index("}", start)]

    assert "transform: translateY(-3px)" in rule
    assert "box-shadow: var(--maatlog-shadow-md)" in rule
    assert "border-color: var(--maatlog-color-link)" in rule


def test_default_post_card_meta_sinks_to_the_bottom(make_project: ProjectFactory) -> None:
    # 本文の長さが違うカード同士でも meta 行が下端で揃うようにする。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-post-card-meta")

    assert "display: flex" in rule
    assert "flex-wrap: wrap" in rule
    assert "gap:" in rule
    assert "margin: auto 0 0" in rule


def test_default_post_card_image_has_a_fixed_aspect_ratio(make_project: ProjectFactory) -> None:
    # contain だとカードごとに画像の高さが変わり、グリッドの行が揃わない。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-post-card-image")

    assert "aspect-ratio: 16 / 9" in rule
    assert "object-fit: cover" in rule
    assert "object-fit: contain" not in rule


def test_default_lead_card_uses_magazine_type_and_image_ratio(
    make_project: ProjectFactory,
) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    title = _css_rule(css, ".maatlog-post-card-lead .maatlog-post-card-title")
    image = _css_rule(css, ".maatlog-post-card-lead .maatlog-post-card-image")
    lead = _css_rule(css, ".maatlog-post-card-lead")

    assert "font-size: 2rem" in title
    assert "aspect-ratio: 4 / 3" in image
    assert "object-fit: cover" in image
    assert "padding: var(--maatlog-space-lg" in lead
    assert "min-height: 16rem" in lead


def test_default_secondary_card_stays_compact(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    title = _css_rule(css, ".maatlog-post-card-secondary .maatlog-post-card-title")
    excerpt = _css_rule(css, ".maatlog-post-card-secondary .maatlog-post-card-excerpt")

    assert "font-size: 1.2rem" in title
    assert "-webkit-line-clamp: 2" in excerpt


def test_default_latest_excerpt_clamps_to_three_lines(
    make_project: ProjectFactory,
) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    excerpt = _css_rule(css, '[data-maatlog-card-variant="latest"] .maatlog-post-card-excerpt')
    lead_excerpt = _css_rule(css, ".maatlog-post-card-lead .maatlog-post-card-excerpt")

    assert "-webkit-line-clamp: 3" in excerpt
    assert "-webkit-line-clamp: 4" in lead_excerpt


def test_default_generic_card_image_stays_sixteen_by_nine(
    make_project: ProjectFactory,
) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-post-card-image")

    assert "aspect-ratio: 16 / 9" in rule


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_card_taxonomy_groups_use_flex_gap(make_project: ProjectFactory, theme: str) -> None:
    # 区切りが読み上げ専用になった分、視覚的な間隔は gap が担う。
    css = _stylesheet(make_project, theme)
    rules = _css_rules(css, ".maatlog-post-card-authors")

    assert rules
    assert any("inline-flex" in rule and "gap:" in rule for rule in rules)


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_post_card_is_the_positioning_context(make_project: ProjectFactory, theme: str) -> None:
    # overlay の inset: 0 はカードを基準に解決させる。
    css = _stylesheet(make_project, theme)
    rule = _css_rule(css, ".maatlog-post-card")

    assert "position: relative" in rule


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_post_card_title_link_stretches_across_the_card(make_project: ProjectFactory, theme: str) -> None:
    # 記事リンクを増やさずにクリック領域だけを広げる（stretched link）。
    css = _stylesheet(make_project, theme)
    rule = _css_rule(css, ".maatlog-post-card-title a::after")

    assert 'content: ""' in rule
    assert "position: absolute" in rule
    assert "inset: 0" in rule


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_post_card_meta_links_stay_above_the_stretched_link(make_project: ProjectFactory, theme: str) -> None:
    # taxonomy リンクが overlay に飲まれると記事ページへ吸い込まれる。
    css = _stylesheet(make_project, theme)
    rule = _css_rule(css, ".maatlog-post-card-meta a")

    assert "position: relative" in rule
    assert "z-index: 1" in rule


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_post_card_title_link_itself_stays_unpositioned(make_project: ProjectFactory, theme: str) -> None:
    # アンカー自身（:hover 等の pseudo-class を含む）を配置すると overlay の基準が
    # タイトル文字幅に縮む。overlay 本体の ::after は別契約なので対象外とする。
    # maatlog-base は現時点でこのセレクタ配下に pseudo-class ルールを持たないため、
    # 空リストも許容する。
    css = _stylesheet(make_project, theme)
    rules = _css_rules_by_selector_prefix(css, ".maatlog-post-card-title a")

    assert all("position:" not in rule for rule in rules)


def test_default_taxonomy_links_are_pills(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-taxonomy-link")

    assert "display: inline-flex" in rule
    assert "border-radius: var(--maatlog-radius-pill)" in rule
    assert "background: var(--maatlog-badge-background)" in rule
    assert "color: var(--maatlog-badge-text)" in rule
    assert "var(--maatlog-motion-fast" in rule


def test_default_category_badge_shares_the_pill_surface(make_project: ProjectFactory) -> None:
    # category と tag は同じ地を共有する。区別は tag の "#" 接頭辞が担う。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-category-badge")

    assert "border-radius: var(--maatlog-radius-pill)" in rule
    assert "background: var(--maatlog-badge-background)" in rule
    assert "border: 0" in rule


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_category_badge_drops_the_bracket_decoration(make_project: ProjectFactory, theme: str) -> None:
    # pill になった以上、生成内容の [ ] は二重の装飾になる。
    css = _stylesheet(make_project, theme)

    assert ".maatlog-category-badge::before" not in css
    assert ".maatlog-category-badge::after" not in css
    # セレクタ自体は POST_TAXONOMY_SELECTORS の契約なので残す。
    assert ".maatlog-category-badge {" in css


def test_default_author_links_are_not_badges(make_project: ProjectFactory) -> None:
    # 著者は人であって分類の入れ物ではない。category / tag と区別が付かなくなる。
    css = _stylesheet(make_project, "maatlog-default")

    post_rule = _css_rule(css, ".maatlog-post-info .maatlog-post-author-link")
    assert "background: none" in post_rule
    assert "padding: 0" in post_rule
    assert "text-decoration: underline" in post_rule

    card_rule = _css_rule(css, ".maatlog-post-card-authors .maatlog-taxonomy-link")
    assert "background: none" in card_rule
    assert "padding: 0" in card_rule
    assert "text-decoration: underline" in card_rule


def test_home_card_tags_are_quieter_than_categories(
    make_project: ProjectFactory,
) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    tag = _css_rule(
        css,
        ".maatlog-post-featured .maatlog-post-card-tags .maatlog-taxonomy-link",
    )
    author = _css_rule(css, ".maatlog-post-featured .maatlog-post-card-authors")

    assert "background: transparent" in tag
    assert "color: var(--maatlog-color-muted" in tag
    assert "border: 1px solid var(--maatlog-color-border" in tag
    assert "color: var(--maatlog-color-muted" in author


def test_medium_breakpoint_collapses_featured_data_component(
    make_project: ProjectFactory,
) -> None:
    block = _media_block_containing(
        _stylesheet(make_project, "maatlog-default"),
        "width <= 64rem",
        '[data-maatlog-component="featured"]',
    )
    rule = _css_rule(block, '[data-maatlog-component="featured"]')
    assert "grid-template-columns: minmax(0, 1fr);" in _normalise(rule)


def test_narrow_breakpoint_collapses_featured_data_component(
    make_project: ProjectFactory,
) -> None:
    block = _media_block_containing(
        _stylesheet(make_project, "maatlog-default"),
        "width <= 48rem",
        '[data-maatlog-component="featured"]',
    )
    rule = _css_rule(block, '[data-maatlog-component="featured"]')
    assert "grid-template-columns: minmax(0, 1fr);" in _normalise(rule)


def test_home_card_eyebrow_is_a_quiet_kicker(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-post-card-eyebrow")
    assert "text-transform: uppercase" in rule
    assert "font-size: 0.78rem" in rule
    assert "color: var(--maatlog-color-muted" in rule


def test_home_card_author_links_are_muted(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(
        css,
        ".maatlog-post-featured .maatlog-post-card-authors .maatlog-taxonomy-link",
    )
    assert "color: var(--maatlog-color-muted" in rule


def test_archive_taxonomy_pills_keep_badge_fill(
    make_project: ProjectFactory,
) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-taxonomy-link")

    assert "background: var(--maatlog-badge-background)" in rule
    assert "color: var(--maatlog-badge-text)" in rule


def test_default_focus_outline_reaches_pill_badges(make_project: ProjectFactory) -> None:
    # pill は角丸なので、outline も同じ半径で回らないと角が欠けて見える。
    css = _stylesheet(make_project, "maatlog-default")
    rules = _css_rules(css, ".maatlog-taxonomy-link:focus-visible")

    assert len(rules) == 1
    assert any("border-radius: var(--maatlog-radius-pill)" in rule for rule in rules)

    normalised = _normalise(css)
    assert ".maatlog-taxonomy-link:focus-visible," in normalised
    assert "outline: 2px solid var(--maatlog-color-link" in normalised
    assert "outline-offset: 2px" in normalised


def test_default_featured_block_is_a_bento(make_project: ProjectFactory) -> None:
    # 大 1 + 小 2 の非対称レイアウト。3 枚ちょうどのときだけ大カードを 2 行ぶちぬく。
    css = _stylesheet(make_project, "maatlog-default")
    container = _css_rule(css, ".maatlog-post-featured")
    lead = _css_rule(css, ".maatlog-post-featured .maatlog-post-card:first-child:nth-last-child(3)")
    solo = _css_rule(css, ".maatlog-post-featured .maatlog-post-card:only-child")

    assert "display: grid" in container
    assert "grid-template-columns:minmax(0,1.6fr)minmax(0,1fr);" in _compact(container)
    assert "grid-row: span 2" in lead
    assert "grid-column: 1 / -1" in solo


def test_default_featured_accepts_theme_api_lead_selectors(
    make_project: ProjectFactory,
) -> None:
    css = _stylesheet(make_project, "maatlog-default")

    assert '[data-maatlog-component="featured"]' in css
    assert ".maatlog-post-card-lead:only-child" in css
    assert ".maatlog-post-card-lead:nth-last-child(3)" in css
    lead_span = _css_rule(css, ".maatlog-post-featured .maatlog-post-card-lead:nth-last-child(3)")
    assert "grid-row: span 2" in lead_span
    solo = _css_rule(css, ".maatlog-post-featured .maatlog-post-card-lead:only-child")
    assert "grid-column: 1 / -1" in solo
    # Task 2 adds a bare-lead box rule (padding/min-height only). It must
    # never carry grid placement, or 2-item featured rows would break.
    try:
        bare_lead = _css_rule(css, ".maatlog-post-card-lead")
    except ValueError:
        bare_lead = ""
    assert "grid-row" not in bare_lead
    assert "grid-column" not in bare_lead


def test_default_latest_cards_use_an_auto_fill_grid(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-post-grid")

    assert "display: grid" in rule
    assert "repeat(auto-fill,minmax(17rem,1fr))" in _compact(rule)


def test_home_latest_grid_uses_wider_tracks_than_archive(
    make_project: ProjectFactory,
) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    home = _css_rule(css, '[data-maatlog-component="latest"]')

    assert "repeat(auto-fill,minmax(max(20rem,calc((100%-2*var(--maatlog-space-md,1rem))/3)),1fr))" in _compact(home)
    archive = _css_rule(css, ".maatlog-post-grid")
    assert "repeat(auto-fill,minmax(17rem,1fr))" in _compact(archive)


def test_default_grid_cards_drop_their_stacking_margin(make_project: ProjectFactory) -> None:
    # グリッドの gap とカードの margin-bottom が二重にかかると行間が広がる。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-post-grid .maatlog-post-card")

    assert ".maatlog-post-featured .maatlog-post-card," in _normalise(css)
    assert "margin-bottom: 0;" in rule


def test_default_post_list_heading_is_a_quiet_label(make_project: ProjectFactory) -> None:
    # featured と Latest の境目。本文の h2 と同じ強さで出すとカードより目立つ。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-post-list-heading")

    assert "text-transform: uppercase" in rule
    assert "letter-spacing:" in rule
    assert "color: var(--maatlog-color-muted" in rule
    assert "grid-area: auto" not in rule


def test_medium_breakpoint_collapses_the_bento(make_project: ProjectFactory) -> None:
    block = _media_block_containing(
        _stylesheet(make_project, "maatlog-default"),
        "width <= 64rem",
        ".maatlog-post-featured",
    )

    assert "grid-template-columns: minmax(0, 1fr);" in _normalise(_css_rule(block, ".maatlog-post-featured"))
    assert "grid-row: auto" in _css_rule(
        block, ".maatlog-post-featured .maatlog-post-card:first-child:nth-last-child(3)"
    )
    assert "repeat(auto-fill,minmax(15rem,1fr))" in _compact(_css_rule(block, ".maatlog-post-grid"))


def test_medium_breakpoint_puts_home_latest_on_two_columns(
    make_project: ProjectFactory,
) -> None:
    block = _media_block_containing(
        _stylesheet(make_project, "maatlog-default"),
        "width <= 64rem",
        '[data-maatlog-component="latest"]',
    )
    home = _css_rule(block, '[data-maatlog-component="latest"]')
    archive = _css_rule(block, ".maatlog-post-grid")

    assert "repeat(2,minmax(0,1fr))" in _compact(home)
    assert "repeat(auto-fill,minmax(15rem,1fr))" in _compact(archive)


def test_narrow_breakpoint_collapses_home_latest_to_one_column(
    make_project: ProjectFactory,
) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    block = _media_block_containing(
        css,
        "width <= 48rem",
        '[data-maatlog-component="latest"]',
    )
    rule = _css_rule(block, '[data-maatlog-component="latest"]')
    assert "grid-template-columns: minmax(0, 1fr);" in _normalise(rule)
    # 64rem の Home 2 列より後ろに narrow 1 列が来ること。
    # 同 specificity では後の宣言が勝つため、順序が逆だと 48rem 幅で 2 列になる。
    home_rules = _css_rules(css, '[data-maatlog-component="latest"]')
    assert "minmax(0,1fr)" in _compact(home_rules[-1])
    assert "repeat(2,minmax(0,1fr))" in _compact(home_rules[-2])


def test_narrow_breakpoint_collapses_featured_and_grid(make_project: ProjectFactory) -> None:
    block = _media_block_containing(
        _stylesheet(make_project, "maatlog-default"),
        "width <= 48rem",
        ".maatlog-post-grid",
    )
    # グループの末尾セレクタで引く（_css_rule は "<selector> {" の完全一致）。
    rule = _normalise(_css_rule(block, ".maatlog-post-grid"))

    assert ".maatlog-post-featured," in _normalise(block)
    assert "grid-template-columns: minmax(0, 1fr);" in rule


def test_default_post_header_is_a_stacked_editorial_block(make_project: ProjectFactory) -> None:
    # meta が header の中に入ったので、header 自身が縦フローの組版単位になる。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-post-header")

    assert "display: flex" in rule
    assert "flex-direction: column" in rule
    assert "gap:" in rule


def test_default_drops_the_meta_grid_area(make_project: ProjectFactory) -> None:
    # meta は header の子になった。named area が残ると誰も使わない行が空く。
    css = _stylesheet(make_project, "maatlog-default")

    assert '"meta"' not in css
    assert "grid-area: meta" not in css


def test_default_post_meta_is_a_single_wrapping_row(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-post-meta")

    assert "flex-wrap: wrap" in rule
    assert "flex-direction: column" not in rule


def test_default_post_title_dominates_the_body(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _normalise(_css_rule(css, ".maatlog-post-header h1"))

    assert "clamp(2.2rem, 5vw, 4rem)" in rule
    assert "line-height: 1.08" in rule
    assert "letter-spacing: -0.035em" in rule


def test_default_styles_the_editorial_header_parts(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")

    assert "text-transform: uppercase" in _css_rule(css, ".maatlog-post-eyebrow")
    assert "color: var(--maatlog-color-muted" in _css_rule(css, ".maatlog-post-tagline")

    hero = _css_rule(css, ".maatlog-post-hero-image")
    assert "aspect-ratio: 21 / 9" in hero
    assert "object-fit: cover" in hero
    assert "border-radius: var(--maatlog-radius-lg" in hero


def test_default_declares_an_explicit_heading_scale(make_project: ProjectFactory) -> None:
    # basic.css 由来の見出しサイズだと h2 と h3 の差がほとんど無い。
    css = _stylesheet(make_project, "maatlog-default")

    for selector, size in (
        (".maatlog-post-body h2", "1.75rem"),
        (".maatlog-post-body h3", "1.35rem"),
        (".maatlog-post-body h4", "1.1rem"),
    ):
        rule = _normalise(_css_rule(css, selector))
        assert f"font-size: {size}" in rule, selector
        assert "margin:" in rule, selector
        assert "letter-spacing:" in rule, selector


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_editorial_header_classes_exist_in_both_themes(make_project: ProjectFactory, theme: str) -> None:
    # base は見た目を作らないが、新しいセマンティッククラスの最小スタイルは持つ。
    css = _stylesheet(make_project, theme)

    for selector in (".maatlog-post-eyebrow", ".maatlog-post-tagline", ".maatlog-post-hero-image"):
        assert f"{selector} {{" in css, selector


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_article_container_rules_are_scoped_by_element(make_project: ProjectFactory, theme: str) -> None:
    # ``{maatlog:post}`` ロールは <code class="xref maatlog maatlog-post"> を出す。
    # 記事コンテナのルールを裸のクラスで書くと、インライン参照が grid の箱になる。
    css = _stylesheet(make_project, theme)

    assert "article.maatlog-post,\nsection.maatlog-archive {" in css
    assert "\n.maatlog-post,\n.maatlog-archive {" not in css


def test_default_tables_scroll_inside_themselves(make_project: ProjectFactory) -> None:
    # Sphinx は table にラッパを出さない。table 自身をスクロールコンテナにする。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-layout-main table.docutils")

    assert "display: block" in rule
    assert "overflow-x: auto" in rule
    assert "max-width: 100%" in rule


def test_default_table_header_sits_on_a_quiet_surface(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-layout-main table.docutils th")

    assert "background: var(--maatlog-color-surface-hover" in rule
    assert "text-align: left" in rule


def test_default_blockquote_uses_an_accent_rule(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-layout-main blockquote")

    assert "border-left: 3px solid var(--maatlog-color-accent" in rule
    assert "background: var(--maatlog-color-surface" in rule


def test_default_blockquote_reaches_through_the_docutils_div(make_project: ProjectFactory) -> None:
    # docutils は blockquote の中に <div> を挟む。最終要素は 2 段下にいる。
    css = _stylesheet(make_project, "maatlog-default")

    assert ".maatlog-layout-main blockquote > div > :last-child" in css


def test_default_admonitions_use_two_accents_only(make_project: ProjectFactory) -> None:
    # 種別ごとに色を増やすと、技術記事の中で admonition だけが騒がしくなる。
    css = _stylesheet(make_project, "maatlog-default")
    base = _css_rule(css, ".maatlog-layout-main .admonition")
    caution = _css_rule(css, ".maatlog-layout-main .admonition.attention")

    assert "border-left: 3px solid var(--maatlog-color-link" in base
    assert "border-radius: var(--maatlog-radius-md" in base
    assert "border-left-color: var(--maatlog-color-accent" in caution


def test_default_admonition_title_reads_as_a_label(make_project: ProjectFactory) -> None:
    # Sphinx の admonition-title は <p> なので、見出しに見える指定を自前で当てる。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-layout-main .admonition > .admonition-title")

    assert "text-transform: uppercase" in rule
    assert "font-weight: 700" in rule


def test_default_headerlink_is_hidden_until_wanted(make_project: ProjectFactory) -> None:
    # ¶ を常時出すとドキュメントテーマの顔になる。display: none にはしない
    # ——キーボードから到達できなくなるため、opacity で退かせる。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-layout-main a.headerlink")

    assert "opacity: 0" in rule
    assert "display: none" not in rule


def test_default_headerlink_returns_on_hover_and_focus(make_project: ProjectFactory) -> None:
    # hover だけにするとキーボード利用者に見えない。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-layout-main a.headerlink:focus-visible")

    assert "opacity: 1" in rule
    assert ":hover > a.headerlink" in css
    assert ":is(h1, h2, h3, h4, h5, h6, dt, caption, figcaption):hover > a.headerlink" in css


def test_default_nav_links_are_as_quiet_as_the_toc(make_project: ProjectFactory) -> None:
    # 左 nav だけ本文と同色だと、両サイドバーの強さが揃わない。
    css = _stylesheet(make_project, "maatlog-default")
    toctree = _css_rule(css, ".maatlog-nav-toctree a")
    taxonomy = _css_rule(css, ".maatlog-taxonomy-item")

    assert "color: var(--maatlog-color-muted)" in toctree
    assert "color: var(--maatlog-color-muted)" in taxonomy


def test_default_nav_links_recover_on_hover(make_project: ProjectFactory) -> None:
    # 平常時を muted に落としたぶん、hover / focus では本文色まで戻す。
    css = _stylesheet(make_project, "maatlog-default")
    toctree = _css_rule(css, ".maatlog-nav-toctree a:focus-visible")
    taxonomy = _css_rule(css, ".maatlog-taxonomy-item:focus-visible")

    assert "color: var(--maatlog-color-text)" in toctree
    assert "color: var(--maatlog-color-text)" in taxonomy


def test_default_sidebars_use_a_thin_scrollbar(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")

    assert "scrollbar-width: thin" in _css_rule(css, ".maatlog-nav")
    assert "scrollbar-width: thin" in _css_rule(css, ".maatlog-toc")


def test_default_sidebar_feed_links_have_no_bullets(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-default")

    assert "list-style: none" in _css_rule(css, ".maatlog-sidebar .maatlog-feed-links")


def test_default_normal_page_prose_is_capped(make_project: ProjectFactory) -> None:
    # コンテナは main いっぱい（既存契約）。行長はテキスト要素側で抑える。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-layout-page-normal .body :is(p, ul, ol, dl, blockquote)")

    assert "max-width: var(--maatlog-content-width" in rule


def test_default_normal_page_headings_stay_full_width(make_project: ProjectFactory) -> None:
    # 通常ページの見出しは目次的な役割が強い。幅を切ると表や図とくい違う。
    # test_wide_content_fills_the_main_column が h1 の全幅を実ブラウザで固定している。
    css = _stylesheet(make_project, "maatlog-default")
    rule = _css_rule(css, ".maatlog-layout-page-normal .body :is(p, ul, ol, dl, blockquote)")

    assert "h1" not in rule
    assert "h2" not in rule


def _top_level_css_before_reduced_motion(css: str) -> str:
    """Return stylesheet text before the reduced-motion media query."""
    marker = "@media (prefers-reduced-motion: reduce)"
    assert marker in css, "maatlog-default must keep a single reduced-motion block"
    return css.split(marker, 1)[0]


def test_default_enables_cross_document_view_transition(
    make_project: ProjectFactory,
) -> None:
    # Issue #67: same-origin MPA navigations get a short root transition.
    css = _stylesheet(make_project, "maatlog-default")
    head = _top_level_css_before_reduced_motion(css)

    assert "@view-transition" in head
    assert "navigation: auto" in head
    assert "::view-transition-old(root)" in head
    assert "::view-transition-new(root)" in head
    assert "animation-duration: var(--maatlog-motion-fast)" in head
    assert "animation-timing-function: ease-out" in head


def test_default_disables_view_transition_under_reduced_motion(
    make_project: ProjectFactory,
) -> None:
    # Prefer turning navigation off over relying only on animation: none.
    css = _stylesheet(make_project, "maatlog-default")
    block = _media_block_containing(
        css,
        "prefers-reduced-motion: reduce",
        "animation: none",
    )

    assert "@view-transition" in block
    assert "navigation: none" in block
    # Keep the existing hover-motion kill switch.
    assert "transition: none" in block
    assert "transform: none" in block


def test_base_does_not_declare_view_transition(
    make_project: ProjectFactory,
) -> None:
    # Page transition is visual chrome, not Theme API contract CSS.
    css = _stylesheet(make_project, "maatlog-base")

    assert "@view-transition" not in css
    assert "::view-transition-old" not in css
    assert "::view-transition-new" not in css


def test_default_view_transition_does_not_require_extra_scripts(
    make_project: ProjectFactory,
) -> None:
    # Spec: CSS only — keep the single theme runtime; add no VT/SPA script.
    result = make_project(files=LAYOUT_PROJECT, theme="maatlog-default").build()
    html = result.html("about.html").text
    maatlog_scripts = re.findall(
        r"<script\b[^>]*maatlog[^>]*>",
        html,
        flags=re.IGNORECASE,
    )

    assert len(maatlog_scripts) == 1
    assert "maatlog.js" in maatlog_scripts[0]
    assert "startViewTransition" not in html
    assert "maatlog-view" not in html.lower()


def test_base_gives_the_infinite_scroll_sentinel_a_measurable_box(make_project: ProjectFactory) -> None:
    # 高さ 0 の要素は IntersectionObserver から見えないことがある。
    css = _stylesheet(make_project, "maatlog-base")
    rule = _css_rule(css, ".maatlog-infinite-sentinel")

    assert "block-size: 1px" in rule


# ``maatlog-default`` ships its own ``static/maatlog.css`` under the same name as
# ``maatlog-base``, so Sphinx's theme static copy makes the child file replace the
# parent's entirely. Every visual class base defines must therefore be mirrored.
BASE_ONLY_CLASSES = frozenset(
    {
        # A 1px IntersectionObserver sentinel with no visual presentation; the
        # default theme needs no rule of its own for it.
        "maatlog-infinite-sentinel",
    }
)

HERO_CLASSES = (
    "maatlog-post-top-image",
    "maatlog-post-top-image-img",
    "maatlog-post-top-image-overlay",
    "maatlog-post-top-image-title",
)


def _class_selectors(css: str) -> set[str]:
    without_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return set(re.findall(r"\.(maatlog[A-Za-z0-9_-]*)", without_comments))


def test_default_stylesheet_mirrors_every_base_class(make_project: ProjectFactory) -> None:
    """The default theme replaces base's stylesheet, so it must cover its classes."""
    base = _class_selectors(_stylesheet(make_project, "maatlog-base"))
    default = _class_selectors(_stylesheet(make_project, "maatlog-default"))

    assert sorted(base - BASE_ONLY_CLASSES - default) == []


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
@pytest.mark.parametrize("selector", HERO_CLASSES)
def test_hero_styles_are_declared(make_project: ProjectFactory, theme: str, selector: str) -> None:
    assert f".{selector} {{" in _stylesheet(make_project, theme)


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_hero_title_overlaps_the_image(make_project: ProjectFactory, theme: str) -> None:
    """The acceptance criterion is an overlay, which needs a positioned ancestor."""
    css = _stylesheet(make_project, theme)

    container = _css_rule(css, ".maatlog-post-top-image")
    assert "position: relative" in container
    title = _css_rule(css, ".maatlog-post-top-image-title")
    assert "position: absolute" in title
    assert "--maatlog-top-image-title-color" in css


def test_base_theme_defines_profile_width_tokens(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-base")

    assert "--maatlog-profile-main-width:" in css
    assert "--maatlog-profile-content-width:" in css


def test_base_theme_lets_profile_main_use_the_full_grid_track(make_project: ProjectFactory) -> None:
    """Profile pages skip the page TOC column, so main should not be capped below the grid track."""
    css = _stylesheet(make_project, "maatlog-base")

    assert "--maatlog-profile-main-width:" in css
    assert ".maatlog-layout-page-profile .maatlog-layout-main" not in css


def test_base_theme_does_not_touch_the_shared_content_width(make_project: ProjectFactory) -> None:
    """通常ページの行長ポリシー（Issue #71 / #110）を退行させない。"""
    css = _stylesheet(make_project, "maatlog-base")

    assert "--maatlog-content-width: clamp(42rem, 24rem + 16vw, 60rem);" in css


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_author_summary_card_is_styled(make_project: ProjectFactory, theme: str) -> None:
    css = _stylesheet(make_project, theme)

    assert ".maatlog-author-summary-card {" in css


def test_base_sizes_the_author_avatar(make_project: ProjectFactory) -> None:
    css = _stylesheet(make_project, "maatlog-base")
    avatar = _css_rule(css, ".maatlog-author-summary-avatar")

    assert "width: var(--maatlog-author-avatar-size, 3.5rem);" in avatar
    assert "height: var(--maatlog-author-avatar-size, 3.5rem);" in avatar


CONFIG_STYLE_PROJECT = {
    "about.rst": "About\n=====\n\nA plain page paragraph.\n",
    "post.rst": """:maatlog-post: true
:maatlog-slug: width-post
:maatlog-published-at: 2026-07-31T09:00:00Z

Width Post
==========

Paragraph one.
""",
}


def test_no_config_style_is_emitted_when_nothing_is_configured(
    make_project: ProjectFactory,
) -> None:
    """未設定時の <head> は現状のまま。<style> を増やさない。"""
    result = make_project(files=CONFIG_STYLE_PROJECT).build()

    for page in ("index.html", "about.html", "post.html", "blog.html"):
        html = result.path(page).read_text(encoding="utf-8")
        assert "--maatlog-content-width:" not in html
        assert "--maatlog-top-image-title-font:" not in html


@pytest.mark.parametrize("page", ["index.html", "about.html", "post.html", "blog.html"])
def test_content_width_reaches_every_page_kind(make_project: ProjectFactory, page: str) -> None:
    """normal（index / about）・post・archive のいずれにも :root トークンが出る。"""
    result = make_project(
        files=CONFIG_STYLE_PROJECT,
        config={"maatlog_content_width": "100%"},
    ).build()

    html = result.path(page).read_text(encoding="utf-8")
    assert "<style>:root { --maatlog-content-width: 100%; }</style>" in html


def test_content_width_reaches_the_blog_home(make_project: ProjectFactory) -> None:
    """page_kind == "home" も layout.html を通る。"""
    result = make_project(
        files=CONFIG_STYLE_PROJECT,
        config={"maatlog_content_width": "100%", "maatlog_home_docname": "index"},
    ).build()

    html = result.path("index.html").read_text(encoding="utf-8")
    assert "<style>:root { --maatlog-content-width: 100%; }</style>" in html


def test_content_width_style_wins_over_the_theme_stylesheet(
    make_project: ProjectFactory,
) -> None:
    """同一詳細度の :root はソース順で後勝ち。<style> は <link> より後に出す。"""
    result = make_project(
        files=CONFIG_STYLE_PROJECT,
        config={"maatlog_content_width": "100%"},
    ).build()

    html = result.path("post.html").read_text(encoding="utf-8")
    link_at = html.index("_static/maatlog.css")
    style_at = html.index("--maatlog-content-width: 100%")
    assert link_at < style_at


def test_content_width_keeps_css_functions_unescaped(make_project: ProjectFactory) -> None:
    """<style> は raw text。エスケープすると clamp() の引数が壊れる。"""
    result = make_project(
        files=CONFIG_STYLE_PROJECT,
        config={"maatlog_content_width": "clamp(42rem, 70vw, 90rem)"},
    ).build()

    html = result.path("post.html").read_text(encoding="utf-8")
    assert "--maatlog-content-width: clamp(42rem, 70vw, 90rem);" in html


def test_config_style_emits_both_tokens_in_one_rule(make_project: ProjectFactory) -> None:
    result = make_project(
        files=CONFIG_STYLE_PROJECT,
        config={
            "maatlog_content_width": "100%",
            "maatlog_top_image_title_font": "Georgia, serif",
        },
    ).build()

    html = result.path("post.html").read_text(encoding="utf-8")
    assert (
        "<style>:root { --maatlog-content-width: 100%; --maatlog-top-image-title-font: Georgia, serif; }</style>"
    ) in html
