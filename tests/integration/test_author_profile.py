"""Integration coverage for author profile pages."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from conftest import ProjectFactory
from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

import maatlog
from maatlog.errors import MaatlogBuildError
from maatlog.views import AuthorLinkView, AuthorProfileView, AuthorStatsView

POST_ONE = """---
maatlog-post: true
maatlog-slug: one
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-authors: [alice]
---
# One

First post.
"""

POST_TWO = """---
maatlog-post: true
maatlog-slug: two
maatlog-published-at: 2026-07-30T09:00:00Z
maatlog-authors: [bob]
---
# Two

Second post.
"""

BASE_FILES = {"one.md": POST_ONE, "two.md": POST_TWO}

AUTHORS = {"alice": "Alice Anderson", "bob": "Bob"}


def codes_of(error: MaatlogBuildError) -> list[str]:
    return [item.code for item in error.diagnostics]


@pytest.mark.parametrize(
    ("profile", "expected_code"),
    [
        ({"role": "Editor"}, None),
        ({"featured_posts": ["nope"]}, "maatlog.author.featured-unknown"),
        ({"featured_posts": ["two"]}, "maatlog.author.featured-foreign"),
        ({"about_docname": "authors/missing"}, "maatlog.author.about-unknown"),
        ({"avatar": "authors/absent.png"}, "maatlog.image.missing"),
    ],
)
def test_profile_cross_references_are_validated_during_build(
    make_project: ProjectFactory, profile: dict[str, object], expected_code: str | None
) -> None:
    site = make_project(
        files=BASE_FILES,
        config={"maatlog_authors": AUTHORS, "maatlog_author_profiles": {"alice": profile}},
    )

    if expected_code is None:
        site.build()
        return

    with pytest.raises(MaatlogBuildError) as excinfo:
        site.build()
    assert codes_of(excinfo.value) == [expected_code]


def test_profile_for_an_author_absent_from_maatlog_authors_fails(make_project: ProjectFactory) -> None:
    site = make_project(
        files=BASE_FILES,
        config={"maatlog_authors": AUTHORS, "maatlog_author_profiles": {"carol": {"role": "Ghost"}}},
    )

    with pytest.raises(MaatlogBuildError) as excinfo:
        site.build()

    assert codes_of(excinfo.value) == ["maatlog.author.profile-unknown"]


PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100fdff03fa0000000049454e44ae426082"
)


def test_avatar_is_copied_into_the_image_directory(make_project: ProjectFactory) -> None:
    site = make_project(
        files={**BASE_FILES, "authors/alice.png": PNG_1X1},
        config={
            "maatlog_authors": AUTHORS,
            "maatlog_author_profiles": {"alice": {"avatar": "authors/alice.png"}},
        },
    )

    result = site.build()

    copied = sorted(path.name for path in result.path("_images").iterdir())
    assert "alice.png" in copied


INDEX_WITHOUT_ABOUT = """Root
====

.. toctree::

   one
   two
"""

ABOUT_ALICE = """# About Alice

Alice writes about Python.
"""


ABOUT_PROFILE_CONFIG = {
    "maatlog_authors": AUTHORS,
    "maatlog_author_profiles": {"alice": {"about_docname": "authors/alice"}},
}
ABOUT_FILES = {**BASE_FILES, "index.rst": INDEX_WITHOUT_ABOUT, "authors/alice.md": ABOUT_ALICE}


def test_about_document_outside_the_toctree_does_not_warn(make_project: ProjectFactory) -> None:
    result = make_project(files=ABOUT_FILES, config=ABOUT_PROFILE_CONFIG).build()

    assert "toc.not_included" not in result.warnings
    assert result.app.env.metadata["authors/alice"].get("orphan") is True


def test_a_document_outside_the_toctree_still_warns_without_a_profile(
    make_project: ProjectFactory,
) -> None:
    """orphan 抑止は About 文書だけに効く。無関係な文書の警告は消さない。"""
    result = make_project(
        files=ABOUT_FILES,
        config={"maatlog_authors": AUTHORS},
    ).build()

    assert "toc.not_included" in result.warnings


def test_render_about_body_resolves_uris_for_the_profile_page(make_project: ProjectFactory) -> None:
    """深さの違う 2 つの docname 間で、画像 URI が埋め込み先ページ基準になる。"""
    from maatlog.profiles import render_about_body

    result = make_project(
        files={
            **BASE_FILES,
            "index.rst": INDEX_WITHOUT_ABOUT,
            "authors/alice.md": "# About Alice\n\n![avatar](alice.png)\n",
            "authors/alice.png": PNG_1X1,
        },
        config=ABOUT_PROFILE_CONFIG,
    ).build()

    body = render_about_body(result.app.builder, about_docname="authors/alice", from_docname="blog/author/alice")

    # blog/author/alice.html から見た _images は ../../_images。
    assert "../../_images/alice.png" in body
    # 文書タイトルの h1 は取り除かれている。
    assert "About Alice</h1>" not in body


def test_render_about_body_restores_the_builder_state(make_project: ProjectFactory) -> None:
    from maatlog.profiles import render_about_body

    result = make_project(files=ABOUT_FILES, config=ABOUT_PROFILE_CONFIG).build()
    builder = cast(Any, result.app.builder)
    before = (builder.current_docname, builder.imgpath, builder.dlpath)

    render_about_body(builder, about_docname="authors/alice", from_docname="blog/author/alice")

    assert (builder.current_docname, builder.imgpath, builder.dlpath) == before


BASE_THEME = Path(maatlog.__file__).parent / "themes" / "maatlog-base"

PROFILE_VIEW = AuthorProfileView(
    slug="alice",
    display_name="Alice Anderson",
    role="Editor & Developer",
    avatar_url="../../_images/alice.png",
    initials="AA",
    bio_short="Python developer.",
    interests=("Python", "Sphinx"),
    links=(AuthorLinkView(type="github", url="https://github.com/alice", label="GitHub", icon="github"),),
    about_html="<p>About body.</p>",
    featured=(),
    stats=AuthorStatsView(post_count=2, writing_since=2024, latest_post=None),
)


def render_component(name: str, **context: object) -> str:
    environment = SandboxedEnvironment(loader=FileSystemLoader(str(BASE_THEME)))
    environment.add_extension("jinja2.ext.i18n")
    cast(Any, environment).install_null_translations()
    return environment.get_template(f"maatlog/components/{name}").render(**context)


def test_profile_header_renders_name_role_and_avatar() -> None:
    html = render_component("profile-header.html", maatlog={"profile": PROFILE_VIEW, "feeds": ()})

    assert 'data-maatlog-component="profile-header"' in html
    assert "Alice Anderson" in html
    assert "Editor &amp; Developer" in html
    assert "../../_images/alice.png" in html
    assert 'data-maatlog-component="author-links"' in html


def test_profile_header_falls_back_to_initials_without_an_avatar() -> None:
    view = replace(PROFILE_VIEW, avatar_url=None)

    html = render_component("profile-header.html", maatlog={"profile": view, "feeds": ()})

    assert "maatlog-profile-avatar-initials" in html
    assert ">AA<" in html


def test_profile_about_is_emitted_unescaped() -> None:
    html = render_component("profile-about.html", maatlog={"profile": PROFILE_VIEW})

    assert "<p>About body.</p>" in html


def test_profile_about_is_omitted_without_a_body() -> None:
    html = render_component("profile-about.html", maatlog={"profile": replace(PROFILE_VIEW, about_html=None)})

    assert html.strip() == ""


def test_profile_interests_renders_one_item_per_value() -> None:
    html = render_component("profile-interests.html", maatlog={"profile": PROFILE_VIEW})

    assert html.count("<li") == 2


def test_profile_stats_renders_every_known_metric() -> None:
    html = render_component("profile-stats.html", maatlog={"profile": PROFILE_VIEW})

    assert ">2<" in html
    assert ">2024<" in html
    # latest_post が None のとき、その項目は出さない。
    assert "<time" not in html


def test_profile_featured_is_omitted_when_unset() -> None:
    html = render_component("profile-featured.html", maatlog={"profile": PROFILE_VIEW})

    assert html.strip() == ""


FULL_CONFIG = {
    "maatlog_authors": AUTHORS,
    "maatlog_author_profiles": {
        "alice": {
            "role": "Editor",
            "bio_short": "Python developer.",
            "interests": ["Python"],
            "links": [{"type": "github", "url": "https://github.com/alice"}],
            "featured_posts": ["one"],
            "about_docname": "authors/alice",
        }
    },
}

FULL_FILES = {**BASE_FILES, "index.rst": INDEX_WITHOUT_ABOUT, "authors/alice.md": ABOUT_ALICE}


def test_author_with_a_profile_renders_the_profile_page(make_project: ProjectFactory) -> None:
    result = make_project(files=FULL_FILES, config=FULL_CONFIG).build()

    page = result.html("blog/author/alice.html")

    assert page.select_one(".maatlog-profile[data-maatlog-component='profile']") is not None
    assert page.select_one(".maatlog-profile-header") is not None
    assert "Alice Anderson" in page
    assert "Alice writes about Python." in page
    assert page.select_one(".maatlog-profile-interests") is not None
    assert page.select_one(".maatlog-profile-featured") is not None
    assert page.select_one(".maatlog-profile-stats") is not None
    assert page.select_one(".maatlog-profile-posts") is not None


def test_author_without_a_profile_keeps_the_archive_page(make_project: ProjectFactory) -> None:
    result = make_project(files=FULL_FILES, config=FULL_CONFIG).build()

    page = result.html("blog/author/bob.html")

    assert page.select_one(".maatlog-archive[data-maatlog-component='archive']") is not None
    assert page.select_one(".maatlog-profile") is None


def test_profile_url_follows_the_archive_docname(make_project: ProjectFactory) -> None:
    result = make_project(files=FULL_FILES, config={**FULL_CONFIG, "maatlog_archive_docname": "journal"}).build()

    assert result.path("journal/author/alice.html").is_file()
    assert not result.path("blog/author/alice.html").exists()


def test_profile_sections_are_absent_from_page_two(make_project: ProjectFactory) -> None:
    posts = {
        f"p{index}.md": (
            "---\n"
            "maatlog-post: true\n"
            f"maatlog-slug: p{index}\n"
            f"maatlog-published-at: 2026-07-{index:02d}T09:00:00Z\n"
            "maatlog-authors: [alice]\n"
            "---\n"
            f"# P{index}\n\nBody.\n"
        )
        for index in range(1, 13)
    }
    index_rst = "Root\n====\n\n.. toctree::\n\n" + "\n".join(f"   p{i}" for i in range(1, 13)) + "\n"
    result = make_project(
        files={**posts, "index.rst": index_rst},
        config={"maatlog_authors": AUTHORS, "maatlog_author_profiles": {"alice": {"role": "Editor"}}},
    ).build()

    page_one = result.html("blog/author/alice.html")
    page_two = result.html("blog/author/alice/page/2.html")

    assert page_one.select_one(".maatlog-profile-header") is not None
    assert page_two.select_one(".maatlog-profile-header") is None
    assert page_two.select_one(".maatlog-archive") is not None


def test_about_document_canonical_points_at_the_profile_page(make_project: ProjectFactory) -> None:
    result = make_project(files=FULL_FILES, config=FULL_CONFIG).build()

    canonical = result.html("authors/alice.html").select_one("link[rel='canonical']")

    assert canonical is not None
    assert canonical["href"] == "https://example.test/blog/author/alice.html"


def test_about_document_without_a_baseurl_has_no_canonical(make_project: ProjectFactory) -> None:
    """feeds を切らないと html_baseurl 必須の検証で先に落ちるため、併せて無効化する。"""
    result = make_project(
        files=FULL_FILES,
        config={**FULL_CONFIG, "html_baseurl": "", "maatlog_generate_feeds": False},
    ).build()

    assert result.html("authors/alice.html").select_one("link[rel='canonical']") is None
