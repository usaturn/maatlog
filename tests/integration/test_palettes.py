"""パレットプリセットの契約（Theme API 1.5）。

Issue #92 の各フェーズが tests/integration/test_layout_css.py を触るため、
パレットの検証はこのファイルに閉じる。

コントラストの計算は tests/unit/test_theme_contrast.py と同じ式を持つ。
テスト間で実装を import し合うと片方の移動でもう片方が壊れるため、
このリポジトリの既存テストと同じく小さな重複を許している。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import BuildResult, ProjectFactory

from maatlog.errors import MaatlogBuildError

THEMES_ROOT = Path(__file__).resolve().parents[2] / "src" / "maatlog" / "themes"
BASE_STATIC = THEMES_ROOT / "maatlog-base" / "static"
PALETTES_DIR = BASE_STATIC / "palettes"

DEFAULT_PALETTE = "indigo"
PALETTES = ("indigo", "github", "solarized", "nord", "neon")
ADDITIONAL_PALETTES = tuple(name for name in PALETTES if name != DEFAULT_PALETTE)

LIGHT_SELECTOR = ":root"
DARK_MEDIA_SELECTOR = ':root:not([data-theme="light"])'
DARK_ATTRIBUTE_SELECTOR = ':root[data-theme="dark"]'
PALETTE_SELECTORS = (LIGHT_SELECTOR, DARK_MEDIA_SELECTOR, DARK_ATTRIBUTE_SELECTOR)

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

# (前景トークン, 背景トークン, 必要な比)。装飾トークン
# (--maatlog-color-border / --maatlog-code-border / 面としての
# --maatlog-inline-code-background) には最低比を課さない。
CONTRAST_PAIRS = (
    ("--maatlog-color-text", "--maatlog-color-background", 4.5),
    ("--maatlog-color-text", "--maatlog-color-surface", 4.5),
    ("--maatlog-color-text", "--maatlog-color-surface-hover", 4.5),
    ("--maatlog-color-muted", "--maatlog-color-background", 4.5),
    ("--maatlog-color-muted", "--maatlog-color-surface", 4.5),
    ("--maatlog-color-link", "--maatlog-color-background", 4.5),
    ("--maatlog-color-link", "--maatlog-color-surface", 4.5),
    ("--maatlog-color-accent", "--maatlog-color-background", 4.5),
    ("--maatlog-color-accent", "--maatlog-color-surface", 4.5),
    ("--maatlog-code-text", "--maatlog-code-background", 4.5),
    ("--maatlog-inline-code-text", "--maatlog-inline-code-background", 4.5),
    ("--maatlog-badge-text", "--maatlog-badge-background", 4.5),
    # 操作できる部品の境界は非テキスト UI として 3:1。
    ("--maatlog-color-control-border", "--maatlog-color-background", 3.0),
    ("--maatlog-color-control-border", "--maatlog-color-surface", 3.0),
)


def palette_css(name: str) -> str:
    """パレット ``name`` を定義している CSS の中身。

    既定パレットはテーマ自身の ``maatlog.css`` が持つ。二重管理を避けるため
    パレットファイルは作らない、という設計をここでも守る。
    """
    if name == DEFAULT_PALETTE:
        return (BASE_STATIC / "maatlog.css").read_text(encoding="utf-8")
    return (PALETTES_DIR / f"{name}.css").read_text(encoding="utf-8")


def _rule_body(css: str, selector: str) -> str:
    start = css.index(f"{selector} {{")
    return css[css.index("{", start) + 1 : css.index("}", start)]


def block_tokens(css: str, selector: str) -> dict[str, str]:
    """``selector`` のブロックが宣言するカスタムプロパティを返す。"""
    tokens: dict[str, str] = {}
    for declaration in _rule_body(css, selector).split(";"):
        name, separator, value = declaration.partition(":")
        if separator and name.strip().startswith("--"):
            tokens[name.strip()] = value.strip()
    return tokens


def _relative_luminance(colour: str) -> float:
    digits = colour.lstrip("#")
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    channels = [int(digits[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    first, second = _relative_luminance(foreground), _relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def test_contrast_ratio_matches_known_values() -> None:
    # 実装が正しいことを既知の値で確かめてから、パレットの検証に使う。
    assert contrast_ratio("#000", "#fff") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#fff", "#fff") == pytest.approx(1.0, abs=0.01)


@pytest.mark.parametrize("palette", PALETTES)
@pytest.mark.parametrize("selector", PALETTE_SELECTORS)
def test_palette_declares_every_colour_token(palette: str, selector: str) -> None:
    # 欠けたトークンはテーマの既定値にフォールバックし、2 つのパレットが
    # 混ざった配色になる。3 ブロックすべてで 17 個そろっていること。
    tokens = block_tokens(palette_css(palette), selector)

    assert set(COLOR_TOKENS) <= set(tokens), sorted(set(COLOR_TOKENS) - set(tokens))


@pytest.mark.parametrize("palette", ADDITIONAL_PALETTES)
@pytest.mark.parametrize("selector", PALETTE_SELECTORS)
def test_additional_palette_declares_only_colour_tokens(palette: str, selector: str) -> None:
    # パレットが差し替えるのは色だけ。余白・角丸・フォント・color-scheme を
    # 持ち込むと、パレットごとにレイアウトが割れる。
    # 別名トークン（--maatlog-color-primary / --maatlog-card-background /
    # --maatlog-banner-background / --maatlog-shadow-sm / --maatlog-shadow-md）も
    # 書かない。maatlog.css の :root が元トークンを参照しており、自動で追従する。
    css = palette_css(palette)

    assert set(block_tokens(css, selector)) == set(COLOR_TOKENS)
    for declaration in _rule_body(css, selector).split(";"):
        name, separator, _value = declaration.partition(":")
        if separator:
            assert name.strip().startswith("--"), name.strip()


@pytest.mark.parametrize("palette", PALETTES)
def test_both_dark_blocks_declare_the_same_values(palette: str) -> None:
    # ダークの値は media クエリ側と data-theme 側の 2 箇所に書く必要がある。
    # 片方だけ更新する事故をパレットごとに止める。
    css = palette_css(palette)

    assert block_tokens(css, DARK_MEDIA_SELECTOR) == block_tokens(css, DARK_ATTRIBUTE_SELECTOR)


@pytest.mark.parametrize("palette", PALETTES)
@pytest.mark.parametrize("selector", [LIGHT_SELECTOR, DARK_ATTRIBUTE_SELECTOR])
@pytest.mark.parametrize(("foreground", "background", "minimum"), CONTRAST_PAIRS)
def test_palette_meets_wcag_aa(palette: str, selector: str, foreground: str, background: str, minimum: float) -> None:
    tokens = block_tokens(palette_css(palette), selector)
    ratio = contrast_ratio(tokens[foreground], tokens[background])

    assert ratio >= minimum, f"{palette} {selector}: {foreground} on {background} = {ratio:.2f}"


@pytest.mark.parametrize("palette", ADDITIONAL_PALETTES)
def test_palette_file_holds_no_colour_outside_its_tokens(palette: str) -> None:
    # パレットファイルはトークン宣言だけを持つ。セレクタに直接色を書かない。
    css = re.sub(r"--[\w-]+\s*:[^;]*;", "", palette_css(palette))

    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", css) == []


def test_every_additional_palette_ships_a_stylesheet() -> None:
    missing = [name for name in ADDITIONAL_PALETTES if not (PALETTES_DIR / f"{name}.css").is_file()]

    assert not missing, missing


def test_the_default_palette_ships_no_stylesheet_of_its_own() -> None:
    # 既定の値をパレットファイルにも書くと二重管理になる。
    assert not (PALETTES_DIR / f"{DEFAULT_PALETTE}.css").exists()


_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
_THEME_FIXTURE_PREFIX = f"import sys\nsys.path.insert(0, {str(_FIXTURES_DIR)!r})\n"
_THEME_FIXTURE_EXTENSIONS = ("maatlog_theme_fixtures",)

WIRING_PROJECT = {
    "about.rst": "About\n=====\n\nBody text.\n",
}


def _stylesheet_hrefs(result: BuildResult) -> list[str]:
    """リンクされたスタイルシートのパス（Sphinx の ``?v=`` は落とす）。"""
    page = result.html("about.html")
    return [link["href"].partition("?")[0] for link in page.select("link[rel='stylesheet']") if "href" in link]


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_selected_palette_is_linked_after_the_theme_stylesheet(make_project: ProjectFactory, theme: str) -> None:
    result = make_project(files=WIRING_PROJECT, theme=theme, config={"maatlog_palette": "neon"}).build()
    hrefs = _stylesheet_hrefs(result)

    assert result.asset("_static/palettes/neon.css").is_file()
    assert "_static/palettes/neon.css" in hrefs
    # 後勝ちでトークンを上書きするため、順序が契約。
    assert hrefs.index("_static/palettes/neon.css") > hrefs.index("_static/maatlog.css")


@pytest.mark.parametrize("palette", [None, "indigo"])
def test_the_default_palette_links_no_additional_stylesheet(make_project: ProjectFactory, palette: str | None) -> None:
    # 既定のままのサイトでは、リンクされるスタイルシートが 1 枚増えない。
    # （Sphinx はテーマの static/ を丸ごとコピーするので、ファイル自体は出る。）
    config = {} if palette is None else {"maatlog_palette": palette}
    result = make_project(files=WIRING_PROJECT, config=config).build()

    assert [href for href in _stylesheet_hrefs(result) if "palettes/" in href] == []


def test_unknown_palette_fails_the_build(make_project: ProjectFactory) -> None:
    with pytest.raises(MaatlogBuildError, match="maatlog.theme.palette-unknown") as error:
        make_project(files=WIRING_PROJECT, config={"maatlog_palette": "sunset"}).build()

    # 利用できる名前を列挙して示す。
    assert "neon" in (error.value.diagnostics[0].expected or "")


def test_palette_unaware_theme_rejects_a_non_default_palette(make_project: ProjectFactory) -> None:
    with pytest.raises(MaatlogBuildError, match="maatlog.theme.palette-unsupported"):
        make_project(
            files=WIRING_PROJECT,
            theme="standalone",
            config={"maatlog_palette": "neon"},
            extensions=_THEME_FIXTURE_EXTENSIONS,
            conf_py_prefix=_THEME_FIXTURE_PREFIX,
        ).build()


def test_palette_unaware_theme_still_builds_without_a_palette(make_project: ProjectFactory) -> None:
    # api 1.0 のテーマは何もしなければ従来どおり通る。
    result = make_project(
        files=WIRING_PROJECT,
        theme="standalone",
        extensions=_THEME_FIXTURE_EXTENSIONS,
        conf_py_prefix=_THEME_FIXTURE_PREFIX,
    ).build()

    assert [href for href in _stylesheet_hrefs(result) if "palettes/" in href] == []


def test_an_empty_palette_name_fails_the_build(make_project: ProjectFactory) -> None:
    with pytest.raises(MaatlogBuildError, match="maatlog.config.invalid"):
        make_project(files=WIRING_PROJECT, config={"maatlog_palette": ""}).build()
