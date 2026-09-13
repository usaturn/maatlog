project = "MaatLog"
copyright = "2026, MaatLog maintainers"
author = "MaatLog maintainers"
language = "ja"
release = "0.5.0"

extensions = [
    "maatlog",
    "myst_parser",
]

exclude_patterns = ["_build"]

html_theme = "maatlog-default"
html_baseurl = "https://example.com/"

maatlog_timezone = "Asia/Tokyo"
maatlog_tagline = "Sphinx を静的ブログに変える拡張"
maatlog_archive_docname = "blog"
maatlog_home_docname = "index"
maatlog_content_width = "90%"
