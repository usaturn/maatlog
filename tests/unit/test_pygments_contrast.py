"""シンタックス色のコントラストを「下限記録」として固定する。

Theme API 1.6 の方針: シンタックストークン色は装飾であり、WCAG 2.2 AA
（4.5:1）の対象外とする。コードの全文字は --maatlog-code-text ×
--maatlog-code-background で描かれる地の色を持ち、その組には AA を課してある
（tests/integration/test_palettes.py）。ハイライトはその上に載る冗長な符号化で、
色を失っても内容は読める。

そのうえで、設計時の実測値を下限として記録する。等値ではなく下限にするのは
scripts/ci/verify.sh の latest プロファイルが Pygments を上げうるためで、
上振れは通し、劣化だけを止める。

コントラストの計算式は tests/unit/test_theme_contrast.py と
tests/integration/test_palettes.py と同じものを持つ。テスト間で実装を import
し合うと片方の移動でもう片方が壊れるため、このリポジトリの既存方針に従って
小さな重複を許している。
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, cast

import pytest
from pygments.styles import get_style_by_name  # pyright: ignore[reportUnknownVariableType]

THEMES_ROOT = Path(__file__).resolve().parents[2] / "src" / "maatlog" / "themes"
BASE_STATIC = THEMES_ROOT / "maatlog-base" / "static"
PALETTES_DIR = BASE_STATIC / "palettes"
MANIFEST = THEMES_ROOT / "maatlog-base" / "maatlog-theme.toml"

DEFAULT_PALETTE = "indigo"
LIGHT_SELECTOR = ":root"
DARK_SELECTOR = ':root[data-theme="dark"]'

# 設計時（Pygments 2.20.0）の実測。各スタイルが色を与える全トークンの前景色を
# そのパレットの --maatlog-code-background に対して測った最小比。
# (パレット, セレクタ) -> 下限
BASELINE = {
    ("indigo", LIGHT_SELECTOR): 3.89,
    ("indigo", DARK_SELECTOR): 3.75,
    ("github", LIGHT_SELECTOR): 4.12,
    ("github", DARK_SELECTOR): 3.77,
    ("solarized", LIGHT_SELECTOR): 2.79,
    ("solarized", DARK_SELECTOR): 2.42,
    ("nord", LIGHT_SELECTOR): 2.43,
    ("nord", DARK_SELECTOR): 1.96,
    ("neon", LIGHT_SELECTOR): 1.90,
    ("neon", DARK_SELECTOR): 1.90,
}


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
    # 実装が正しいことを既知の値で確かめてから、ベースラインの検証に使う。
    assert contrast_ratio("#000", "#fff") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#fff", "#fff") == pytest.approx(1.0, abs=0.01)


def declared_styles() -> dict[str, str]:
    """maatlog-base が宣言する パレット -> Pygments スタイル。"""
    document = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    return dict(document["maatlog"]["pygments"])


def code_background(palette: str, selector: str) -> str:
    source = BASE_STATIC / "maatlog.css" if palette == DEFAULT_PALETTE else PALETTES_DIR / f"{palette}.css"
    css = source.read_text(encoding="utf-8")
    start = css.index(f"{selector} {{")
    body = css[css.index("{", start) + 1 : css.index("}", start)]
    for declaration in body.split(";"):
        name, separator, value = declaration.partition(":")
        if separator and name.strip() == "--maatlog-code-background":
            return value.strip()
    raise AssertionError(f"{palette} {selector}: --maatlog-code-background not declared")


def token_colours(style: str) -> list[str]:
    colours: set[str] = set()
    style_cls = cast(Any, get_style_by_name)(style)
    for _token, item in style_cls:
        colour = item.get("color")
        if isinstance(colour, str) and colour:
            colours.add("#" + colour)
    return sorted(colours)


def test_every_palette_declares_a_pygments_style() -> None:
    # 宣言漏れは静かにフォールバックするので、ここで数を固定する。
    document = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))

    assert set(declared_styles()) == set(document["maatlog"]["palettes"])


@pytest.mark.parametrize(("palette", "selector"), sorted(BASELINE))
def test_syntax_colours_do_not_fall_below_the_recorded_minimum(palette: str, selector: str) -> None:
    background = code_background(palette, selector)
    style = declared_styles()[palette]
    worst = min(contrast_ratio(colour, background) for colour in token_colours(style))

    assert worst >= BASELINE[(palette, selector)] - 0.005, (
        f"{palette} {selector} ({style}): {worst:.2f} < {BASELINE[(palette, selector)]:.2f}"
    )
