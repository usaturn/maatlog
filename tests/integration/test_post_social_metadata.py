"""Integration coverage for post social metadata in the rendered HTML (issue #209)."""

from __future__ import annotations

import re
from typing import cast

import pytest
from conftest import HtmlPage, ProjectFactory
from social_metadata import json_ld_objects, open_graph_values, twitter_values

POST_FILES: dict[str, str | bytes] = {
    "index.rst": "Home\n====\n",
    "posts/internal.rst": (
        ":maatlog-post: true\n:maatlog-slug: internal\n:maatlog-published-at: 2026-09-01T12:00:00Z\n"
        ":maatlog-excerpt: An internal excerpt.\n:maatlog-tags: sphinx, python\n"
        ":maatlog-categories: engineering\n:maatlog-authors: alice, bob\n\n"
        "Internal Post\n=============\n\nBody.\n"
    ),
    "posts/external.rst": (
        ":maatlog-post: true\n:maatlog-slug: external\n:maatlog-published-at: 2026-09-02T12:00:00Z\n"
        ":maatlog-excerpt: An external excerpt.\n"
        ":maatlog-external-url: https://elsewhere.test/articles/hello\n\n"
        "External Post\n=============\n"
    ),
    "authors/alice.md": "# Alice\n",
}

POST_CONFIG = {
    "html_baseurl": "https://example.test/docs/",
    "maatlog_home_docname": "index",
    "maatlog_authors": {"alice": "Alice Anderson", "bob": "Bob Brown"},
    "maatlog_author_profiles": {"alice": {"about_docname": "authors/alice"}},
    "maatlog_tags": {"sphinx": "Sphinx", "python": "Python"},
    "maatlog_categories": {"engineering": "Engineering"},
}

#: An explicit canonical including query and fragment: ``maatlog-canonical-url`` preserves
#: the accepted URL byte-for-byte, so canonical/OG/JSON-LD assertions keep the fragment.
CANONICAL_URL = "https://example.test/canonical.html?utm=1#summary"

#: An author display name is config-supplied (``maatlog_authors``), never RST-parsed, so a
#: U+2028/U+2029 can reach ``author[].name`` in the JSON-LD and must be script-escaped there.
#: The separators are embedded mid-name because :func:`~.post._text` strips edge whitespace.
AUTHOR_SEPARATORS = "Bo\u2028b B\u2029rown"

#: Image-bearing posts on top of the shared ``POST_FILES`` tree.
IMAGE_FILES: dict[str, str | bytes] = {
    **POST_FILES,
    "posts/with-image.rst": (
        ":maatlog-post: true\n:maatlog-slug: with-image\n:maatlog-published-at: 2026-09-03T12:00:00Z\n"
        ":maatlog-excerpt: An image excerpt.\n"
        ":maatlog-image: images/cover.png\n\n"
        "Image Post\n==========\n\n"
        ".. maatlog:maattop:: images/hero.png\n"
        "   :alt: A beautiful landscape\n\nBody.\n"
    ),
    "posts/maattop.rst": (
        ":maatlog-post: true\n:maatlog-slug: maattop\n:maatlog-published-at: 2026-09-04T12:00:00Z\n"
        ":maatlog-excerpt: A maattop excerpt.\n\n"
        "Maattop Post\n============\n\n"
        ".. maatlog:maattop:: images/hero.png\n"
        "   :alt: A beautiful landscape\n\nBody.\n"
    ),
    "posts/images/cover.png": b"png-bytes",
    "posts/images/hero.png": b"png-bytes",
}

#: Values that must stay inside the JSON-LD ``<script>`` rather than breaking out of it.
#: U+2028/U+2029 escaping is covered at the unit level (test_json_ld_serialization);
#: docutils normalises a literal U+2028 in RST headings and field bodies to a line break,
#: so it cannot be threaded through an RST source and is left out here.
HOSTILE_TITLE = "</script><script>alert(x)</script> & <>"
HOSTILE_EXCERPT = "an <excerpt> with </script> & <tag> values"


@pytest.mark.parametrize(("builder", "suffix"), [("html", ".html"), ("dirhtml", "/index.html")])
def test_internal_post_head_carries_one_of_each_property(
    make_project: ProjectFactory, builder: str, suffix: str
) -> None:
    result = make_project(
        files=POST_FILES, config=POST_CONFIG, builder=builder, source_date_epoch="1789171200"
    ).build()
    page = result.html(f"posts/internal{suffix}")

    assert open_graph_values(page, "og:type") == ["article"]
    assert open_graph_values(page, "og:title") == ["Internal Post"]
    assert open_graph_values(page, "og:description") == ["An internal excerpt."]
    assert open_graph_values(page, "article:tag") == ["Sphinx", "Python"]
    assert open_graph_values(page, "article:section") == ["Engineering"]
    assert open_graph_values(page, "article:published_time") == ["2026-09-01T12:00:00+00:00"]
    assert twitter_values(page, "twitter:card") == ["summary"]
    assert twitter_values(page, "twitter:title") == ["Internal Post"]
    url = open_graph_values(page, "og:url")
    assert url == ["https://example.test/docs/posts/internal" + (".html" if builder == "html" else "/")]

    documents = json_ld_objects(page)
    assert len(documents) == 1
    document = documents[0]
    assert isinstance(document, dict)
    assert document["@type"] == "BlogPosting"
    assert document["headline"] == "Internal Post"
    assert document["url"] == url[0]
    assert document["keywords"] == ["Sphinx", "Python"]
    authors = cast(list[dict[str, object]], document["author"])
    assert [person["name"] for person in authors] == ["Alice Anderson", "Bob Brown"]
    alice_profile = "https://example.test/docs/blog/author/alice" + (".html" if builder == "html" else "/")
    assert authors[0]["url"] == alice_profile


def test_explicit_canonical_drives_the_shared_url(make_project: ProjectFactory) -> None:
    files = dict(POST_FILES)
    source = files["posts/internal.rst"]
    assert isinstance(source, str)
    files["posts/internal.rst"] = source.replace(
        ":maatlog-slug: internal\n",
        f":maatlog-slug: internal\n:maatlog-canonical-url: {CANONICAL_URL}\n",
    )
    result = make_project(files=files, config=POST_CONFIG, source_date_epoch="1789171200").build()
    page = result.html("posts/internal.html")

    assert open_graph_values(page, "og:url") == [CANONICAL_URL]
    assert page.select('link[rel="canonical"]') == [{"rel": "canonical", "href": CANONICAL_URL}]
    documents = json_ld_objects(page)
    assert len(documents) == 1
    assert isinstance(documents[0], dict)
    assert documents[0]["url"] == CANONICAL_URL


def test_external_post_is_not_presented_as_a_blog_posting(make_project: ProjectFactory) -> None:
    result = make_project(files=POST_FILES, config=POST_CONFIG, source_date_epoch="1789171200").build()
    page = result.html("posts/external.html")

    assert open_graph_values(page, "og:type") == ["website"]
    assert open_graph_values(page, "og:url") == ["https://elsewhere.test/articles/hello"]
    assert open_graph_values(page, "article:published_time") == []
    assert json_ld_objects(page) == []
    assert page.select('link[rel="canonical"]') == [
        {"rel": "canonical", "href": "https://example.test/docs/posts/external.html"}
    ]
    # Being external must not strip the local feed discovery links: the post still indexes
    # the blog and its publication month (it has no tags/categories of its own to thread).
    atom = [link["href"] for link in page.select('link[type="application/atom+xml"]')]
    assert atom == [
        "https://example.test/docs/blog/atom.xml",
        "https://example.test/docs/blog/month/2026-09/atom.xml",
    ]


def test_missing_baseurl_degrades_without_breaking_the_build(make_project: ProjectFactory) -> None:
    result = make_project(
        files=IMAGE_FILES,
        config={**POST_CONFIG, "html_baseurl": "", "maatlog_generate_feeds": False},
        source_date_epoch="1789171200",
    ).build()
    page = result.html("posts/internal.html")

    assert open_graph_values(page, "og:type") == ["article"]
    assert open_graph_values(page, "og:title") == ["Internal Post"]
    assert open_graph_values(page, "og:url") == []
    assert "html_baseurl" not in result.warnings
    documents = json_ld_objects(page)
    assert len(documents) == 1
    assert isinstance(documents[0], dict)
    assert "url" not in documents[0]

    # ``with-image`` really declares a representative image, yet ``og:image`` must still
    # be absent: with no page URL the image URI cannot be absolutized, so every image
    # property is dropped instead of emitting a non-crawlable form.
    image_page = result.html("posts/with-image.html")
    assert open_graph_values(image_page, "og:image") == []
    assert open_graph_values(image_page, "og:image:alt") == []
    assert twitter_values(image_page, "twitter:image") == []
    assert twitter_values(image_page, "twitter:card") == ["summary"]


def test_incremental_and_parallel_builds_do_not_duplicate_metadata(make_project: ProjectFactory) -> None:
    project = make_project(files=POST_FILES, config=POST_CONFIG, source_date_epoch="1789171200")
    first = project.build().html("posts/internal.html")
    source = POST_FILES["posts/internal.rst"]
    assert isinstance(source, str)
    project.write("posts/internal.rst", source.replace("Internal Post\n=============", "Renamed\n======="))
    second = project.build(reuse_environment=True).html("posts/internal.html")

    assert open_graph_values(second, "og:title") == ["Renamed"]
    assert len(json_ld_objects(second)) == 1

    parallel = (
        make_project(files=POST_FILES, config=POST_CONFIG, source_date_epoch="1789171200")
        .build(parallel=4)
        .html("posts/internal.html")
    )
    # §9.2 requires a -j parallel build to agree with a single build on the metadata
    # values, not merely that the property exists. ``og:type`` is a constant literal and
    # cannot distinguish a duplicated or stale row, so compare a real value set against
    # the single ``first`` build (like with like — the incremental ``second`` page has
    # been renamed, so it is not a valid baseline for a title equality check).
    for prop in (
        "og:title",
        "og:url",
        "og:description",
        "article:tag",
        "article:section",
        "article:published_time",
    ):
        assert open_graph_values(parallel, prop) == open_graph_values(first, prop)
    assert json_ld_objects(parallel) == json_ld_objects(first)
    assert len(json_ld_objects(parallel)) == 1


@pytest.mark.parametrize(("builder", "suffix"), [("html", ".html"), ("dirhtml", "/index.html")])
def test_representative_image_wins_over_maattop_and_both_are_absolutized(
    make_project: ProjectFactory, builder: str, suffix: str
) -> None:
    result = make_project(
        files=IMAGE_FILES, config=POST_CONFIG, builder=builder, source_date_epoch="1789171200"
    ).build()

    def asserts_image(page: HtmlPage, *, basename: str, alt: list[str]) -> None:
        og_image = open_graph_values(page, "og:image")
        assert og_image == [f"https://example.test/docs/_images/{basename}"]
        assert open_graph_values(page, "og:image:alt") == alt
        assert twitter_values(page, "twitter:card") == ["summary_large_image"]

    # A post carrying BOTH a representative image and a maattop hero: the representative
    # image must win, and (having no alt field) must emit no og:image:alt.
    asserts_image(result.html(f"posts/with-image{suffix}"), basename="cover.png", alt=[])
    # With only a maattop hero, the hero is shared absolutely and reuses its :alt:.
    asserts_image(result.html(f"posts/maattop{suffix}"), basename="hero.png", alt=["A beautiful landscape"])


def test_hostile_values_cannot_escape_the_json_ld_script(make_project: ProjectFactory) -> None:
    files = dict(POST_FILES)
    files["posts/internal.rst"] = (
        ":maatlog-post: true\n:maatlog-slug: internal\n:maatlog-published-at: 2026-09-01T12:00:00Z\n"
        f":maatlog-excerpt: {HOSTILE_EXCERPT}\n:maatlog-tags: sphinx, python\n"
        ":maatlog-categories: engineering\n:maatlog-authors: alice, bob\n\n"
        f"{HOSTILE_TITLE}\n"
        f"{'=' * len(HOSTILE_TITLE)}\n\nBody.\n"
    )
    result = make_project(files=files, config=POST_CONFIG, source_date_epoch="1789171200").build()
    page = result.html("posts/internal.html")

    documents = json_ld_objects(page)
    assert len(documents) == 1
    assert isinstance(documents[0], dict)
    assert documents[0]["headline"] == HOSTILE_TITLE
    assert documents[0]["description"] == HOSTILE_EXCERPT


def test_unicode_separator_in_author_name_stays_escaped_in_json_ld(
    make_project: ProjectFactory,
) -> None:
    """A config-supplied author display name reaches the JSON-LD head unmodified.

    Unlike an RST title/excerpt, ``maatlog_authors`` values are never RST-parsed, so a
    U+2028/U+2029 in a display name flows straight into ``author[].name`` and must be
    script-escaped there. (The visible byline renders the raw name elsewhere on the page,
    so the escape is asserted scoped to the JSON-LD script body.)
    """
    config = {**POST_CONFIG, "maatlog_authors": {"alice": "Alice Anderson", "bob": AUTHOR_SEPARATORS}}
    result = make_project(files=POST_FILES, config=config, source_date_epoch="1789171200").build()
    page = result.html("posts/internal.html")

    documents = json_ld_objects(page)
    assert len(documents) == 1
    assert isinstance(documents[0], dict)
    authors = cast(list[dict[str, object]], documents[0]["author"])
    assert [person["name"] for person in authors][1] == AUTHOR_SEPARATORS

    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', page.text, re.DOTALL)
    assert block is not None
    body = block.group(1)
    assert " " not in body
    assert " " not in body
    assert "\\u2028" in body
    assert "\\u2029" in body
