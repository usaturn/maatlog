"""One-build social metadata matrix over every page kind (issue #212).

The fixed ``social_metadata_project`` tree publishes one of every page kind in a
single Sphinx build: a configured Home, an internal post with an explicit
canonical, an external post, an author profile, paginated archives on every
axis, and one ordinary page. Both full-HTML builders must agree on the
crawler-facing values; only the page-URL suffix differs.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import pytest
from acceptance.site import AcceptanceBuildResult, AcceptanceSite
from social_metadata import (
    HtmlPage,
    MetaCollector,
    assert_crawler_urls_are_absolute,
    assert_no_crawler_urls,
    assert_no_duplicate_social_metadata,
    assert_no_social_metadata,
    json_ld_bodies,
    json_ld_objects,
    open_graph_values,
    twitter_values,
)

SOCIAL_METADATA_PROJECT_ROOT = Path(__file__).resolve().parent / "social_metadata_project"

BASEURL = "https://example.test/docs/"
SITE_TITLE = "Integration Blog"
INTERNAL_CANONICAL = "https://canonical.example/articles/internal?utm=maatlog#summary"
EXTERNAL_URL = "https://publisher.example/articles/42?utm=maatlog#source"
INTERNAL_EXCERPT = "An internal excerpt for the integration matrix."
EXTERNAL_EXCERPT = "An external excerpt for the integration matrix."
INTERNAL_PUBLISHED = "2026-08-10T12:00:00+00:00"
ALICE_NAME = "Alice Anderson"
ALICE_BIO = "Python developer."
ALICE_SAME_AS = "https://alice.example/about?from=maatlog#profile"
AVATAR_URL = f"{BASEURL}_images/alice.png"
REPRESENTATIVE_URL = f"{BASEURL}_images/representative.png"

BLOG_FEED = f"{BASEURL}blog/atom.xml"
TAG_SPHINX_FEED = f"{BASEURL}blog/tag/sphinx/atom.xml"
TAG_PYTHON_FEED = f"{BASEURL}blog/tag/python/atom.xml"
CATEGORY_ENGINEERING_FEED = f"{BASEURL}blog/category/engineering/atom.xml"
CATEGORY_NOTES_FEED = f"{BASEURL}blog/category/notes/atom.xml"
AUTHOR_ALICE_FEED = f"{BASEURL}blog/author/alice/atom.xml"
AUTHOR_BOB_FEED = f"{BASEURL}blog/author/bob/atom.xml"
MONTH_FEED = f"{BASEURL}blog/month/2026-08/atom.xml"

#: Hostile payload for the script-escape regression: the inline value threads
#: through document titles/excerpts, while the full text (newline plus real
#: U+2028/U+2029 code points) is config-supplied, never RST-parsed.
HOSTILE_INLINE = '" apostrophe \' backslash \\ < > </script><script data-escaped="no">bad()</script> & 日本語'
HOSTILE_TEXT = f"{HOSTILE_INLINE}\nline paragraph end"
SCRIPT_UNSAFE = ("<", ">", "&", " ", " ")


@pytest.fixture
def social_metadata_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AcceptanceSite:
    return AcceptanceSite(tmp_path / "social-metadata", monkeypatch, project_root=SOCIAL_METADATA_PROJECT_ROOT)


def _paths(builder: str) -> dict[str, str]:
    suffix = "index.html" if builder == "dirhtml" else None

    def page(docname: str) -> str:
        return f"{docname}/{suffix}" if suffix else f"{docname}.html"

    return {
        "home": "index.html",
        "internal": page("posts/internal"),
        "external": page("posts/external"),
        "profile": page("blog/author/alice"),
        "profile_page_2": page("blog/author/alice/page/2"),
        "all": page("blog"),
        "tag": page("blog/tag/sphinx"),
        "category": page("blog/category/engineering"),
        "author_archive": page("blog/author/bob"),
        "month": page("blog/month/2026-08"),
        "normal": page("normal"),
    }


def _page_url(builder: str, docname: str) -> str:
    if builder == "dirhtml":
        return f"{BASEURL}{docname}/"
    return f"{BASEURL}{docname}.html"


def _home_url(builder: str) -> str:
    return BASEURL if builder == "dirhtml" else f"{BASEURL}index.html"


def _website_objects(page: HtmlPage) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for payload in json_ld_objects(page):
        if isinstance(payload, dict):
            obj = cast("dict[str, object]", payload)
            if obj.get("@type") == "WebSite":
                found.append(obj)
    return found


def _page(result: AcceptanceBuildResult, relative: str) -> HtmlPage:
    # ``AcceptanceBuildResult.html()`` returns the same object, but the ``HtmlPage``
    # stub in ``acceptance.site`` (kept for the type checker, see that module) is
    # nominally distinct from the shared ``conftest.HtmlPage`` the ``social_metadata``
    # helpers are typed against. Building from the raw text keeps one nominal type.
    return HtmlPage(result.text(relative))


def _website_carriers(result: AcceptanceBuildResult) -> list[str]:
    carriers: list[str] = []
    for relative in sorted(result.relative_files_with_suffix(".html")):
        if _website_objects(_page(result, relative)):
            carriers.append(relative)
    return carriers


def _assert_no_empty_json_ld_values(value: object) -> None:
    """JSON-LD must parse and carry no empty string, collection, or null.

    Without ``html_baseurl`` every URL-bearing key is dropped instead of emitted
    empty, so a surviving ``""``/``[]``/``{}``/``None`` means a projector leaked a
    placeholder where it should have omitted the key.
    """
    assert value is not None
    assert value != ""
    assert value != []
    assert value != {}
    if isinstance(value, dict):
        for item in cast("dict[str, object]", value).values():
            _assert_no_empty_json_ld_values(item)
    elif isinstance(value, list):
        for item in cast("list[object]", value):
            _assert_no_empty_json_ld_values(item)


def _canonical_href(page: HtmlPage) -> list[str]:
    return [link["href"] for link in page.select('link[rel="canonical"]')]


def _atom_hrefs(page: HtmlPage) -> list[str]:
    return [link["href"] for link in page.select('link[type="application/atom+xml"]')]


def _meta_items(page: HtmlPage) -> MetaCollector:
    collector = MetaCollector()
    collector.feed(page.text)
    collector.close()
    return collector


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_internal_post_projects_article(social_metadata_site: AcceptanceSite, builder: str) -> None:
    result = social_metadata_site.build(builder)
    page = _page(result, _paths(builder)["internal"])

    assert open_graph_values(page, "og:type") == ["article"]
    assert open_graph_values(page, "og:title") == ["Internal Post"]
    assert open_graph_values(page, "og:site_name") == [SITE_TITLE]
    assert open_graph_values(page, "og:url") == [INTERNAL_CANONICAL]
    assert open_graph_values(page, "og:description") == [INTERNAL_EXCERPT]
    # The representative image wins over the maattop hero, and — having no alt
    # field of its own — emits no image alt even though the hero declares one.
    assert open_graph_values(page, "og:image") == [REPRESENTATIVE_URL]
    assert open_graph_values(page, "og:image:alt") == []
    assert open_graph_values(page, "article:published_time") == [INTERNAL_PUBLISHED]
    assert open_graph_values(page, "article:tag") == ["Sphinx", "Python"]
    assert open_graph_values(page, "article:section") == ["Engineering", "Notes"]
    assert twitter_values(page, "twitter:card") == ["summary_large_image"]
    assert twitter_values(page, "twitter:title") == ["Internal Post"]
    assert twitter_values(page, "twitter:description") == [INTERNAL_EXCERPT]
    assert twitter_values(page, "twitter:image") == [REPRESENTATIVE_URL]
    assert twitter_values(page, "twitter:image:alt") == []

    # The explicit canonical owns every crawler URL the page publishes.
    assert _canonical_href(page) == [INTERNAL_CANONICAL]

    bodies = json_ld_bodies(page)
    assert len(bodies) == 1
    documents = json_ld_objects(page)
    assert len(documents) == 1
    profile_url = _page_url(builder, "blog/author/alice")
    bob_url = _page_url(builder, "blog/author/bob")
    assert documents[0] == {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": "Internal Post",
        "description": INTERNAL_EXCERPT,
        "datePublished": INTERNAL_PUBLISHED,
        "url": INTERNAL_CANONICAL,
        "image": [REPRESENTATIVE_URL],
        # Authors stay in the post's own declaration order.
        "author": [
            {"@type": "Person", "name": ALICE_NAME, "url": profile_url},
            {"@type": "Person", "name": "Bob Builder", "url": bob_url},
        ],
        "keywords": ["Sphinx", "Python"],
        "articleSection": ["Engineering", "Notes"],
    }

    # Ordered lifecycle values: one row per emitted property, in document order.
    collected = _meta_items(page)
    assert collected.open_graph_items == [
        ("og:type", "article"),
        ("og:title", "Internal Post"),
        ("og:site_name", SITE_TITLE),
        ("og:url", INTERNAL_CANONICAL),
        ("og:description", INTERNAL_EXCERPT),
        ("og:image", REPRESENTATIVE_URL),
        ("article:published_time", INTERNAL_PUBLISHED),
        ("article:tag", "Sphinx"),
        ("article:tag", "Python"),
        ("article:section", "Engineering"),
        ("article:section", "Notes"),
    ]
    assert collected.twitter_items == [
        ("twitter:card", "summary_large_image"),
        ("twitter:title", "Internal Post"),
        ("twitter:description", INTERNAL_EXCERPT),
        ("twitter:image", REPRESENTATIVE_URL),
    ]

    assert _atom_hrefs(page) == [
        BLOG_FEED,
        TAG_SPHINX_FEED,
        TAG_PYTHON_FEED,
        CATEGORY_ENGINEERING_FEED,
        CATEGORY_NOTES_FEED,
        AUTHOR_ALICE_FEED,
        AUTHOR_BOB_FEED,
        MONTH_FEED,
    ]


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_external_post_projects_publisher_url(social_metadata_site: AcceptanceSite, builder: str) -> None:
    result = social_metadata_site.build(builder)
    paths = _paths(builder)
    page = _page(result, paths["external"])
    local_url = _page_url(builder, "posts/external")

    assert open_graph_values(page, "og:type") == ["website"]
    assert open_graph_values(page, "og:title") == ["External Post"]
    assert open_graph_values(page, "og:site_name") == [SITE_TITLE]
    # The shared URL is the publisher URL, query and fragment included.
    assert open_graph_values(page, "og:url") == [EXTERNAL_URL]
    assert open_graph_values(page, "og:description") == [EXTERNAL_EXCERPT]
    assert open_graph_values(page, "og:image") == []
    assert twitter_values(page, "twitter:card") == ["summary"]
    assert twitter_values(page, "twitter:title") == ["External Post"]
    assert twitter_values(page, "twitter:description") == [EXTERNAL_EXCERPT]
    assert twitter_values(page, "twitter:image") == []
    # Never presented as MaatLog's own article.
    assert open_graph_values(page, "article:published_time") == []
    assert open_graph_values(page, "article:tag") == []
    assert open_graph_values(page, "article:section") == []
    assert json_ld_objects(page) == []
    # The local canonical still names the generated MaatLog page.
    assert _canonical_href(page) == [local_url]
    # The post indexes the blog and its month, nothing else.
    assert _atom_hrefs(page) == [BLOG_FEED, MONTH_FEED]


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_profile_page_projects_person(social_metadata_site: AcceptanceSite, builder: str) -> None:
    result = social_metadata_site.build(builder)
    page = _page(result, _paths(builder)["profile"])
    profile_url = _page_url(builder, "blog/author/alice")

    assert open_graph_values(page, "og:type") == ["profile"]
    assert open_graph_values(page, "og:title") == [ALICE_NAME]
    assert open_graph_values(page, "og:site_name") == [SITE_TITLE]
    assert open_graph_values(page, "og:url") == [profile_url]
    assert open_graph_values(page, "og:description") == [ALICE_BIO]
    assert open_graph_values(page, "og:image") == [AVATAR_URL]
    assert twitter_values(page, "twitter:card") == ["summary"]
    assert twitter_values(page, "twitter:title") == [ALICE_NAME]
    assert twitter_values(page, "twitter:description") == [ALICE_BIO]
    assert twitter_values(page, "twitter:image") == [AVATAR_URL]

    documents = json_ld_objects(page)
    assert len(documents) == 1
    assert documents[0] == {
        "@context": "https://schema.org",
        "@type": "ProfilePage",
        "mainEntity": {
            "@type": "Person",
            "name": ALICE_NAME,
            "description": ALICE_BIO,
            "image": AVATAR_URL,
            "url": profile_url,
            # The website link survives with its query and fragment.
            "sameAs": [ALICE_SAME_AS],
        },
    }

    collected = _meta_items(page)
    assert collected.open_graph_items == [
        ("og:type", "profile"),
        ("og:title", ALICE_NAME),
        ("og:site_name", SITE_TITLE),
        ("og:url", profile_url),
        ("og:description", ALICE_BIO),
        ("og:image", AVATAR_URL),
    ]
    assert collected.twitter_items == [
        ("twitter:card", "summary"),
        ("twitter:title", ALICE_NAME),
        ("twitter:description", ALICE_BIO),
        ("twitter:image", AVATAR_URL),
    ]

    assert _canonical_href(page) == [profile_url]
    assert _atom_hrefs(page) == [BLOG_FEED, AUTHOR_ALICE_FEED]


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_archives_carry_website_without_json_ld(social_metadata_site: AcceptanceSite, builder: str) -> None:
    result = social_metadata_site.build(builder)
    paths = _paths(builder)
    cases: tuple[tuple[str, str, list[str]], ...] = (
        # (path key, expected title, expected discovery hrefs)
        ("profile_page_2", ALICE_NAME, [BLOG_FEED, AUTHOR_ALICE_FEED]),
        ("all", "Posts", [BLOG_FEED]),
        ("tag", "Sphinx", [BLOG_FEED, TAG_SPHINX_FEED]),
        ("category", "Engineering", [BLOG_FEED, CATEGORY_ENGINEERING_FEED]),
        ("author_archive", "Bob Builder", [BLOG_FEED, AUTHOR_BOB_FEED]),
        ("month", "2026-08", [BLOG_FEED, MONTH_FEED]),
    )
    docnames = {
        "profile_page_2": "blog/author/alice/page/2",
        "all": "blog",
        "tag": "blog/tag/sphinx",
        "category": "blog/category/engineering",
        "author_archive": "blog/author/bob",
        "month": "blog/month/2026-08",
    }
    for key, title, discovery in cases:
        page = _page(result, paths[key])
        expected_url = _page_url(builder, docnames[key])
        assert open_graph_values(page, "og:type") == ["website"], key
        assert open_graph_values(page, "og:title") == [title], key
        assert open_graph_values(page, "og:site_name") == [SITE_TITLE], key
        assert open_graph_values(page, "og:url") == [expected_url], key
        assert open_graph_values(page, "og:description") == [], key
        assert twitter_values(page, "twitter:card") == ["summary"], key
        assert twitter_values(page, "twitter:title") == [title], key
        assert twitter_values(page, "twitter:description") == [], key
        assert json_ld_objects(page) == [], key
        assert _canonical_href(page) == [expected_url], key
        assert _atom_hrefs(page) == discovery, key


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_configured_home_is_the_only_website_carrier(social_metadata_site: AcceptanceSite, builder: str) -> None:
    result = social_metadata_site.build(builder)
    paths = _paths(builder)
    home_url = _home_url(builder)
    page = _page(result, paths["home"])

    assert open_graph_values(page, "og:type") == ["website"]
    assert open_graph_values(page, "og:title") == [SITE_TITLE]
    # No tagline is configured, so the blog top publishes no description.
    assert open_graph_values(page, "og:description") == []
    assert open_graph_values(page, "og:site_name") == []
    assert open_graph_values(page, "og:url") == [home_url]
    assert twitter_values(page, "twitter:card") == ["summary"]
    assert twitter_values(page, "twitter:title") == [SITE_TITLE]
    assert twitter_values(page, "twitter:description") == []
    assert twitter_values(page, "twitter:image") == []

    websites = _website_objects(page)
    assert len(websites) == 1
    assert websites[0] == {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": SITE_TITLE,
        "url": home_url,
    }

    assert _canonical_href(page) == [home_url]
    assert _atom_hrefs(page) == [BLOG_FEED]

    assert _website_carriers(result) == ["index.html"]


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_normal_page_carries_no_metadata(social_metadata_site: AcceptanceSite, builder: str) -> None:
    result = social_metadata_site.build(builder)
    page = _page(result, _paths(builder)["normal"])

    assert_no_social_metadata(page)
    # Sphinx still publishes its own canonical for the ordinary page.
    assert _canonical_href(page) == [_page_url(builder, "normal")]
    assert _atom_hrefs(page) == []


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_every_page_passes_head_hygiene(social_metadata_site: AcceptanceSite, builder: str) -> None:
    result = social_metadata_site.build(builder)
    relatives = sorted(result.relative_files_with_suffix(".html"))
    # The fixed tree renders the configured Home, four posts, the About page, one
    # ordinary page, and every paginated archive; the matrix must cover them all.
    assert len(relatives) > 15
    for relative in relatives:
        page = _page(result, relative)
        assert_no_duplicate_social_metadata(page)
        assert_crawler_urls_are_absolute(page)
        # Spec §5: the canonical link must not repeat either — exactly one per
        # page, and its href must be an absolute HTTP(S) URL like every other
        # crawler-facing URL.
        canonicals = _canonical_href(page)
        assert len(canonicals) == 1, relative
        parsed = urlsplit(canonicals[0])
        assert parsed.scheme in {"http", "https"} and parsed.netloc, canonicals[0]


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_fallback_home_moves_website_to_archive_root(social_metadata_site: AcceptanceSite, builder: str) -> None:
    result = social_metadata_site.build(builder, config_overrides={"maatlog_home_docname": None})
    paths = _paths(builder)

    expected_carrier = "blog/index.html" if builder == "dirhtml" else "blog.html"
    assert _website_carriers(result) == [expected_carrier]

    # Without a configured Home the root document is an ordinary page again.
    assert_no_social_metadata(_page(result, paths["home"]))


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_hostile_text_cannot_escape_the_script_element(social_metadata_site: AcceptanceSite, builder: str) -> None:
    assert "\u2028" in HOSTILE_TEXT
    assert "\\u2028" not in HOSTILE_TEXT
    # Single-quote the excerpt for the YAML front matter (apostrophes doubled);
    # the heading carries the raw inline value like any other Markdown title.
    hostile_excerpt = HOSTILE_INLINE.replace("'", "''")
    result = social_metadata_site.build(
        builder,
        config_overrides={
            # Sphinx typographic quotes would curl the straight quotes in the
            # Markdown heading, so the document-derived headline could never stay
            # byte-identical to HOSTILE_INLINE. Disable only that substitution:
            # every hostile byte (including </script>) still reaches the head.
            "smartquotes": False,
            "project": HOSTILE_TEXT,
            "maatlog_tagline": HOSTILE_TEXT,
            "maatlog_authors": {"alice": HOSTILE_TEXT, "bob": "Bob Builder"},
            "maatlog_author_profiles": {
                "alice": {
                    "about_docname": "authors/alice",
                    "avatar": "authors/alice.png",
                    "bio_short": HOSTILE_TEXT,
                    "links": [{"type": "website", "url": ALICE_SAME_AS}],
                }
            },
        },
        extra_files={
            "posts/internal.md": (
                "---\n"
                "maatlog-post: true\n"
                "maatlog-slug: internal\n"
                "maatlog-published-at: 2026-08-10T12:00:00Z\n"
                "maatlog-tags: [sphinx, python]\n"
                "maatlog-categories: [engineering, notes]\n"
                "maatlog-authors: [alice, bob]\n"
                f"maatlog-excerpt: '{hostile_excerpt}'\n"
                "maatlog-image: representative.png\n"
                f"maatlog-canonical-url: {INTERNAL_CANONICAL}\n"
                "---\n"
                "\n"
                f"# {HOSTILE_INLINE}\n"
                "\n"
                "Body of the internal post.\n"
                "\n"
                "```{maatlog:maattop} hero.png\n"
                ":alt: Hero alt that must not win\n"
                "```\n"
            )
        },
    )
    paths = _paths(builder)

    home = _page(result, paths["home"])
    internal = _page(result, paths["internal"])
    profile = _page(result, paths["profile"])

    home_payload = cast("dict[str, object]", json_ld_objects(home)[0])
    post_payload = cast("dict[str, object]", json_ld_objects(internal)[0])
    profile_payload = cast("dict[str, object]", json_ld_objects(profile)[0])
    person = cast("dict[str, object]", profile_payload["mainEntity"])

    assert (home_payload["name"], home_payload["description"]) == (HOSTILE_TEXT, HOSTILE_TEXT)
    assert (post_payload["headline"], post_payload["description"]) == (HOSTILE_INLINE, HOSTILE_INLINE)
    assert (person["name"], person["description"]) == (HOSTILE_TEXT, HOSTILE_TEXT)
    for page, expected_title in ((home, HOSTILE_TEXT), (internal, HOSTILE_INLINE), (profile, HOSTILE_TEXT)):
        bodies = json_ld_bodies(page)
        assert len(bodies) == 1
        for body in bodies:
            assert all(character not in body for character in SCRIPT_UNSAFE)
            assert "</script>" not in body.lower()
        assert open_graph_values(page, "og:title") == [expected_title]
        assert_no_duplicate_social_metadata(page)
        assert len(page.select('script[type="application/ld+json"]')) == 1
        # Scoped to the head: a serializer breakout would inject the attacker's
        # element here, right after the JSON-LD script. The body keeps its own
        # rendering of the hostile document title (toctree links), which is a
        # separate theme-body boundary this metadata regression must not touch.
        assert page.select('head script[data-escaped="no"]') == []


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_social_metadata_degrades_without_a_baseurl(social_metadata_site: AcceptanceSite, builder: str) -> None:
    result = social_metadata_site.build(
        builder,
        config_overrides={
            "html_baseurl": "",
            "maatlog_generate_feeds": False,
            "maatlog_home_docname": "index",
        },
    )
    paths = _paths(builder)

    # Internal post: every text value survives; local URLs are dropped while the
    # explicit absolute canonical needs no baseurl, so it stays byte-for-byte.
    # assert_no_crawler_urls() would reject that configured URL, so it stays unused
    # here — the exact og:url/canonical equality below pins that nothing else was
    # invented instead.
    internal = _page(result, paths["internal"])
    assert open_graph_values(internal, "og:type") == ["article"]
    assert open_graph_values(internal, "og:title") == ["Internal Post"]
    assert open_graph_values(internal, "og:description") == [INTERNAL_EXCERPT]
    assert open_graph_values(internal, "og:url") == [INTERNAL_CANONICAL]
    assert open_graph_values(internal, "og:image") == []
    assert open_graph_values(internal, "article:published_time") == [INTERNAL_PUBLISHED]
    assert open_graph_values(internal, "article:tag") == ["Sphinx", "Python"]
    assert open_graph_values(internal, "article:section") == ["Engineering", "Notes"]
    assert twitter_values(internal, "twitter:card") == ["summary"]
    assert twitter_values(internal, "twitter:title") == ["Internal Post"]
    assert twitter_values(internal, "twitter:description") == [INTERNAL_EXCERPT]
    assert twitter_values(internal, "twitter:image") == []
    documents = json_ld_objects(internal)
    assert len(documents) == 1
    posting = cast("dict[str, object]", documents[0])
    assert posting["headline"] == "Internal Post"
    assert posting["description"] == INTERNAL_EXCERPT
    assert posting["datePublished"] == INTERNAL_PUBLISHED
    assert posting["url"] == INTERNAL_CANONICAL
    assert "image" not in posting
    authors = cast("list[dict[str, object]]", posting["author"])
    assert [person["name"] for person in authors] == [ALICE_NAME, "Bob Builder"]
    assert all("url" not in person for person in authors)
    _assert_no_empty_json_ld_values(posting)
    assert _canonical_href(internal) == [INTERNAL_CANONICAL]
    assert _atom_hrefs(internal) == []

    # Profile: the absolute website link survives, local URLs are dropped.
    profile = _page(result, paths["profile"])
    assert open_graph_values(profile, "og:type") == ["profile"]
    assert open_graph_values(profile, "og:title") == [ALICE_NAME]
    assert open_graph_values(profile, "og:description") == [ALICE_BIO]
    assert open_graph_values(profile, "og:url") == []
    assert open_graph_values(profile, "og:image") == []
    assert twitter_values(profile, "twitter:card") == ["summary"]
    assert twitter_values(profile, "twitter:title") == [ALICE_NAME]
    assert twitter_values(profile, "twitter:description") == [ALICE_BIO]
    assert twitter_values(profile, "twitter:image") == []
    profile_documents = json_ld_objects(profile)
    assert len(profile_documents) == 1
    profile_document = cast("dict[str, object]", profile_documents[0])
    person = cast("dict[str, object]", profile_document["mainEntity"])
    assert person["name"] == ALICE_NAME
    assert person["description"] == ALICE_BIO
    assert person["sameAs"] == [ALICE_SAME_AS]
    assert "url" not in person
    assert "image" not in person
    _assert_no_empty_json_ld_values(profile_documents[0])
    assert_no_crawler_urls(profile)
    assert _canonical_href(profile) == []
    assert _atom_hrefs(profile) == []

    # Configured Home: the site name survives without its URL.
    home = _page(result, paths["home"])
    assert open_graph_values(home, "og:type") == ["website"]
    assert open_graph_values(home, "og:title") == [SITE_TITLE]
    assert open_graph_values(home, "og:description") == []
    assert open_graph_values(home, "og:url") == []
    assert twitter_values(home, "twitter:card") == ["summary"]
    assert twitter_values(home, "twitter:title") == [SITE_TITLE]
    websites = _website_objects(home)
    assert len(websites) == 1
    assert websites[0]["name"] == SITE_TITLE
    assert "url" not in websites[0]
    _assert_no_empty_json_ld_values(websites[0])
    assert_no_crawler_urls(home)
    assert _canonical_href(home) == []
    assert _atom_hrefs(home) == []

    # Every archive axis keeps its title and drops its URL, discovery, and JSON-LD.
    archive_cases: tuple[tuple[str, str], ...] = (
        ("profile_page_2", ALICE_NAME),
        ("all", "Posts"),
        ("tag", "Sphinx"),
        ("category", "Engineering"),
        ("author_archive", "Bob Builder"),
        ("month", "2026-08"),
    )
    for key, title in archive_cases:
        archive = _page(result, paths[key])
        assert open_graph_values(archive, "og:type") == ["website"], key
        assert open_graph_values(archive, "og:title") == [title], key
        assert open_graph_values(archive, "og:url") == [], key
        assert twitter_values(archive, "twitter:card") == ["summary"], key
        assert twitter_values(archive, "twitter:title") == [title], key
        assert json_ld_objects(archive) == [], key
        assert_no_crawler_urls(archive)
        assert _canonical_href(archive) == [], key
        assert _atom_hrefs(archive) == [], key

    # External post: the absolute publisher URL is not a local URL, so it stays.
    # assert_no_crawler_urls() would reject that shared URL, so it stays unused here.
    external = _page(result, paths["external"])
    local_url = _page_url(builder, "posts/external")
    assert open_graph_values(external, "og:type") == ["website"]
    assert open_graph_values(external, "og:title") == ["External Post"]
    assert open_graph_values(external, "og:url") == [EXTERNAL_URL]
    assert open_graph_values(external, "og:description") == [EXTERNAL_EXCERPT]
    assert open_graph_values(external, "og:image") == []
    assert twitter_values(external, "twitter:card") == ["summary"]
    assert twitter_values(external, "twitter:title") == ["External Post"]
    assert twitter_values(external, "twitter:description") == [EXTERNAL_EXCERPT]
    assert twitter_values(external, "twitter:image") == []
    assert json_ld_objects(external) == []
    # The local page URL cannot be absolutized, so no canonical is invented.
    assert _canonical_href(external) == []
    assert _atom_hrefs(external) == []
    collected = _meta_items(external)
    meta_values = [content for _, content in collected.open_graph_items + collected.twitter_items]
    assert EXTERNAL_URL in meta_values
    assert local_url not in meta_values
    assert all("example.test/docs" not in value for value in meta_values), meta_values
