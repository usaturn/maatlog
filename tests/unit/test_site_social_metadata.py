"""Unit tests for the site / archive social metadata projector (issue #211)."""

from __future__ import annotations

import json
from typing import cast

from maatlog.social_metadata import SocialMetadataView
from maatlog.social_metadata.site import project_site_metadata
from maatlog.views import ArchiveView, MaatlogTemplateContext, SiteView

BLOG_TOP_URL = "https://example.test/"


def _site(title: str = "Example Blog", tagline: str | None = "Notes on Sphinx") -> SiteView:
    return SiteView(title=title, tagline=tagline, archive_url="blog.html")


def _archive(*, is_home: bool, label: str = "Posts", page_number: int = 1) -> ArchiveView:
    return ArchiveView(
        kind="all",
        id=None,
        label=label,
        docname="blog",
        page_number=page_number,
        total_posts=3,
        is_home=is_home,
    )


def _context(
    *,
    site: SiteView | None = None,
    archive: ArchiveView | None = None,
) -> MaatlogTemplateContext:
    return MaatlogTemplateContext(
        page_kind="home",
        site=site if site is not None else _site(),
        archive=archive if archive is not None else _archive(is_home=True),
    )


def _open_graph(view: SocialMetadataView) -> list[tuple[str, str]]:
    return [(item.property, item.content) for item in view.open_graph]


def _twitter(view: SocialMetadataView) -> list[tuple[str, str]]:
    return [(item.name, item.content) for item in view.twitter]


def test_blog_top_projects_open_graph_and_twitter_in_order() -> None:
    view = project_site_metadata(_context(), page_url=BLOG_TOP_URL)

    assert _open_graph(view) == [
        ("og:type", "website"),
        ("og:title", "Example Blog"),
        ("og:description", "Notes on Sphinx"),
        ("og:url", BLOG_TOP_URL),
    ]
    assert _twitter(view) == [
        ("twitter:card", "summary"),
        ("twitter:title", "Example Blog"),
        ("twitter:description", "Notes on Sphinx"),
    ]


def test_blog_top_omits_site_name() -> None:
    # og:title and WebSite.name already carry the site title on the blog top.
    view = project_site_metadata(_context(), page_url=BLOG_TOP_URL)
    assert "og:site_name" not in [item.property for item in view.open_graph]


def test_blog_top_without_page_url_omits_og_url() -> None:
    view = project_site_metadata(_context(), page_url=None)
    assert [item.property for item in view.open_graph] == ["og:type", "og:title", "og:description"]


def test_blog_top_with_blank_tagline_omits_description() -> None:
    view = project_site_metadata(_context(site=_site(tagline="   ")), page_url=BLOG_TOP_URL)
    assert [item.property for item in view.open_graph] == ["og:type", "og:title", "og:url"]
    assert [item.name for item in view.twitter] == ["twitter:card", "twitter:title"]


def test_blog_top_without_site_title_falls_back_to_archive_label() -> None:
    view = project_site_metadata(_context(site=_site(title="  ")), page_url=BLOG_TOP_URL)
    assert ("og:title", "Posts") in _open_graph(view)
    assert ("twitter:title", "Posts") in _twitter(view)


def test_blog_top_without_any_title_emits_nothing() -> None:
    view = project_site_metadata(
        _context(site=_site(title=""), archive=_archive(is_home=True, label="")),
        page_url=BLOG_TOP_URL,
    )
    assert view == SocialMetadataView()


def test_missing_archive_emits_nothing() -> None:
    context = MaatlogTemplateContext(page_kind="home", site=_site(), archive=None)
    assert project_site_metadata(context, page_url=BLOG_TOP_URL) == SocialMetadataView()


def _json_ld(view: SocialMetadataView) -> dict[str, object]:
    assert view.json_ld is not None
    parsed = json.loads(view.json_ld)
    assert isinstance(parsed, dict)
    return cast("dict[str, object]", parsed)


def test_blog_top_emits_website_json_ld_with_fixed_key_order() -> None:
    view = project_site_metadata(_context(), page_url=BLOG_TOP_URL)
    payload = _json_ld(view)

    assert list(payload) == ["@context", "@type", "name", "url", "description"]
    assert payload == {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "Example Blog",
        "url": BLOG_TOP_URL,
        "description": "Notes on Sphinx",
    }


def test_website_json_ld_omits_absent_url_and_description() -> None:
    view = project_site_metadata(_context(site=_site(tagline=None)), page_url=None)
    assert _json_ld(view) == {"@context": "https://schema.org", "@type": "WebSite", "name": "Example Blog"}


def test_website_json_ld_is_absent_without_site_title() -> None:
    # schema.org requires WebSite.name, and the archive label is the page's title,
    # not the site's name, so no JSON-LD is emitted at all.
    view = project_site_metadata(_context(site=_site(title="   ")), page_url=BLOG_TOP_URL)
    assert view.json_ld is None
    assert ("og:title", "Posts") in _open_graph(view)


def test_website_json_ld_escapes_script_unsafe_values() -> None:
    hostile = 'Blog </script><script>alert("x")</script> & <b>    日本語 "quoted" \\ back'
    view = project_site_metadata(
        _context(site=_site(title=hostile, tagline=hostile)),
        page_url=BLOG_TOP_URL,
    )
    assert view.json_ld is not None
    assert "</script>" not in view.json_ld
    for character in ("<", ">", "&", " ", " "):
        assert character not in view.json_ld
    payload = _json_ld(view)
    assert payload["name"] == hostile
    assert payload["description"] == hostile


TAG_ARCHIVE_URL = "https://example.test/blog/tag/sphinx.html"


def _tag_archive(*, label: str = "sphinx", page_number: int = 1) -> ArchiveView:
    return ArchiveView(
        kind="tag",
        id="sphinx",
        label=label,
        docname="blog/tag/sphinx",
        page_number=page_number,
        total_posts=12,
        is_home=False,
    )


def _archive_context(
    *,
    site: SiteView | None = None,
    archive: ArchiveView | None = None,
) -> MaatlogTemplateContext:
    return MaatlogTemplateContext(
        page_kind="archive",
        site=site if site is not None else _site(),
        archive=archive if archive is not None else _tag_archive(),
    )


def test_archive_projects_label_site_name_and_url() -> None:
    view = project_site_metadata(_archive_context(), page_url=TAG_ARCHIVE_URL)

    assert _open_graph(view) == [
        ("og:type", "website"),
        ("og:title", "sphinx"),
        ("og:site_name", "Example Blog"),
        ("og:url", TAG_ARCHIVE_URL),
    ]
    assert _twitter(view) == [("twitter:card", "summary"), ("twitter:title", "sphinx")]


def test_archive_never_emits_json_ld() -> None:
    # CollectionPage / ItemList are out of scope for the first implementation (#206).
    assert project_site_metadata(_archive_context(), page_url=TAG_ARCHIVE_URL).json_ld is None


def test_archive_omits_description_even_with_tagline() -> None:
    view = project_site_metadata(_archive_context(site=_site(tagline="Notes")), page_url=TAG_ARCHIVE_URL)
    assert "og:description" not in [item.property for item in view.open_graph]
    assert "twitter:description" not in [item.name for item in view.twitter]


def test_archive_without_site_title_omits_site_name() -> None:
    view = project_site_metadata(_archive_context(site=_site(title=" ")), page_url=TAG_ARCHIVE_URL)
    assert [item.property for item in view.open_graph] == ["og:type", "og:title", "og:url"]


def test_archive_without_page_url_omits_og_url() -> None:
    view = project_site_metadata(_archive_context(), page_url=None)
    assert [item.property for item in view.open_graph] == ["og:type", "og:title", "og:site_name"]


def test_archive_without_label_emits_nothing() -> None:
    # Spec §4.4: the archive's only title is the label. Site title and page_url
    # are not enough to emit a partial card without og:type / og:title.
    view = project_site_metadata(_archive_context(archive=_tag_archive(label="  ")), page_url=TAG_ARCHIVE_URL)
    assert view == SocialMetadataView()
    assert view.open_graph == ()
    assert view.twitter == ()
    assert view.json_ld is None


def test_archive_pagination_keeps_label_and_omits_page_number() -> None:
    view = project_site_metadata(
        _archive_context(archive=_tag_archive(page_number=2)),
        page_url="https://example.test/blog/tag/sphinx/page/2.html",
    )
    assert ("og:title", "sphinx") in _open_graph(view)
    assert view.json_ld is None


def test_archive_all_axis_page_two_is_not_blog_top() -> None:
    view = project_site_metadata(
        _archive_context(archive=_archive(is_home=False, page_number=2)),
        page_url="https://example.test/blog/page/2.html",
    )
    assert ("og:title", "Posts") in _open_graph(view)
    assert ("og:site_name", "Example Blog") in _open_graph(view)
    assert view.json_ld is None


def test_no_images_are_projected() -> None:
    for view in (
        project_site_metadata(_context(), page_url=BLOG_TOP_URL),
        project_site_metadata(_archive_context(), page_url=TAG_ARCHIVE_URL),
    ):
        assert [item for item in view.open_graph if item.property.startswith("og:image")] == []
        assert [item for item in view.twitter if item.name.startswith("twitter:image")] == []
        assert [item.content for item in view.twitter if item.name == "twitter:card"] == ["summary"]
