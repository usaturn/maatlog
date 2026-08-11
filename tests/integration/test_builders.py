"""Builder capability gate: full HTML, document-only, and partial HTML."""

from __future__ import annotations

from collections.abc import Mapping
from io import StringIO
from pathlib import Path

import pytest
from conftest import SphinxFactory
from docutils import nodes
from sphinx.application import Sphinx

from maatlog.builders import (
    PARTIAL_SUPPORT_CODE,
    BuilderCapability,
    builder_capability,
)

MIXED_PROJECT: dict[str, str] = {
    "index.rst": """\
Root
====

See :maatlog:post:`hello` and :maatlog:tag:`Sphinx <sphinx>`.

.. toctree::
   :hidden:

   hello
""",
    "hello.md": """---
maatlog-post: true
maatlog-slug: hello
maatlog-published-at: 2026-07-15T12:00:00Z
maatlog-tags: [sphinx]
maatlog-categories: [engineering]
maatlog-authors: [alice]
---
# Hello

Post body for builder matrix tests.
""",
}

MIXED_CONFIG: dict[str, object] = {
    "maatlog_timezone": "UTC",
    "maatlog_tags": {"sphinx": "Sphinx"},
    "maatlog_categories": {"engineering": "Engineering"},
    "maatlog_authors": {"alice": "Alice"},
    "maatlog_archive_docname": "blog",
    "html_baseurl": "https://example.test/",
}


def _write_project(root: Path, files: Mapping[str, str], config: Mapping[str, object]) -> Path:
    srcdir = root / "source"
    srcdir.mkdir(parents=True)
    extension_list = ["maatlog"]
    config_lines = [
        f"extensions = {list(extension_list)!r}",
        "source_suffix = {'.rst': 'restructuredtext', '.md': 'markdown'}",
        "root_doc = 'index'",
        "html_theme = 'maatlog-default'",
    ]
    for name, value in config.items():
        config_lines.append(f"{name} = {value!r}")
    (srcdir / "conf.py").write_text("\n".join(config_lines) + "\n", encoding="utf-8")
    for name, content in files.items():
        target = srcdir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return srcdir


def _make_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    builder: str,
    warningiserror: bool,
    config: Mapping[str, object] | None = None,
    files: Mapping[str, str] | None = None,
) -> Sphinx:
    """Create a Sphinx app with explicit warningiserror (for partial-support)."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1785542400")
    root = tmp_path / f"builder-{builder}-{warningiserror}"
    srcdir = _write_project(root, files or MIXED_PROJECT, {**MIXED_CONFIG, **(config or {})})
    warning_stream = StringIO()
    app = Sphinx(
        str(srcdir),
        str(srcdir),
        str(root / "output"),
        str(root / "doctrees"),
        builder,
        status=StringIO(),
        warning=warning_stream,
        warningiserror=warningiserror,
        freshenv=True,
    )
    # Attach stream for tests that inspect warning text without -W.
    app.__dict__["_maatlog_test_warning_stream"] = warning_stream
    return app


@pytest.mark.parametrize(
    ("builder", "capability"),
    [
        ("html", BuilderCapability.FULL_HTML),
        ("dirhtml", BuilderCapability.FULL_HTML),
        ("text", BuilderCapability.DOCUMENT_ONLY),
        ("singlehtml", BuilderCapability.PARTIAL_HTML),
    ],
)
def test_builder_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    builder: str,
    capability: BuilderCapability,
) -> None:
    # singlehtml emits a partial-support warning during builder-inited; allow it.
    app = _make_app(tmp_path, monkeypatch, builder=builder, warningiserror=False)
    assert builder_capability(app.builder) is capability


@pytest.mark.parametrize("builder", ["text", "latex"])
def test_document_only_builds_without_html_feature_failures(
    make_sphinx: SphinxFactory,
    builder: str,
) -> None:
    """Document-only builders process posts and post roles without feed/theme CSS errors."""
    # No html_baseurl: must not raise maatlog.feed.baseurl-required.
    app = make_sphinx(
        files=MIXED_PROJECT,
        config={
            **MIXED_CONFIG,
            "html_baseurl": "",
            # Intentionally not a MaatLog theme — Theme API must not hard-fail.
            "html_theme": "alabaster",
        },
        builder=builder,
        theme="alabaster",
    )
    app.build()

    outdir = Path(app.outdir)
    if builder == "text":
        text = (outdir / "index.txt").read_text(encoding="utf-8")
        assert "Hello" in text or "hello" in text
        assert "Post body for builder matrix tests" in (outdir / "hello.txt").read_text(encoding="utf-8")
    else:
        # LaTeX source only — no PDF toolchain required.
        tex_files = list(outdir.rglob("*.tex"))
        assert tex_files, "expected LaTeX source under outdir"
        combined = "\n".join(path.read_text(encoding="utf-8") for path in tex_files)
        assert "Hello" in combined or "hello" in combined

    assert not list(outdir.rglob("atom.xml"))
    assert not list(outdir.rglob("blog/**/*.html"))

    doctree = app.env.get_and_resolve_doctree("index", app.builder, tags=app.builder.tags)
    post_refs = [n for n in doctree.findall(nodes.reference) if "hello" in n.astext().lower() or n.astext() == "hello"]
    # Role may render display text from the post title after resolution.
    title_refs = [n for n in doctree.findall(nodes.reference) if n.astext() in {"hello", "Hello"}]
    assert post_refs or title_refs, "post role should remain a reference on document-only builders"

    tag_refs = [n for n in doctree.findall(nodes.reference) if n.astext() == "Sphinx"]
    assert not tag_refs, "taxonomy role must not be a reference on document-only builders"
    tag_inlines = [
        n for n in doctree.findall(nodes.inline) if n.astext() == "Sphinx" and not isinstance(n, nodes.reference)
    ]
    assert tag_inlines, "taxonomy role should resolve to an inline label"


def test_partial_html_warns_once_and_disables_html_features(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from maatlog.builders import warn_partial_support_once

    app = _make_app(tmp_path, monkeypatch, builder="singlehtml", warningiserror=False)
    stream: StringIO = app.__dict__["_maatlog_test_warning_stream"]
    init_text = stream.getvalue()
    assert init_text.count(PARTIAL_SUPPORT_CODE) == 1
    assert "limited support" in init_text

    # Flag must suppress further emissions for the same application.
    stream.seek(0)
    stream.truncate(0)
    warn_partial_support_once(app)
    warn_partial_support_once(app)
    app.build()
    assert PARTIAL_SUPPORT_CODE not in stream.getvalue()

    outdir = Path(app.outdir)
    assert not list(outdir.rglob("atom.xml"))
    # No dedicated archive HTML pages for singlehtml.
    assert not (outdir / "blog").exists()

    doctree = app.env.get_and_resolve_doctree("index", app.builder, tags=app.builder.tags)
    tag_refs = [n for n in doctree.findall(nodes.reference) if n.astext() == "Sphinx"]
    assert not tag_refs
    tag_inlines = [
        n for n in doctree.findall(nodes.inline) if n.astext() == "Sphinx" and not isinstance(n, nodes.reference)
    ]
    assert tag_inlines

    title_refs = [n for n in doctree.findall(nodes.reference) if n.astext() in {"hello", "Hello"}]
    assert title_refs, "post role should still resolve on partial HTML builders"


def test_partial_html_warning_sets_status_under_warningiserror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sphinx 9 ``-W`` / warningiserror sets statuscode after build (no raise)."""
    app = _make_app(tmp_path, monkeypatch, builder="singlehtml", warningiserror=True)
    app.build()
    assert app.statuscode == 1
    stream: StringIO = app.__dict__["_maatlog_test_warning_stream"]
    assert PARTIAL_SUPPORT_CODE in stream.getvalue()


def test_full_html_still_emits_archives_and_feeds(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files=MIXED_PROJECT, config=MIXED_CONFIG, builder="html")
    app.build()
    outdir = Path(app.outdir)
    assert (outdir / "blog" / "atom.xml").is_file()
    assert (outdir / "blog.html").is_file() or (outdir / "blog" / "index.html").is_file()
