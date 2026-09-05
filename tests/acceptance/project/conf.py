"""Acceptance Sphinx project for MaatLog MVP A1–A12 scenarios."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow ``automodule:: api`` without installing the project as a package.
sys.path.insert(0, str(Path(__file__).resolve().parent))

extensions = [
    "maatlog",
    "myst_parser",
    "sphinx.ext.autodoc",
    # Registers contract_theme / incompatible_theme / missing_* via add_html_theme.
    "maatlog_acceptance_themes",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
root_doc = "index"

project = "MaatLog Acceptance"
author = "MaatLog"

html_theme = "maatlog-default"
html_baseurl = "https://example.test/docs/"
html_search_language = "ja"

# Build-time clock for publication boundaries (2026-08-15T00:00:00Z).
# Tests also set SOURCE_DATE_EPOCH; keep conf free of side effects.

maatlog_timezone = "UTC"
maatlog_tags = {
    "sphinx": "Sphinx",
    "python": "Python",
}
maatlog_categories = {
    "engineering": "Engineering",
    "ops": "Operations",
}
maatlog_authors = {
    "alice": "Alice",
    "bob": "Bob",
    "carol": "Carol",
    "dave": "Dave",
}
maatlog_author_profiles = {
    "alice": {
        "role": "Editor & Developer",
        "avatar": "authors/alice.png",
        "bio_short": "Python / Cloud / Sphinx developer.",
        "interests": ["Python", "Cloud", "Sphinx"],
        "links": [
            {"type": "github", "url": "https://github.com/example"},
            {"type": "website", "url": "https://example.com/"},
        ],
        "about_docname": "authors/alice",
    },
}
maatlog_default_author = "alice"
maatlog_archive_docname = "blog"
maatlog_home_docname = "home"
maatlog_page_size = 10
maatlog_generate_feeds = True
maatlog_feed_taxonomies = ("tag", "category", "author", "month")
maatlog_feed_limit = 20

exclude_patterns = [
    "_themes",
    "api.py",
    "**/__pycache__",
]
