"""Integration tests for official MaatLog themes and Theme API contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ProjectFactory
from jinja2 import Environment

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


@pytest.mark.parametrize(
    ("theme", "code"),
    [
        ("missing-manifest", "maatlog.theme.manifest-missing"),
        ("incompatible", "maatlog.theme.api-incompatible"),
        ("missing-block", "maatlog.theme.block-missing"),
        ("base-not-inherited", "maatlog.theme.base-not-inherited"),
        ("missing-templates", "maatlog.theme.template-missing"),
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
