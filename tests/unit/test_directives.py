"""Unit tests for maattop_node and MaattopDirective."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from maatlog.directives import MaattopDirective, maattop_node
from maatlog.errors import MaatlogBuildError


def _make_directive(uri: str, alt: str = "", *, srcdir: Path, source: Path) -> MaattopDirective:
    """Return a MaattopDirective instance with mocked Sphinx env."""
    directive = MaattopDirective.__new__(MaattopDirective)
    directive.arguments = [uri]
    directive.options = {"alt": alt} if alt else {}
    directive.content = MagicMock()
    directive.lineno = 1
    directive.content_offset = 0
    directive.block_text = ""
    directive.state = MagicMock()
    directive.state_machine = MagicMock()
    directive.state_machine.get_source_and_line.return_value = (str(source), 1)
    env = MagicMock()
    env.docname = "posts/test-post"
    env.doc2path.return_value = str(source)
    env.srcdir = str(srcdir)
    env.note_dependency = MagicMock()
    env.images = MagicMock()
    env.images.add_file = MagicMock()
    directive.state.document.settings.env = env
    return directive


def test_maattop_directive_produces_node(tmp_path: Path) -> None:
    source = tmp_path / "posts" / "test-post.rst"
    source.parent.mkdir()
    source.write_text("placeholder", encoding="utf-8")
    img = source.parent / "images" / "hero.png"
    img.parent.mkdir()
    img.write_bytes(b"png")

    directive = _make_directive("images/hero.png", "Hero image", srcdir=tmp_path, source=source)
    result = directive.run()

    assert len(result) == 1
    assert isinstance(result[0], maattop_node)
    node = result[0]
    assert node["uri"] == "posts/images/hero.png"
    assert node["alt"] == "Hero image"


def test_maattop_directive_alt_defaults_to_empty(tmp_path: Path) -> None:
    source = tmp_path / "post.rst"
    source.write_text("placeholder", encoding="utf-8")
    img = tmp_path / "hero.png"
    img.write_bytes(b"png")

    directive = _make_directive("hero.png", srcdir=tmp_path, source=source)
    result = directive.run()

    assert isinstance(result[0], maattop_node)
    node = result[0]
    assert node["alt"] == ""


def test_maattop_directive_rejects_invalid_uri(tmp_path: Path) -> None:
    source = tmp_path / "post.rst"
    source.write_text("placeholder", encoding="utf-8")

    directive = _make_directive("https://example.com/hero.png", srcdir=tmp_path, source=source)
    with pytest.raises(MaatlogBuildError):
        directive.run()


def test_maattop_directive_rejects_missing_file(tmp_path: Path) -> None:
    source = tmp_path / "post.rst"
    source.write_text("placeholder", encoding="utf-8")

    directive = _make_directive("missing.png", srcdir=tmp_path, source=source)
    with pytest.raises(MaatlogBuildError):
        directive.run()


def test_maattop_directive_registers_srcdir_relative_key_when_srcdir_is_unresolved(tmp_path: Path) -> None:
    """The registered image key stays srcdir-relative even when ``env.srcdir`` is not resolved.

    ``validate_image_uri`` returns a resolved path, so relativising against a raw
    ``env.srcdir`` (a symlink here) breaks unless the caller resolves it too.
    The posix separator half of the same expression cannot be asserted on POSIX,
    where ``str(Path)`` and ``Path.as_posix()`` are identical.
    """
    real_srcdir = tmp_path / "real"
    source = real_srcdir / "posts" / "test-post.rst"
    source.parent.mkdir(parents=True)
    source.write_text("placeholder", encoding="utf-8")
    img = source.parent / "images" / "hero.png"
    img.parent.mkdir()
    img.write_bytes(b"png")

    linked_srcdir = tmp_path / "link"
    linked_srcdir.symlink_to(real_srcdir)

    directive = _make_directive(
        "images/hero.png",
        srcdir=linked_srcdir,
        source=linked_srcdir / "posts" / "test-post.rst",
    )
    result = directive.run()

    assert isinstance(result[0], maattop_node)
    node = result[0]
    assert node["uri"] == "posts/images/hero.png"
    env = directive.state.document.settings.env
    env.images.add_file.assert_called_once_with("posts/test-post", "posts/images/hero.png")
