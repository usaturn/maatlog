"""テーマ同梱の静的アセットをソースツリーから読み取る helper。"""

from __future__ import annotations

from pathlib import Path

THEMES_ROOT = Path(__file__).resolve().parents[2] / "src" / "maatlog" / "themes"


def theme_stylesheet(theme: str) -> str:
    """``src/maatlog/themes/<theme>/static/maatlog.css`` の内容。

    静的な宣言検査は生成物ではなくソースを直接読む。生成 ``_static/maatlog.css``
    がこの内容をそのまま配することは、各テーマの結合検査が担保する。
    """
    return (THEMES_ROOT / theme / "static" / "maatlog.css").read_text(encoding="utf-8")
