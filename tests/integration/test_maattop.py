"""Integration tests for the maattop directive."""

from __future__ import annotations

from typing import cast

from conftest import ProjectFactory, SphinxFactory

from maatlog.domain import MaatlogDomain

RST_WITH_MAATTOP = """\
:maatlog-post: true
:maatlog-published-at: 2026-09-01T09:00:00Z
:maatlog-slug: hero-post

Hero Article
============

.. maatlog:maattop:: images/hero.png
   :alt: A beautiful landscape

Body text here.
"""

MYST_WITH_MAATTOP = """\
---
maatlog-post: true
maatlog-published-at: 2026-09-01T09:00:00Z
maatlog-slug: hero-post-md
maatlog-top-image: images/hero.png
maatlog-top-image-alt: A beautiful landscape
---
# Hero Article MyST

Body text here.
"""


def test_maattop_rst_stores_in_domain(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "post.rst": RST_WITH_MAATTOP,
            "images/hero.png": b"png",
        }
    )
    app.build()

    domain = cast(MaatlogDomain, app.env.get_domain("maatlog"))
    data = domain.maattop_for("post")
    assert data is not None
    assert data["alt"] == "A beautiful landscape"


def test_maattop_node_removed_from_doctree(make_sphinx: SphinxFactory) -> None:
    from maatlog.directives import maattop_node

    app = make_sphinx(
        files={
            "post.rst": RST_WITH_MAATTOP,
            "images/hero.png": b"png",
        }
    )
    app.build()

    doctree = app.env.get_doctree("post")
    assert list(doctree.findall(maattop_node)) == []


def test_maattop_html_output_contains_hero(make_project: ProjectFactory) -> None:
    result = make_project(
        files={
            "post.rst": RST_WITH_MAATTOP,
            "images/hero.png": b"png",
        }
    ).build()

    html = result.path("post.html").read_text(encoding="utf-8")
    assert "maatlog-post-top-image" in html
    assert "A beautiful landscape" in html


def test_maattop_without_top_image_no_hero_html(make_project: ProjectFactory) -> None:
    result = make_project(
        files={
            "post.rst": """\
:maatlog-post: true
:maatlog-published-at: 2026-09-01T09:00:00Z
:maatlog-slug: no-hero

No Hero Article
===============

Body text.
""",
        }
    ).build()

    html = result.path("post.html").read_text(encoding="utf-8")
    assert "maatlog-post-top-image" not in html


def test_maattop_myst_frontmatter_stores_in_domain(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "post.md": MYST_WITH_MAATTOP,
            "images/hero.png": b"png",
        }
    )
    app.build()

    domain = cast(MaatlogDomain, app.env.get_domain("maatlog"))
    data = domain.maattop_for("post")
    assert data is not None
    assert data["alt"] == "A beautiful landscape"


def test_maatlog_top_image_title_font_injected(make_project: ProjectFactory) -> None:
    result = make_project(
        config={"maatlog_top_image_title_font": "Georgia, serif"},
        files={
            "post.rst": RST_WITH_MAATTOP,
            "images/hero.png": b"png",
        },
    ).build()

    html = result.path("post.html").read_text(encoding="utf-8")
    assert "--maatlog-top-image-title-font" in html
    assert "Georgia, serif" in html


def test_maatlog_top_image_title_font_keeps_quotes_unescaped(make_project: ProjectFactory) -> None:
    """``<style>`` は raw text なので、HTML エスケープするとフォント指定が壊れる。"""
    result = make_project(
        config={"maatlog_top_image_title_font": '"Noto Sans JP", serif'},
        files={
            "post.rst": RST_WITH_MAATTOP,
            "images/hero.png": b"png",
        },
    ).build()

    html = result.path("post.html").read_text(encoding="utf-8")
    assert "&#34;" not in html
    assert '--maatlog-top-image-title-font: "Noto Sans JP", serif;' in html
