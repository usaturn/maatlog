"""Unit tests for the MyST front matter hero image collector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from maatlog.metadata import collect_maattop_from_myst

SOURCE_TEXT = """---
maatlog-top-image: images/hero.png
maatlog-top-image-alt: Hero
---

# Title
"""


def _make_app(*, srcdir: Path, source: Path, docname: str) -> MagicMock:
    """Return a Sphinx app double wired for ``collect_maattop_from_myst``."""
    app = MagicMock()
    app.srcdir = str(srcdir)
    app.env.current_document.docname = docname
    app.env.doc2path.return_value = str(source)
    app.env.get_domain.return_value = MagicMock()
    app.__dict__["_maatlog_sources_by_docname"] = {docname: [SOURCE_TEXT]}
    return app


def test_collect_maattop_from_myst_registers_srcdir_relative_key(tmp_path: Path) -> None:
    source = tmp_path / "posts" / "article.md"
    source.parent.mkdir(parents=True)
    source.write_text(SOURCE_TEXT, encoding="utf-8")
    img = source.parent / "images" / "hero.png"
    img.parent.mkdir()
    img.write_bytes(b"png")

    app = _make_app(srcdir=tmp_path, source=source, docname="posts/article")
    collect_maattop_from_myst(app, MagicMock())

    app.env.images.add_file.assert_called_once_with("posts/article", "posts/images/hero.png")
    app.env.get_domain.return_value.note_maattop.assert_called_once_with(
        "posts/article", uri="posts/images/hero.png", alt="Hero"
    )


def test_collect_maattop_from_myst_registers_key_when_srcdir_is_unresolved(tmp_path: Path) -> None:
    """The registered image key stays srcdir-relative even when ``app.srcdir`` is not resolved.

    ``validate_image_uri`` returns a resolved path, so relativising against a raw
    ``app.srcdir`` (a symlink here) breaks unless the caller resolves it too.
    The posix separator half of the same expression cannot be asserted on POSIX,
    where ``str(Path)`` and ``Path.as_posix()`` are identical.
    """
    real_srcdir = tmp_path / "real"
    source = real_srcdir / "posts" / "article.md"
    source.parent.mkdir(parents=True)
    source.write_text(SOURCE_TEXT, encoding="utf-8")
    img = source.parent / "images" / "hero.png"
    img.parent.mkdir()
    img.write_bytes(b"png")

    linked_srcdir = tmp_path / "link"
    linked_srcdir.symlink_to(real_srcdir)

    app = _make_app(
        srcdir=linked_srcdir,
        source=linked_srcdir / "posts" / "article.md",
        docname="posts/article",
    )
    collect_maattop_from_myst(app, MagicMock())

    app.env.images.add_file.assert_called_once_with("posts/article", "posts/images/hero.png")
