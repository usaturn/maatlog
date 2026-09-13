"""Integration tests for official MaatLog themes and Theme API contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ProjectFactory
from jinja2 import Environment
from social_metadata import (
    assert_no_duplicate_social_metadata,
    assert_no_social_metadata,
    json_ld_objects,
    open_graph_values,
    twitter_values,
)

from maatlog.errors import MaatlogBuildError
from maatlog.theme_api import (
    REQUIRED_BLOCKS,
    REQUIRED_TEMPLATES,
    collect_template_block_names,
    validate_selected_theme,
)

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
_THEME_FIXTURE_PREFIX = f"import sys\nsys.path.insert(0, {str(_FIXTURES_DIR)!r})\n"
_THEME_FIXTURE_EXTENSIONS = ("maatlog_theme_fixtures",)

POST_PROJECT = {
    "post.md": """---
maatlog-post: true
maatlog-slug: hello-base
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-tags: [sphinx]
maatlog-categories: [engineering]
maatlog-authors: [alice]
maatlog-excerpt: A short summary.
---
# Hello Base

Internal body for the base theme contract.
""",
}

EXTERNAL_POST_PROJECT = {
    "post.md": """---
maatlog-post: true
maatlog-slug: external-base
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-excerpt: External summary only.
maatlog-external-url: https://publisher.example/articles/42
---
# External Post

This body must not appear for external posts.
""",
}

CSS_CUSTOM_PROPERTIES = (
    "--maatlog-content-width",
    "--maatlog-sidebar-width",
    "--maatlog-nav-width",
    "--maatlog-rail-width",
    "--maatlog-author-avatar-size",
    "--maatlog-banner-background",
    "--maatlog-banner-height",
    "--maatlog-space-xs",
    "--maatlog-space-sm",
    "--maatlog-space-md",
    "--maatlog-space-lg",
    "--maatlog-color-text",
    "--maatlog-color-muted",
    "--maatlog-color-link",
    "--maatlog-color-border",
    "--maatlog-card-background",
)


def test_base_theme_contract(make_project: ProjectFactory) -> None:
    result = make_project(files=POST_PROJECT, theme="maatlog-base").build()
    page = result.html("post.html")

    assert page.select_one(".maatlog-post[data-maatlog-component='post']")
    assert page.select_one(".maatlog-post-body")
    assert page.select_one(".maatlog-post-header")
    assert page.select_one(".maatlog-post-meta")
    assert page.select_one(".maatlog-post-navigation")
    assert page.select_one(".maatlog-sidebar[data-maatlog-component='sidebar']")
    assert result.asset("_static/maatlog.css").exists()

    css = result.asset("_static/maatlog.css").read_text(encoding="utf-8")
    for prop in CSS_CUSTOM_PROPERTIES:
        assert prop in css


def test_base_theme_external_post_shows_excerpt_not_body(make_project: ProjectFactory) -> None:
    result = make_project(files=EXTERNAL_POST_PROJECT, theme="maatlog-base").build()
    page = result.html("post.html")

    assert page.select_one(".maatlog-external-link")
    assert "External summary only." in page.text
    assert "This body must not appear for external posts." not in page.text
    assert "Read on external site" in page.text


def test_validate_selected_theme_accepts_maatlog_base(make_project: ProjectFactory) -> None:
    """validate_selected_theme recognizes all required templates and blocks."""
    result = make_project(files=POST_PROJECT, theme="maatlog-base").build()
    app = result.app

    # Already ran at builder-inited; call again to assert no raise.
    validate_selected_theme(app)

    environment = app.builder.templates.environment
    assert isinstance(environment, Environment)
    for template_name in REQUIRED_TEMPLATES:
        environment.get_template(template_name)

    required = set(REQUIRED_BLOCKS)
    for page_template in ("maatlog/post.html", "maatlog/archive.html"):
        blocks = collect_template_block_names(environment, page_template)
        assert required.issubset(blocks), f"{page_template} missing {required - blocks}"


def test_base_theme_package_data_on_disk() -> None:
    """Theme files are present under the package for wheel packaging."""
    import maatlog

    theme_root = Path(maatlog.__file__).resolve().parent / "themes" / "maatlog-base"
    assert (theme_root / "theme.conf").is_file()
    assert (theme_root / "maatlog-theme.toml").is_file()
    assert (theme_root / "static" / "maatlog.css").is_file()
    for relative in REQUIRED_TEMPLATES:
        assert (theme_root / relative).is_file(), relative


def test_theme_templates_close_every_jinja_comment() -> None:
    """Every ``{#`` gets its own ``#}``.

    A comment terminated with ``-}`` instead of ``-#}`` does not close: Jinja keeps
    reading to the next ``#}`` and swallows whatever lies between, so markup added
    there disappears from the output without any error.
    """
    import maatlog

    themes_root = Path(maatlog.__file__).resolve().parent / "themes"
    environment = Environment()
    templates = sorted(themes_root.rglob("*.html"))
    assert templates, "no theme templates found"
    for template in templates:
        source = template.read_text(encoding="utf-8")
        opened = source.count("{#")
        closed = sum(1 for _, token, _ in environment.lex(source) if token == "comment_begin")
        assert closed == opened, f"{template.relative_to(themes_root)} leaves a Jinja comment unclosed"


def test_default_theme_is_usable_without_options(make_project: ProjectFactory) -> None:
    """html_theme defaults to maatlog-default; post page renders sidebar."""
    result = make_project(files=POST_PROJECT).build()
    page = result.html("post.html")

    assert page.select_one(".maatlog-sidebar")
    assert page.select_one(".maatlog-post[data-maatlog-component='post']")
    assert result.asset("_static/maatlog.css").exists()
    css = result.asset("_static/maatlog.css").read_text(encoding="utf-8")
    assert "grid-template" in css or "display: grid" in css
    assert "focus-visible" in css


def test_default_theme_package_data_on_disk() -> None:
    import maatlog

    theme_root = Path(maatlog.__file__).resolve().parent / "themes" / "maatlog-default"
    assert (theme_root / "theme.conf").is_file()
    assert (theme_root / "maatlog-theme.toml").is_file()
    assert (theme_root / "static" / "maatlog.css").is_file()
    conf = (theme_root / "theme.conf").read_text(encoding="utf-8")
    assert "inherit = maatlog-base" in conf
    manifest = (theme_root / "maatlog-theme.toml").read_text(encoding="utf-8")
    assert 'implementation = "inherits-base"' in manifest


POST_HEADER_PROJECT = {
    "post.md": """---
maatlog-post: true
maatlog-slug: claude-code-memo
maatlog-published-at: 2025-06-28T00:00:00+09:00
maatlog-tags: [ai, claude-code]
maatlog-categories: [it-technology]
maatlog-authors: [usaturn]
---
# 初心者が Claude Code を使い始めたメモ

Body text here.
""",
}

NUMBERED_POST_HEADER_PROJECT = {
    **POST_HEADER_PROJECT,
    "index.rst": """Root
====

.. toctree::
   :numbered:

   post
""",
}


def test_post_page_renders_single_title_and_structured_meta(make_project: ProjectFactory) -> None:
    result = make_project(
        files=POST_HEADER_PROJECT,
        config={"maatlog_timezone": "Asia/Tokyo"},
    ).build()
    page = result.html("post.html")

    assert "初心者が Claude Code を使い始めたメモ" in page.text
    assert page.select_one(".maatlog-post-info time[datetime='2025-06-28T00:00:00+09:00']")
    assert "2025年6月28日" in page.text
    assert ">2025年6月28日<" in page.text
    assert page.select_one(".maatlog-post-meta-separator")
    assert page.select_one(".maatlog-post-authors .maatlog-taxonomy-link[href='blog/author/usaturn.html']")
    assert page.select_one(".maatlog-post-categories .maatlog-category-badge[href='blog/category/it-technology.html']")
    assert page.select_one(".maatlog-post-tags .maatlog-tag-link[href='blog/tag/ai.html']")
    assert "#ai" in page.text
    assert "Body text here." in page.text
    assert len(page.select("h1")) == 1


def test_post_page_in_numbered_toctree_renders_single_title(make_project: ProjectFactory) -> None:
    result = make_project(
        files=NUMBERED_POST_HEADER_PROJECT,
        config={"maatlog_timezone": "Asia/Tokyo"},
    ).build()
    page = result.html("post.html")

    assert page.select_one(".maatlog-post-header h1") is not None
    assert "Body text here." in page.text
    assert len(page.select("h1")) == 1


def test_inherits_base_third_party_theme_is_accepted(make_project: ProjectFactory) -> None:
    result = make_project(
        files=POST_PROJECT,
        theme="inherits_base",
        extensions=_THEME_FIXTURE_EXTENSIONS,
        conf_py_prefix=_THEME_FIXTURE_PREFIX,
    ).build()
    page = result.html("post.html")
    assert page.select_one(".maatlog-post")
    assert page.select_one(".maatlog-sidebar")
    assert open_graph_values(page, "og:type") == ["article"]
    assert len(json_ld_objects(page)) == 1
    assert_no_duplicate_social_metadata(page)


def test_standalone_third_party_theme_is_accepted(make_project: ProjectFactory) -> None:
    result = make_project(
        files=POST_PROJECT,
        theme="standalone",
        extensions=_THEME_FIXTURE_EXTENSIONS,
        conf_py_prefix=_THEME_FIXTURE_PREFIX,
    ).build()
    page = result.html("post.html")
    assert page.select_one(".maatlog-post")
    assert page.select_one(".maatlog-sidebar")
    assert_no_social_metadata(page)
    assert set(result.app.env.get_domain("maatlog").data["posts_by_docname"]) == {"post"}


def test_standalone_optin_third_party_theme_renders_shared_metadata(make_project: ProjectFactory) -> None:
    """A standalone theme that opts in renders the shared View contract.

    ``maatlog.metadata`` is present in the standalone template context even when
    the theme does not opt in; iterating it like the shared partial renders the
    post's article metadata exactly once.
    """
    result = make_project(
        files=POST_PROJECT,
        theme="standalone_optin",
        extensions=_THEME_FIXTURE_EXTENSIONS,
        conf_py_prefix=_THEME_FIXTURE_PREFIX,
    ).build()
    page = result.html("post.html")
    assert open_graph_values(page, "og:type") == ["article"]
    assert twitter_values(page, "twitter:card") == ["summary"]
    assert len(json_ld_objects(page)) == 1
    assert_no_duplicate_social_metadata(page)


@pytest.mark.parametrize(
    ("theme", "code"),
    [
        ("missing-manifest", "maatlog.theme.manifest-missing"),
        ("incompatible", "maatlog.theme.api-incompatible"),
        ("missing-block", "maatlog.theme.block-missing"),
        ("base-not-inherited", "maatlog.theme.base-not-inherited"),
        ("missing-templates", "maatlog.theme.template-missing"),
        ("missing-palette-css", "maatlog.theme.palette-stylesheet-missing"),
    ],
)
def test_invalid_third_party_theme_fails(
    make_project: ProjectFactory,
    theme: str,
    code: str,
) -> None:
    with pytest.raises(MaatlogBuildError, match=code):
        make_project(
            files=POST_PROJECT,
            theme=theme,
            extensions=_THEME_FIXTURE_EXTENSIONS,
            conf_py_prefix=_THEME_FIXTURE_PREFIX,
        ).build()


EDITORIAL_POST_PROJECT = {
    "post.md": """---
maatlog-post: true
maatlog-slug: editorial
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-tags: [sphinx]
maatlog-categories: [engineering]
maatlog-authors: [alice]
maatlog-excerpt: A tagline that belongs above the fold.
maatlog-image: images/cover.png
---
# Editorial post

Body text here.
""",
    "images/cover.png": b"png",
}


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_post_header_carries_the_editorial_hierarchy(make_project: ProjectFactory, theme: str) -> None:
    # category → title → tagline → meta → hero image を 1 つの <header> にまとめ、
    # 記事ページの視覚階層を CSS だけで組めるようにする。
    result = make_project(files=EDITORIAL_POST_PROJECT, theme=theme).build()
    page = result.html("post.html")
    header = page.select_one(".maatlog-post-header")

    assert header is not None
    assert page.select_one(".maatlog-post-header .maatlog-post-eyebrow .maatlog-category-badge") is not None
    assert page.select_one(".maatlog-post-header h1") is not None
    assert page.select_one(".maatlog-post-header .maatlog-post-tagline") is not None
    assert page.select_one(".maatlog-post-header .maatlog-post-meta") is not None
    assert page.select_one(".maatlog-post-header .maatlog-post-hero-image") is not None
    assert len(page.select("h1")) == 1


def test_post_header_orders_eyebrow_title_tagline_meta_hero(make_project: ProjectFactory) -> None:
    # 視覚階層は DOM 順で決まる。CSS を挟まずに読める順序であること。
    result = make_project(files=EDITORIAL_POST_PROJECT).build()
    html = result.html("post.html").text

    order = [
        html.index('class="maatlog-post-eyebrow"'),
        html.index("<h1>"),
        html.index('class="maatlog-post-tagline"'),
        html.index('class="maatlog-post-meta"'),
        html.index('class="maatlog-post-hero-image"'),
    ]
    assert order == sorted(order), order


def test_post_meta_keeps_date_author_and_tags_but_drops_categories(
    make_project: ProjectFactory,
) -> None:
    # category は eyebrow に出したので meta からは外す。date / author / tag は残す。
    result = make_project(files=EDITORIAL_POST_PROJECT).build()
    page = result.html("post.html")

    assert page.select_one(".maatlog-post-meta .maatlog-post-info time") is not None
    assert page.select_one(".maatlog-post-meta .maatlog-post-authors .maatlog-post-author-link") is not None
    assert page.select_one(".maatlog-post-meta .maatlog-post-tags .maatlog-tag-link") is not None
    assert page.select_one(".maatlog-post-meta .maatlog-post-categories") is None


def test_hero_image_is_decorative(make_project: ProjectFactory) -> None:
    # 記事タイトルと同じ情報しか持たない。読み上げに出すと二重になる。
    result = make_project(files=EDITORIAL_POST_PROJECT).build()
    hero = result.html("post.html").select_one(".maatlog-post-hero-image")

    assert hero is not None
    assert hero["alt"] == ""


def test_external_post_shows_the_excerpt_once(make_project: ProjectFactory) -> None:
    # excerpt は header の tagline が出す。本文側にも出すと同じ文が 2 回出る。
    # head は仕様として Social Metadata が同じ excerpt を出すため、数える範囲は本文（body）に絞る。
    result = make_project(files=EXTERNAL_POST_PROJECT, theme="maatlog-base").build()
    page = result.html("post.html")

    tagline = page.select_one(".maatlog-post-tagline")
    assert tagline is not None
    assert page.select_one(".maatlog-post-body .maatlog-post-excerpt") is None
    body = page.text[page.text.index("<body") :]
    assert body.count("External summary only.") == 1
    assert page.select_one(".maatlog-external-link") is not None


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_post_card_exposes_machine_readable_published_at(make_project: ProjectFactory, theme: str) -> None:
    # Issue #62: NEW 判定のために post-card が data-maatlog-published-at 属性を持つ。
    result = make_project(files=POST_PROJECT, theme=theme).build()
    archive = result.html("blog.html")

    card = archive.select_one(".maatlog-post-card")
    assert card is not None
    assert "data-maatlog-published-at" in card, "post-card に data-maatlog-published-at 属性がない"
    # 値が ISO 8601 で始まる（機械可読な形式）
    val = card["data-maatlog-published-at"]
    assert isinstance(val, str) and val.startswith("2026-"), f"予期しない値: {val!r}"
