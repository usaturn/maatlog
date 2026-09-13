"""Integration coverage for author profile social metadata (issue #210)."""

from __future__ import annotations

from typing import cast

import pytest
from conftest import HtmlPage, ProjectFactory
from social_metadata import json_ld_objects, open_graph_values, twitter_values

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100fdff03fa0000000049454e44ae426082"
)

BASEURL = "https://example.test/docs/"
AVATAR_URL = f"{BASEURL}_images/alice.png"

#: Kept away from both ends of the string so ``str.strip()`` cannot remove the
#: interesting part: U+2028 and U+2029 count as whitespace in Python.
HOSTILE_TEXT = "Alice</script><b>&\"'\\ \u2028 \u2029 日本語 end"


def _post(slug: str, day: int, author: str) -> str:
    title = slug.capitalize()
    return (
        ":maatlog-post: true\n"
        f":maatlog-slug: {slug}\n"
        f":maatlog-published-at: 2026-08-{day:02d}T00:00:00Z\n"
        f":maatlog-authors: {author}\n"
        "\n"
        f"{title}\n"
        f"{'=' * len(title)}\n"
    )


PROFILE_FILES: dict[str, str | bytes] = {
    "index.rst": "Home\n====\n",
    "normal.rst": "Normal\n======\n",
    "posts/one.rst": _post("one", 1, "alice"),
    "posts/two.rst": _post("two", 2, "alice"),
    "posts/three.rst": _post("three", 3, "bob"),
    "authors/alice.md": "# About Alice\n\nAlice writes about Python.\n",
    "authors/alice.png": PNG_1X1,
}

PROFILE_CONFIG: dict[str, object] = {
    "project": "Example Blog",
    "html_baseurl": BASEURL,
    "maatlog_home_docname": "index",
    # One post per page, so alice's two posts split into a profile page and a page 2.
    "maatlog_page_size": 1,
    "maatlog_authors": {"alice": "Alice Anderson", "bob": "Bob"},
    "maatlog_author_profiles": {
        "alice": {
            "about_docname": "authors/alice",
            "avatar": "authors/alice.png",
            "bio_short": "Python developer.",
            "links": [
                {"type": "github", "url": "https://github.com/alice"},
                {"type": "mastodon", "url": "https://social.example/@alice"},
            ],
        }
    },
}

HOSTILE_CONFIG: dict[str, object] = {
    **PROFILE_CONFIG,
    "maatlog_authors": {"alice": HOSTILE_TEXT, "bob": "Bob"},
    "maatlog_author_profiles": {
        "alice": {
            "about_docname": "authors/alice",
            "avatar": "authors/alice.png",
            "bio_short": HOSTILE_TEXT,
            "links": [{"type": "github", "url": "https://github.com/alice"}],
        }
    },
}


def paths_for(builder: str) -> dict[str, str]:
    if builder == "html":
        return {
            "profile": "blog/author/alice.html",
            "profile_page_2": "blog/author/alice/page/2.html",
            "unconfigured_author": "blog/author/bob.html",
            "post": "posts/one.html",
            "normal": "normal.html",
        }
    return {
        "profile": "blog/author/alice/index.html",
        "profile_page_2": "blog/author/alice/page/2/index.html",
        "unconfigured_author": "blog/author/bob/index.html",
        "post": "posts/one/index.html",
        "normal": "normal/index.html",
    }


def profile_document(page: HtmlPage) -> dict[str, object]:
    documents = json_ld_objects(page)
    assert len(documents) == 1
    document = documents[0]
    assert isinstance(document, dict)
    return cast("dict[str, object]", document)


def main_entity_of(page: HtmlPage) -> dict[str, object]:
    entity = profile_document(page)["mainEntity"]
    assert isinstance(entity, dict)
    return cast("dict[str, object]", entity)


def json_ld_types(page: HtmlPage) -> list[object]:
    return [
        cast("dict[str, object]", document).get("@type")
        for document in json_ld_objects(page)
        if isinstance(document, dict)
    ]


@pytest.mark.parametrize(
    ("builder", "profile_url"),
    [("html", f"{BASEURL}blog/author/alice.html"), ("dirhtml", f"{BASEURL}blog/author/alice/")],
)
def test_profile_page_publishes_social_metadata(make_project: ProjectFactory, builder: str, profile_url: str) -> None:
    result = make_project(files=PROFILE_FILES, config=PROFILE_CONFIG, builder=builder).build()

    page = result.html(paths_for(builder)["profile"])
    assert open_graph_values(page, "og:type") == ["profile"]
    assert open_graph_values(page, "og:title") == ["Alice Anderson"]
    assert open_graph_values(page, "og:site_name") == ["Example Blog"]
    assert open_graph_values(page, "og:url") == [profile_url]
    assert open_graph_values(page, "og:description") == ["Python developer."]
    assert open_graph_values(page, "og:image") == [AVATAR_URL]
    assert twitter_values(page, "twitter:card") == ["summary"]
    assert twitter_values(page, "twitter:title") == ["Alice Anderson"]
    assert twitter_values(page, "twitter:description") == ["Python developer."]
    assert twitter_values(page, "twitter:image") == [AVATAR_URL]
    assert profile_document(page) == {
        "@context": "https://schema.org",
        "@type": "ProfilePage",
        "mainEntity": {
            "@type": "Person",
            "name": "Alice Anderson",
            "description": "Python developer.",
            "image": AVATAR_URL,
            "url": profile_url,
            "sameAs": ["https://github.com/alice", "https://social.example/@alice"],
        },
    }


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_only_the_first_profile_page_carries_a_person(make_project: ProjectFactory, builder: str) -> None:
    """Page 2, unconfigured authors, posts and normal pages never describe a Person.

    The check is by JSON-LD type rather than "no metadata at all", so it keeps holding
    once #209 and #211 publish their own documents on these same pages.
    """
    # All three posts publish only when SOURCE_DATE_EPOCH is after 2026-08-03; the
    # default (2026-08-01) schedules the Aug 2/3 posts, so alice would keep a single
    # page and there would be no page 2 to assert on.
    result = make_project(
        files=PROFILE_FILES,
        config=PROFILE_CONFIG,
        builder=builder,
        source_date_epoch="1789171200",
    ).build()

    paths = paths_for(builder)
    for key in ("profile_page_2", "unconfigured_author", "post", "normal"):
        page = result.html(paths[key])
        assert "ProfilePage" not in json_ld_types(page), key
        assert "profile" not in open_graph_values(page, "og:type"), key


def test_without_a_baseurl_only_url_free_metadata_is_published(make_project: ProjectFactory) -> None:
    result = make_project(
        files=PROFILE_FILES,
        config={**PROFILE_CONFIG, "html_baseurl": "", "maatlog_generate_feeds": False},
    ).build()

    page = result.html("blog/author/alice.html")
    assert open_graph_values(page, "og:type") == ["profile"]
    assert open_graph_values(page, "og:title") == ["Alice Anderson"]
    assert open_graph_values(page, "og:description") == ["Python developer."]
    assert open_graph_values(page, "og:url") == []
    assert open_graph_values(page, "og:image") == []
    assert twitter_values(page, "twitter:image") == []
    entity = main_entity_of(page)
    assert set(entity) == {"@type", "name", "description", "sameAs"}
    assert entity["sameAs"] == ["https://github.com/alice", "https://social.example/@alice"]


def test_hostile_profile_text_cannot_escape_the_script_element(make_project: ProjectFactory) -> None:
    result = make_project(files=PROFILE_FILES, config=HOSTILE_CONFIG).build()

    page = result.html("blog/author/alice.html")
    entity = main_entity_of(page)
    assert entity["name"] == HOSTILE_TEXT
    assert entity["description"] == HOSTILE_TEXT
    assert open_graph_values(page, "og:title") == [HOSTILE_TEXT]


def test_profile_metadata_does_not_disturb_discovery_links(make_project: ProjectFactory) -> None:
    result = make_project(files=PROFILE_FILES, config=PROFILE_CONFIG).build()

    page = result.html("blog/author/alice.html")
    assert len(page.select('link[rel="canonical"]')) == 1
    assert len(page.select('link[type="application/atom+xml"]')) == 2


def test_parallel_build_publishes_one_profile_page_document(make_project: ProjectFactory) -> None:
    result = make_project(files=PROFILE_FILES, config=PROFILE_CONFIG).build(parallel=4)

    page = result.html("blog/author/alice.html")
    assert profile_document(page)["@type"] == "ProfilePage"
    assert open_graph_values(page, "og:type") == ["profile"]


def test_incremental_rebuild_keeps_the_profile_metadata_stable(make_project: ProjectFactory) -> None:
    """A profile whose About body changed must keep byte-identical metadata.

    The projector reads only the template context, so a rebuild cannot pick up stale or
    duplicated values — this pins that down rather than assuming it.
    """
    project = make_project(files=PROFILE_FILES, config=PROFILE_CONFIG)
    first = profile_document(project.build().html("blog/author/alice.html"))

    project.write("authors/alice.md", "# About Alice\n\nUpdated about body.\n")
    page = project.build(reuse_environment=True).html("blog/author/alice.html")

    assert "Updated about body." in page
    assert profile_document(page) == first
