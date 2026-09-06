"""Magazine Home (Issue #176) の外観・操作性を検証する専用 acceptance プロジェクト."""

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

project = "MaatLog Magazine"
author = "MaatLog"

html_theme = "maatlog-default"
html_baseurl = "https://magazine.test/"

maatlog_timezone = "UTC"
maatlog_tags = {
    "sphinx": "Sphinx",
    "python": "Python",
    "design": "Design",
}
maatlog_categories = {
    "engineering": "Engineering",
    "ops": "Operations",
}
maatlog_authors = {
    "alice": "Alice",
    "bob": "Bob",
    "carol": "Carol",
}
maatlog_author_profiles = {
    "alice": {
        "role": "Editor",
        "bio_short": "Magazine fixture author.",
        "interests": ["Python", "Sphinx"],
        "links": [{"type": "website", "url": "https://magazine.test/alice/"}],
        "about_docname": "authors/alice",
    },
}
maatlog_default_author = "alice"
maatlog_home_docname = "home"
maatlog_archive_docname = "blog"
# 専用 Home では Latest の上限。Featured 3 + Latest 9 = 公開 12 本ちょうど。
maatlog_page_size = 9
maatlog_generate_feeds = True

exclude_patterns = [
    "**/__pycache__",
]
