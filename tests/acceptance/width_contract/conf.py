"""幅契約共有 fixture プロジェクト（Issue #202 で作成。以降の内容変更は Issue への記録と所有者間の調整を要する）。

B(#203) は content width、C(#204) は shell、D(#205) は全 AC の実測に使う。
``maatlog_content_width`` は意図的に設定しない。ビルドごとの config_overrides で
None / "90%" / "100%" / "72rem" / "clamp(42rem, 70vw, 90rem)" を切り替えて検証する（AC3）。
"""

from __future__ import annotations

extensions = [
    "maatlog",
    "myst_parser",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
root_doc = "index"

project = "MaatLog Width Contract"
author = "MaatLog"

html_theme = "maatlog-default"
html_baseurl = "https://width.test/"

maatlog_timezone = "UTC"
maatlog_tags = {"sphinx": "Sphinx"}
maatlog_categories = {"engineering": "Engineering"}
maatlog_authors = {"alice": "Alice"}
maatlog_archive_docname = "blog"
maatlog_generate_feeds = False

# 表番号・コード番号の参照（numref）を検証する。
numfig = True

exclude_patterns = [
    "**/__pycache__",
]
