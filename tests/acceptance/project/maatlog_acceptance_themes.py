"""Register acceptance Theme API fixtures via Sphinx ``add_html_theme``.

Keeps third-party theme discovery on the public Sphinx API instead of relying
only on ``html_theme_path``. Does not import MaatLog private modules.
"""

from __future__ import annotations

from pathlib import Path

from sphinx.application import Sphinx
from sphinx.util.typing import ExtensionMetadata


def setup(app: Sphinx) -> ExtensionMetadata:
    themes_root = Path(app.confdir) / "_themes"
    for path in sorted(themes_root.iterdir()):
        if path.is_dir() and (path / "theme.conf").is_file():
            app.add_html_theme(path.name, str(path))
    return {
        "version": "1.0.0",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
