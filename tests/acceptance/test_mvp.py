"""MaatLog MVP acceptance scenarios A1–A12 (Spec 06 §6)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import pytest

from maatlog.feeds import ATOM

if TYPE_CHECKING:
    from acceptance.site import AcceptanceSite

UNPUBLISHED = ("draft", "scheduled", "expired")

# Published-only taxonomy labels/counts on the sidebar (draft/scheduled/expired excluded).
SIDEBAR_COUNTS = (
    ("Sphinx", 2),
    ("Python", 2),
    ("Engineering", 2),
    ("Alice", 2),
    ("2026-08", 2),
)

# Docname stem matches maatlog-slug so Atom path-based slug inference stays stable.
_EXTERNAL_POST = (
    ":orphan:\n"
    "\n"
    ":maatlog-post: true\n"
    ":maatlog-slug: external-post\n"
    ":maatlog-published-at: 2026-07-15T12:00:00Z\n"
    ":maatlog-excerpt: External acceptance summary only.\n"
    ":maatlog-external-url: https://publisher.example/articles/acceptance\n"
    "\n"
    "External acceptance post\n"
    "========================\n"
    "\n"
    "Hidden external body must not appear in Atom content.\n"
)
_EXTERNAL_POST_PATH = "posts/external-post.rst"


def test_a01_parser_parity(site: AcceptanceSite) -> None:
    """A1: equivalent reST / MyST posts share public Post semantics."""
    result = site.build("html")
    assert site.semantic_post(result, "posts/rst-post") == site.semantic_post(result, "posts/md-post")
    # Titles and taxonomies must also align in rendered public archives.
    archive = result.html("blog/tag/sphinx.html")
    assert archive.select_one('.maatlog-post-card[data-slug="rst-post"]')
    assert archive.select_one('.maatlog-post-card[data-slug="md-post"]')


def test_a02_documents_coexist(site: AcceptanceSite) -> None:
    """A2: normal docs, posts, and autodoc share one source tree and search index."""
    result = site.build("html")
    assert result.exists("index.html")
    assert result.exists("api.html")
    assert result.exists("guide.html")
    assert result.exists("posts/rst-post.html")
    assert result.exists("posts/md-post.html")
    assert result.search_index_contains("reStructuredText post")
    assert result.search_index_contains("API reference") or result.search_index_contains("greet")
    assert result.config_value("html_search_language") == "ja"
    # Autodoc page exposes the sample symbol.
    assert "greet" in result.text("api.html")


def test_a03_unpublished_posts_are_excluded(site: AcceptanceSite) -> None:
    """A3: draft / scheduled / expired never appear on public surfaces."""
    result = site.build("html")
    surfaces = site.public_surfaces(result)
    for slug in UNPUBLISHED:
        assert slug not in surfaces.published_slugs
        assert not surfaces.contains_slug(slug)

    # Explicit surface checks: all archive, taxonomy archives, directive, neighbors, Atom.
    assert result.exists("blog.html")
    blog = result.html("blog.html")
    for slug in UNPUBLISHED:
        assert blog.select_one(f'.maatlog-post-card[data-slug="{slug}"]') is None

    for path in (
        "blog/tag/sphinx.html",
        "blog/category/engineering.html",
        "blog/author/alice.html",
        "blog/month/2026-08.html",
    ):
        page = result.html(path)
        for slug in UNPUBLISHED:
            assert page.select_one(f'.maatlog-post-card[data-slug="{slug}"]') is None
            assert slug not in page.text or f'data-slug="{slug}"' not in page.text

    index = result.html("index.html")
    cards = index.select(".maatlog-post-list .maatlog-post-card")
    card_slugs = {attrs.get("data-slug") for attrs in cards}
    assert card_slugs == {"rst-post", "md-post"}

    for post_path in ("posts/rst-post.html", "posts/md-post.html"):
        nav = result.html(post_path)
        nav_text = nav.text
        for slug in UNPUBLISHED:
            assert f"/{slug}" not in nav_text
            assert f"{slug}.html" not in nav_text

    # Sidebar taxonomy counts are published-only (unpublished share the same IDs).
    sidebar_html = result.text("posts/rst-post.html")
    assert 'class="maatlog-sidebar"' in sidebar_html or "maatlog-sidebar" in sidebar_html
    for label, count in SIDEBAR_COUNTS:
        assert re.search(rf">{re.escape(label)}</a>\s*\({count}\)", sidebar_html), (
            f"expected sidebar count {label} ({count}) excluding unpublished"
        )
    # Counts must not inflate to include draft/scheduled/expired (would be 3+).
    for label, _count in SIDEBAR_COUNTS:
        assert not re.search(rf">{re.escape(label)}</a>\s*\([3-9]|\d{{2,}}\)", sidebar_html)

    for atom_path in (
        "blog/atom.xml",
        "blog/tag/sphinx/atom.xml",
        "blog/category/engineering/atom.xml",
        "blog/author/alice/atom.xml",
        "blog/month/2026-08/atom.xml",
    ):
        feed = site.atom(result, atom_path)
        for slug in UNPUBLISHED:
            assert not feed.contains_slug(slug)
            assert slug not in feed.titles


def test_a04_invalid_metadata_is_actionable(site: AcceptanceSite) -> None:
    """A4: duplicate slug and schema violations fail with location, field, expected."""
    error = site.build_invalid("duplicate-slug")
    text = str(error)
    assert "[maatlog.slug.duplicate]" in text
    assert "duplicate.rst" in text
    assert "rst-post.rst" in text
    assert "field=maatlog-slug" in text
    assert "expected=" in text
    assert "ERROR:" in text

    # Schema violations use the stable ``source:line: ERROR: [code]`` form.
    slug_error = site.build_invalid("invalid-slug")
    slug_text = str(slug_error)
    assert re.search(
        r"posts/bad-slug\.rst:\d+: ERROR: \[maatlog\.slug\.invalid\]",
        slug_text,
    )
    assert "field=maatlog-slug" in slug_text
    assert "expected=" in slug_text
    assert "NOT_VALID" in slug_text

    combo_error = site.build_invalid("external-without-excerpt")
    combo_text = str(combo_error)
    assert re.search(
        r"posts/external-bare\.rst:\d+: ERROR: \[maatlog\.metadata\.combination\]",
        combo_text,
    )
    assert "field=maatlog-external-url" in combo_text
    assert "expected=" in combo_text


def test_a05_four_taxonomies_are_navigable(site: AcceptanceSite) -> None:
    """A5: tag / category / author / month archives reach published posts."""
    result = site.build("html")
    for path in (
        "blog/tag/sphinx.html",
        "blog/category/engineering.html",
        "blog/author/alice.html",
        "blog/month/2026-08.html",
    ):
        assert result.exists(path), path
        assert result.links_are_resolvable(path), path
        page = result.html(path)
        assert page.select_one('.maatlog-post-card[data-slug="rst-post"]')
        assert page.select_one('.maatlog-post-card[data-slug="md-post"]')

    # Roles on the index resolve to those archives.
    index = result.html("index.html")
    assert "blog/tag/sphinx" in index.text or "tag/sphinx" in index.text
    post = result.html("posts/rst-post.html")
    assert post.select_one(".maatlog-sidebar")


def test_a06_global_and_taxonomy_atom(site: AcceptanceSite) -> None:
    """A6: global and taxonomy Atom feeds list only published posts with absolute URLs."""
    result = site.build(
        "html",
        extra_files={_EXTERNAL_POST_PATH: _EXTERNAL_POST},
    )
    global_feed = site.atom(result, "blog/atom.xml")
    # Equal published_at → secondary sort by slug: md-post, rst-post; then older external.
    assert global_feed.slugs == ("md-post", "rst-post", "external-post")
    assert global_feed.all_urls_absolute
    assert global_feed.all_ids_absolute
    for atom_id in global_feed.ids:
        parsed = urlparse(atom_id)
        assert parsed.scheme in {"http", "https"}
        assert parsed.netloc

    tag_feed = site.atom(result, "blog/tag/sphinx/atom.xml")
    assert set(tag_feed.slugs) == {"md-post", "rst-post"}
    assert tag_feed.all_urls_absolute
    assert tag_feed.all_ids_absolute

    for relative in (
        "blog/category/engineering/atom.xml",
        "blog/author/alice/atom.xml",
        "blog/month/2026-08/atom.xml",
    ):
        feed = site.atom(result, relative)
        assert set(feed.slugs) == {"md-post", "rst-post"}
        assert feed.all_urls_absolute
        assert feed.all_ids_absolute

    # External post: excerpt content, related local page, absolute primary alternate.
    external = global_feed.entry_by_slug("external-post")
    assert external is not None
    content = external.find(f"{{{ATOM}}}content")
    assert content is not None
    assert content.get("type") == "html"
    assert content.text is not None
    assert "External acceptance summary only" in content.text
    assert "Hidden external body" not in content.text
    related = [link for link in external.findall(f"{{{ATOM}}}link") if link.get("rel") == "related"]
    assert len(related) == 1
    assert related[0].get("href", "").startswith("https://example.test/docs/")
    alternate = next(
        link for link in external.findall(f"{{{ATOM}}}link") if (link.get("rel") or "alternate") == "alternate"
    )
    assert alternate.get("href") == "https://publisher.example/articles/acceptance"
    entry_id = external.findtext(f"{{{ATOM}}}id")
    assert entry_id is not None
    assert entry_id.startswith("https://")


def test_a07_cross_reference_integration(site: AcceptanceSite) -> None:
    """A7: ordinary, Python, and MaatLog roles resolve across the site."""
    result = site.build("html")
    assert result.links_are_resolvable("guide.html")
    assert result.links_are_resolvable("api.html")
    assert result.links_are_resolvable("index.html")
    assert result.links_are_resolvable("posts/rst-post.html")
    guide = result.text("guide.html")
    assert "api" in guide
    assert "md-post" in guide or "posts/md-post" in guide


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_a08_html_and_dirhtml(site: AcceptanceSite, builder: str) -> None:
    """A8: html and dirhtml emit builder-correct posts, archives, feeds, and pagination."""
    result = site.build(builder, config_overrides={"maatlog_page_size": 1})
    expected = site.expected_blog_outputs(builder, page_size=1)
    assert expected <= result.relative_files

    if builder == "html":
        assert result.links_are_resolvable("blog/tag/sphinx.html")
        assert result.links_are_resolvable("posts/rst-post.html")
        assert result.links_are_resolvable("blog/page/2.html")
        assert result.links_are_resolvable("blog/tag/sphinx/page/2.html")
        # Pagination chrome present on multi-page archives.
        archive = result.html("blog.html")
        assert archive.select_one(".maatlog-pagination")
        assert archive.select_one(".maatlog-pagination-next")
        page2 = result.html("blog/page/2.html")
        assert page2.select_one(".maatlog-pagination-prev")
    else:
        assert result.links_are_resolvable("blog/tag/sphinx/index.html")
        assert result.links_are_resolvable("posts/rst-post/index.html")
        assert result.links_are_resolvable("blog/page/2/index.html")
        assert result.links_are_resolvable("blog/tag/sphinx/page/2/index.html")
        archive = result.html("blog/index.html")
        assert archive.select_one(".maatlog-pagination")
        assert archive.select_one(".maatlog-pagination-next")
        page2 = result.html("blog/page/2/index.html")
        assert page2.select_one(".maatlog-pagination-prev")

    # Atom entry alternate hrefs follow builder URI rules (not only inventory paths).
    feed = site.atom(result, "blog/atom.xml")
    assert feed.all_ids_absolute
    assert feed.alternate_hrefs
    for href in feed.alternate_hrefs:
        parsed = urlparse(href)
        assert parsed.scheme in {"http", "https"}
        assert parsed.netloc == "example.test"
        path = parsed.path
        if builder == "html":
            assert path.endswith(".html"), href
            assert not path.endswith("/"), href
        else:
            assert path.endswith("/"), href
            assert not path.endswith(".html"), href


def test_a09_default_theme(site: AcceptanceSite) -> None:
    """A9: maatlog-default alone renders post chrome (sidebar + neighbors)."""
    page = site.build("html", theme="maatlog-default").html("posts/rst-post.html")
    assert page.select_one(".maatlog-sidebar")
    assert page.select_one(".maatlog-post-navigation")
    # With two published posts, neighbors should be present.
    assert page.select_one(".maatlog-nav-older") or page.select_one(".maatlog-nav-newer")
    archive = site.build("html", theme="maatlog-default").html("blog.html")
    assert archive.select_one(".maatlog-sidebar")
    assert archive.select(".maatlog-post-card")


def test_a10_third_party_theme(site: AcceptanceSite) -> None:
    """A10: registered maatlog-base child can override templates/CSS markers."""
    result = site.build("html", theme="contract_theme")
    page = result.html("posts/rst-post.html")
    assert page.select_one(".contract-theme-marker")
    assert result.exists("_static/maatlog.css")
    # Registration is via add_html_theme (extension), not conf html_theme_path alone.
    conf = (site.srcdir / "conf.py").read_text(encoding="utf-8")
    assert "maatlog_acceptance_themes" in conf
    assert "html_theme_path" not in conf or "html_theme_path" not in conf.split("acceptance overrides")[0]


def test_a11_theme_contract_errors(site: AcceptanceSite) -> None:
    """A11: Theme API failures report theme source, contract field, and core/theme API."""
    # Theme name is the diagnostic source (``theme: ERROR: [code]``), not a
    # substring of the code string alone (e.g. ``manifest`` in ``manifest-missing``).
    error = site.build_invalid("incompatible-theme")
    text = str(error)
    assert re.search(
        r"incompatible_theme: ERROR: \[maatlog\.theme\.api-incompatible\]",
        text,
    )
    assert "field=api" in text
    assert "core_api=1.0" in text
    assert "theme_api=2.0" in text
    assert "value=2.0" in text

    missing_manifest = site.build_invalid("missing-manifest")
    manifest_text = str(missing_manifest)
    assert re.search(
        r"missing_manifest: ERROR: \[maatlog\.theme\.manifest-missing\]",
        manifest_text,
    )
    assert "field=manifest" in manifest_text
    assert "core_api=1.0" in manifest_text
    assert "expected=maatlog-theme.toml" in manifest_text

    missing_block = site.build_invalid("missing-block")
    block_text = str(missing_block)
    assert re.search(
        r"missing_block: ERROR: \[maatlog\.theme\.block-missing\]",
        block_text,
    )
    assert "field=block" in block_text
    assert "core_api=1.0" in block_text
    assert "theme_api=1.0" in block_text

    missing_templates = site.build_invalid("missing-templates")
    templates_text = str(missing_templates)
    assert re.search(
        r"missing_templates: ERROR: \[maatlog\.theme\.template-missing\]",
        templates_text,
    )
    assert "field=template" in templates_text
    assert "core_api=1.0" in templates_text
    assert "theme_api=1.0" in templates_text


@pytest.mark.parametrize("builder", ["text", "latex"])
def test_a12_non_html_builders(site: AcceptanceSite, builder: str) -> None:
    """A12: text/latex build posts and roles without requiring HTML feeds/CSS."""
    result = site.build(builder, theme="alabaster", warningiserror=True)
    assert result.succeeded
    assert result.relative_files_with_suffix(".xml") == frozenset()
    # Post body is processed.
    if builder == "text":
        body = result.text("posts/rst-post.txt")
        assert "Body shared with the MyST twin" in body
        index_text = result.text("index.txt")
        assert "rst-post" in index_text or "reStructuredText" in index_text
    else:
        # LaTeX source exists; no Atom artifacts; body text is present in .tex.
        tex_files = [name for name in result.relative_files if name.endswith(".tex")]
        assert tex_files
        tex_blob = "\n".join(result.text(name) for name in tex_files)
        assert "Body shared with the MyST twin" in tex_blob
        assert "reStructuredText post" in tex_blob or "rst-post" in tex_blob
