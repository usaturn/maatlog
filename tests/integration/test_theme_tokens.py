"""ライト／ダークの配色トークン契約。"""

from __future__ import annotations

import re

import pytest
from conftest import ProjectFactory

TOKEN_PROJECT = {
    "about.rst": "About\n=====\n\n.. code-block:: python\n\n   def f():\n       return 1\n",
}

COLOR_TOKENS = (
    "--maatlog-color-background",
    "--maatlog-color-surface",
    "--maatlog-color-surface-hover",
    "--maatlog-color-text",
    "--maatlog-color-muted",
    "--maatlog-color-link",
    "--maatlog-color-accent",
    "--maatlog-color-border",
    "--maatlog-color-control-border",
    "--maatlog-code-background",
    "--maatlog-code-text",
    "--maatlog-code-border",
    "--maatlog-inline-code-background",
    "--maatlog-inline-code-text",
    "--maatlog-badge-background",
    "--maatlog-badge-text",
    "--maatlog-shadow-color",
)

DARK_MEDIA_SELECTOR = ':root:not([data-theme="light"])'
DARK_ATTRIBUTE_SELECTOR = ':root[data-theme="dark"]'


def _stylesheet(make_project: ProjectFactory, theme: str) -> str:
    result = make_project(files=TOKEN_PROJECT, theme=theme).build()
    return result.asset("_static/maatlog.css").read_text(encoding="utf-8")


def block_tokens(css: str, selector: str) -> dict[str, str]:
    """``selector`` のブロックが宣言するカスタムプロパティを返す。"""
    start = css.index(f"{selector} {{")
    body = css[css.index("{", start) + 1 : css.index("}", start)]
    tokens: dict[str, str] = {}
    for declaration in body.split(";"):
        name, separator, value = declaration.partition(":")
        if separator and name.strip().startswith("--"):
            tokens[name.strip()] = value.strip()
    return tokens


def block_declaration(css: str, selector: str, prop: str) -> str | None:
    """``selector`` のブロックが宣言する通常プロパティの値を返す。"""
    start = css.index(f"{selector} {{")
    body = css[css.index("{", start) + 1 : css.index("}", start)]
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    for declaration in body.split(";"):
        name, separator, value = declaration.partition(":")
        if separator and name.strip() == prop:
            return value.strip()
    return None


def _css_rule_body(css: str, selector: str) -> str:
    """``selector`` の宣言ブロック本体を返す。"""
    start = css.index(f"{selector} {{")
    return css[css.index("{", start) + 1 : css.index("}", start)]


def _balanced_block(css: str, start: int) -> str:
    """``start`` から始まる、波括弧の対応が取れたブロック全体を返す。"""
    depth = 0
    for index in range(css.index("{", start), len(css)):
        if css[index] == "{":
            depth += 1
        elif css[index] == "}":
            depth -= 1
            if depth == 0:
                return css[start : index + 1]
    msg = "unbalanced block"
    raise AssertionError(msg)


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
@pytest.mark.parametrize("token", COLOR_TOKENS)
def test_light_palette_declares_every_color_token(make_project: ProjectFactory, theme: str, token: str) -> None:
    assert token in block_tokens(_stylesheet(make_project, theme), ":root")


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_both_dark_blocks_declare_the_same_values(make_project: ProjectFactory, theme: str) -> None:
    # ダークの値は media クエリ側と data-theme 側の 2 箇所に書く必要がある。
    # 片方だけ更新する事故をここで止める。
    css = _stylesheet(make_project, theme)

    assert block_tokens(css, DARK_MEDIA_SELECTOR) == block_tokens(css, DARK_ATTRIBUTE_SELECTOR)


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_dark_palette_overrides_every_color_token(make_project: ProjectFactory, theme: str) -> None:
    dark = block_tokens(_stylesheet(make_project, theme), DARK_ATTRIBUTE_SELECTOR)

    assert set(COLOR_TOKENS) <= set(dark)


def test_base_and_default_agree_on_every_color_token(make_project: ProjectFactory) -> None:
    # Issue #58 の指摘: base と default でリンク色・カード背景がずれていた。
    base = _stylesheet(make_project, "maatlog-base")
    default = _stylesheet(make_project, "maatlog-default")

    for selector in (":root", DARK_MEDIA_SELECTOR, DARK_ATTRIBUTE_SELECTOR):
        base_colors = {k: v for k, v in block_tokens(base, selector).items() if k in COLOR_TOKENS}
        default_colors = {k: v for k, v in block_tokens(default, selector).items() if k in COLOR_TOKENS}
        assert base_colors == default_colors, selector


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_every_palette_block_declares_a_color_scheme(make_project: ProjectFactory, theme: str) -> None:
    # color-scheme を書かないと検索フォームやスクロールバーが常にライトで描かれる。
    css = _stylesheet(make_project, theme)

    assert block_declaration(css, ":root", "color-scheme") == "light"
    assert block_declaration(css, DARK_MEDIA_SELECTOR, "color-scheme") == "dark"
    assert block_declaration(css, DARK_ATTRIBUTE_SELECTOR, "color-scheme") == "dark"


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_page_and_code_surfaces_use_tokens(make_project: ProjectFactory, theme: str) -> None:
    css = _stylesheet(make_project, theme)

    assert "background: var(--maatlog-color-background" in css
    assert "background: var(--maatlog-code-background" in css
    assert "color: var(--maatlog-code-text" in css


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_inline_code_does_not_reuse_the_block_surface(make_project: ProjectFactory, theme: str) -> None:
    # コードブロックはライトでもダーク地にする。同じトークンを inline code に
    # 使うと本文の途中が黒く抜ける。
    css = _stylesheet(make_project, theme)
    rule = _css_rule_body(css, ".maatlog-layout-main code")

    assert "var(--maatlog-inline-code-background" in rule
    assert "var(--maatlog-inline-code-text" in rule
    assert "var(--maatlog-code-background" not in rule


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_pygments_ships_a_light_and_a_dark_stylesheet(make_project: ProjectFactory, theme: str) -> None:
    result = make_project(files=TOKEN_PROJECT, theme=theme).build()

    assert result.asset("_static/pygments.css").exists()
    assert result.asset("_static/pygments_dark.css").exists()
    # JS が media を書き換えるための掴みどころ。Sphinx が付ける id に依存している。
    link = result.html("about.html").select_one('link[id="pygments_dark_css"]')
    assert link is not None
    assert link["media"] == "(prefers-color-scheme: dark)"


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_pygments_actually_colours_tokens(make_project: ProjectFactory, theme: str) -> None:
    # basic テーマ由来の pygments_style = none を上書きできているか。
    result = make_project(files=TOKEN_PROJECT, theme=theme).build()
    pygments = result.asset("_static/pygments.css").read_text(encoding="utf-8")

    assert ".highlight .k" in pygments


def _colour_literals_outside_tokens(css: str) -> list[str]:
    """トークン宣言と ``var()`` のフォールバック以外に残る色リテラル。"""
    without_fallbacks = re.sub(r"var\(\s*--[\w-]+\s*,[^)]*\)", "var()", css)
    without_tokens = re.sub(r"--[\w-]+\s*:[^;]*;", "", without_fallbacks)
    return re.findall(r"#[0-9a-fA-F]{3,8}\b", without_tokens)


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_components_never_hard_code_a_colour(make_project: ProjectFactory, theme: str) -> None:
    # Issue #58 の実装方針: 各コンポーネントに直接色を書かず、必ずトークンを参照する。
    assert _colour_literals_outside_tokens(_stylesheet(make_project, theme)) == []


PALETTE_SELECTORS = (":root", DARK_MEDIA_SELECTOR, DARK_ATTRIBUTE_SELECTOR)


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_palette_blocks_declare_no_motion(make_project: ProjectFactory, theme: str) -> None:
    # 配色の切替は一瞬で終わらせる。パレットブロックにトランジションを足すと
    # ライト／ダークの切替がにじみ、モーション設定への分岐も必要になる。
    css = _stylesheet(make_project, theme)

    for selector in PALETTE_SELECTORS:
        start = css.index(f"{selector} {{")
        body = css[css.index("{", start) + 1 : css.index("}", start)]
        assert "transition" not in body, selector
        assert "animation" not in body, selector

    body_rule = _css_rule_body(css, "body")
    assert "transition" not in body_rule
    assert "animation" not in body_rule


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_motion_is_cancelled_for_reduced_motion(make_project: ProjectFactory, theme: str) -> None:
    # モーションを 1 つでも宣言するなら、必ず打ち消しを併せて出荷する。
    css = _stylesheet(make_project, theme)
    if "transition" not in css:
        pytest.skip("this theme declares no motion")

    marker = "@media (prefers-reduced-motion: reduce) {"
    assert marker in css
    block = _balanced_block(css, css.index(marker))
    assert "transition: none" in block
    assert "transform: none" in block


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_motion_uses_only_the_duration_token(make_project: ProjectFactory, theme: str) -> None:
    # 継続時間を各所に直書きすると、あとから一括で調整できなくなる。
    css = re.sub(r"/\*.*?\*/", "", _stylesheet(make_project, theme), flags=re.DOTALL)

    for declaration in re.findall(r"transition:[^;}]*", css):
        if "none" in declaration:
            continue
        assert "var(--maatlog-motion-fast)" in declaration, declaration
        assert not re.search(r"\d+m?s\b", declaration), declaration


STRUCTURE_TOKENS = (
    "--maatlog-radius-sm",
    "--maatlog-radius-md",
    "--maatlog-radius-lg",
    "--maatlog-radius-pill",
    "--maatlog-shadow-sm",
    "--maatlog-shadow-md",
    "--maatlog-space-xl",
    "--maatlog-font-sans",
    "--maatlog-font-mono",
    "--maatlog-motion-fast",
    "--maatlog-color-primary",
)


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
@pytest.mark.parametrize("token", STRUCTURE_TOKENS)
def test_light_palette_declares_every_structure_token(make_project: ProjectFactory, theme: str, token: str) -> None:
    # 半径・影・タイポグラフィはライトの :root で一度だけ定義する。
    # ダーク側で変わるのは影の色（--maatlog-shadow-color）だけ。
    assert token in block_tokens(_stylesheet(make_project, theme), ":root")


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_primary_is_an_alias_of_the_link_token(make_project: ProjectFactory, theme: str) -> None:
    # link がリテラルの持ち主。逆向きにすると輝度計算がトークン値を読めなくなる。
    tokens = block_tokens(_stylesheet(make_project, theme), ":root")

    assert tokens["--maatlog-color-primary"] == "var(--maatlog-color-link)"
    assert tokens["--maatlog-color-link"].startswith("#")


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_banner_height_is_a_concrete_length(make_project: ProjectFactory, theme: str) -> None:
    # banner の支柱の最小高さを固定する（sticky offset は --maatlog-space-md を使用）。
    tokens = block_tokens(_stylesheet(make_project, theme), ":root")

    assert tokens["--maatlog-banner-height"] == "4rem"


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_shadows_are_built_from_the_shadow_colour_token(make_project: ProjectFactory, theme: str) -> None:
    # ダークでは影を濃くする。色は 1 トークンに集約しておく。
    tokens = block_tokens(_stylesheet(make_project, theme), ":root")

    assert "var(--maatlog-shadow-color)" in tokens["--maatlog-shadow-sm"]
    assert "var(--maatlog-shadow-color)" in tokens["--maatlog-shadow-md"]
