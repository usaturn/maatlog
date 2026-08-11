"""Sphinx extension: register third-party MaatLog theme fixtures for tests.

Does not import MaatLog private modules — only uses Sphinx public
``app.add_html_theme``.
"""

from __future__ import annotations

from pathlib import Path

from sphinx.application import Sphinx
from sphinx.util.typing import ExtensionMetadata

THEMES_ROOT = Path(__file__).resolve().parent / "themes"


def setup(app: Sphinx) -> ExtensionMetadata:
    for path in sorted(THEMES_ROOT.iterdir()):
        if path.is_dir() and (path / "theme.conf").is_file():
            app.add_html_theme(path.name, str(path))
    return {
        "version": "1.0.0",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
