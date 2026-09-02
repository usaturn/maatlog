"""配色トークンが WCAG 2.2 のコントラスト比を満たすことを固定する。

axe / Lighthouse は「実際に描画された組み合わせ」しか見ないので、
トークン表そのものをここで検証して回帰を防ぐ。
"""

from __future__ import annotations

from pathlib import Path

import pytest

THEMES_ROOT = Path(__file__).resolve().parents[2] / "src" / "maatlog" / "themes"
LIGHT_SELECTOR = ":root"
DARK_SELECTOR = ':root[data-theme="dark"]'

# (前景トークン, 背景トークン, 必要な比)
TEXT_PAIRS = (
    ("--maatlog-color-text", "--maatlog-color-background", 4.5),
    ("--maatlog-color-muted", "--maatlog-color-background", 4.5),
    ("--maatlog-color-link", "--maatlog-color-background", 4.5),
    ("--maatlog-color-accent", "--maatlog-color-background", 4.5),
    ("--maatlog-color-text", "--maatlog-color-surface", 4.5),
    ("--maatlog-color-muted", "--maatlog-color-surface", 4.5),
    ("--maatlog-color-link", "--maatlog-color-surface", 4.5),
    ("--maatlog-color-text", "--maatlog-color-surface-hover", 4.5),
    ("--maatlog-color-muted", "--maatlog-color-surface-hover", 4.5),
    ("--maatlog-code-text", "--maatlog-code-background", 4.5),
    ("--maatlog-inline-code-text", "--maatlog-inline-code-background", 4.5),
    ("--maatlog-badge-text", "--maatlog-badge-background", 4.5),
    # 非テキスト UI（トグルボタンの枠）は 3:1。
    ("--maatlog-color-control-border", "--maatlog-color-background", 3.0),
)


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


def _tokens(theme: str, selector: str) -> dict[str, str]:
    css = (THEMES_ROOT / theme / "static" / "maatlog.css").read_text(encoding="utf-8")
    start = css.index(f"{selector} {{")
    body = css[css.index("{", start) + 1 : css.index("}", start)]
    tokens: dict[str, str] = {}
    for declaration in body.split(";"):
        name, separator, value = declaration.partition(":")
        if separator and name.strip().startswith("--"):
            tokens[name.strip()] = value.strip()
    return tokens


def test_contrast_ratio_matches_known_values() -> None:
    # 実装が正しいことを既知の値で確かめてから、パレットの検証に使う。
    assert contrast_ratio("#000", "#fff") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#fff", "#fff") == pytest.approx(1.0, abs=0.01)


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
@pytest.mark.parametrize("selector", [LIGHT_SELECTOR, DARK_SELECTOR])
@pytest.mark.parametrize(("foreground", "background", "minimum"), TEXT_PAIRS)
def test_palette_meets_wcag_contrast(
    theme: str, selector: str, foreground: str, background: str, minimum: float
) -> None:
    tokens = _tokens(theme, selector)
    ratio = contrast_ratio(tokens[foreground], tokens[background])

    assert ratio >= minimum, f"{theme} {selector}: {foreground} on {background} = {ratio:.2f}"


# 既定パレット indigo の設計時の比。WCAG 下限だけでは
# パレットの静かな劣化（例 link をわずかに暗くする）を止められない。
EXPECTED_RATIOS = {
    LIGHT_SELECTOR: {
        ("--maatlog-color-text", "--maatlog-color-background"): 16.47,
        ("--maatlog-color-muted", "--maatlog-color-background"): 7.14,
        ("--maatlog-color-link", "--maatlog-color-background"): 7.49,
        ("--maatlog-color-accent", "--maatlog-color-background"): 5.83,
        ("--maatlog-code-text", "--maatlog-code-background"): 14.48,
        ("--maatlog-inline-code-text", "--maatlog-inline-code-background"): 9.27,
        ("--maatlog-badge-text", "--maatlog-badge-background"): 9.27,
        ("--maatlog-color-text", "--maatlog-color-surface-hover"): 15.46,
        ("--maatlog-color-muted", "--maatlog-color-surface-hover"): 6.70,
        ("--maatlog-color-control-border", "--maatlog-color-background"): 4.51,
    },
    DARK_SELECTOR: {
        ("--maatlog-color-text", "--maatlog-color-background"): 16.61,
        ("--maatlog-color-muted", "--maatlog-color-background"): 9.58,
        ("--maatlog-color-link", "--maatlog-color-background"): 10.82,
        ("--maatlog-color-accent", "--maatlog-color-background"): 11.60,
        ("--maatlog-code-text", "--maatlog-code-background"): 17.38,
        ("--maatlog-inline-code-text", "--maatlog-inline-code-background"): 10.51,
        ("--maatlog-badge-text", "--maatlog-badge-background"): 10.51,
        ("--maatlog-color-text", "--maatlog-color-surface-hover"): 12.65,
        ("--maatlog-color-muted", "--maatlog-color-surface-hover"): 7.29,
        ("--maatlog-color-control-border", "--maatlog-color-background"): 6.45,
    },
}


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
@pytest.mark.parametrize("selector", [LIGHT_SELECTOR, DARK_SELECTOR])
def test_palette_keeps_the_designed_contrast_ratios(theme: str, selector: str) -> None:
    tokens = _tokens(theme, selector)

    for (foreground, background), expected in EXPECTED_RATIOS[selector].items():
        ratio = contrast_ratio(tokens[foreground], tokens[background])
        assert ratio == pytest.approx(expected, abs=0.01), f"{theme} {selector}: {foreground} on {background}"
