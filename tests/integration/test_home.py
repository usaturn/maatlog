"""Integration tests for the MaatLog blog home page (maatlog_home_docname)."""

from __future__ import annotations

from collections.abc import Mapping
from io import StringIO
from pathlib import Path

import pytest
from conftest import ProjectFactory
from sphinx.application import Sphinx

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

HOME_PROJECT: Mapping[str, str] = {
    "index.rst": "Example Blog\n============\n\nWelcome to the blog.\n",
    "one.md": """---
maatlog-post: true
maatlog-slug: one
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-tags: [sphinx]
---
# One

First post.
""",
    "two.md": """---
maatlog-post: true
maatlog-slug: two
maatlog-published-at: 2026-07-30T09:00:00Z
maatlog-tags: [sphinx]
---
# Two

Second post.
""",
}


def _make_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: Mapping[str, object],
    theme: str = "maatlog-default",
    extensions: tuple[str, ...] = ("maatlog",),
    files: Mapping[str, str] = HOME_PROJECT,
    label: str = "home",
) -> Sphinx:
    """Build a Sphinx app with an inspectable warning stream (no -W)."""
    root = tmp_path / label
    srcdir = root / "source"
    srcdir.mkdir(parents=True)
    for name, content in files.items():
        target = srcdir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    lines = [
        # Fixture themes live under tests/fixtures; mirror test_themes.py's prefix.
        f"import sys\nsys.path.insert(0, {str(_FIXTURES_DIR)!r})",
        f"extensions = {list(extensions)!r}",
        "source_suffix = {'.rst': 'restructuredtext', '.md': 'markdown'}",
        "root_doc = 'index'",
        "html_baseurl = 'https://example.test/'",
        f"html_theme = {theme!r}",
    ]
    lines.extend(f"{name} = {value!r}" for name, value in config.items())
    (srcdir / "conf.py").write_text("\n".join(lines) + "\n", encoding="utf-8")

    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1785542400")
    warning_stream = StringIO()
    app = Sphinx(
        str(srcdir),
        str(srcdir),
        str(root / "output"),
        str(root / "doctrees"),
        "html",
        status=StringIO(),
        warning=warning_stream,
        warningiserror=False,
        freshenv=True,
    )
    app.__dict__["_maatlog_test_warning_stream"] = warning_stream
    return app


def test_home_page_renders_hero_intro_cards_and_archive_link(make_project: ProjectFactory) -> None:
    result = make_project(
        files=HOME_PROJECT,
        config={"maatlog_home_docname": "index", "project": "Example Blog", "maatlog_tagline": "Notes"},
    ).build()

    home = result.html("index.html")
    assert home.select_one(".maatlog-hero[data-maatlog-component='hero']") is not None
    assert "Example Blog" in home
    assert "Notes" in home
    assert home.select_one(".maatlog-home-intro") is not None
    assert "Welcome to the blog." in home
    assert home.select_one(".maatlog-post-card") is not None
    archive_link = home.select_one(".maatlog-home-archive-link")
    assert archive_link is not None
    assert archive_link["href"] == "blog.html"
    # The home page has no pagination.
    assert home.select_one(".maatlog-pagination") is None


def test_archive_root_loses_hero_when_home_is_active(make_project: ProjectFactory) -> None:
    result = make_project(
        files=HOME_PROJECT,
        config={"maatlog_home_docname": "index", "project": "Example Blog"},
    ).build()
    blog = result.html("blog.html")
    assert blog.select_one(".maatlog-hero") is None
    assert blog.select_one(".maatlog-archive-header") is not None


def test_archive_root_keeps_hero_when_home_is_not_configured(make_project: ProjectFactory) -> None:
    result = make_project(files=HOME_PROJECT, config={"project": "Example Blog"}).build()
    blog = result.html("blog.html")
    assert blog.select_one(".maatlog-hero") is not None
    home = result.html("index.html")
    assert home.select_one(".maatlog-hero") is None


def test_home_respects_page_size(make_project: ProjectFactory) -> None:
    result = make_project(
        files=HOME_PROJECT,
        config={"maatlog_home_docname": "index", "maatlog_page_size": 1},
    ).build()
    home = result.html("index.html")
    assert len(home.select(".maatlog-post-card")) == 1


def test_home_that_is_also_a_post_still_captures_feed_body(make_project: ProjectFactory) -> None:
    """Home wins over post.html, but the post body must still be stored for Atom feeds."""
    result = make_project(
        files=HOME_PROJECT,
        config={"maatlog_home_docname": "one", "project": "Example Blog"},
    ).build()

    home = result.html("one.html")
    assert home.select_one(".maatlog-hero[data-maatlog-component='hero']") is not None
    assert home.select_one(".maatlog-post[data-maatlog-component='post']") is None
    atom = result.path("blog/atom.xml").read_text(encoding="utf-8")
    assert "First post." in atom


def test_home_that_is_also_a_post_omits_its_own_card(
    make_project: ProjectFactory,
) -> None:
    result = make_project(
        files=HOME_PROJECT,
        config={
            "maatlog_home_docname": "one",
            "maatlog_page_size": 1,
            "project": "Example Blog",
        },
    ).build()

    home = result.html("one.html")
    cards = home.select(".maatlog-post-card")
    assert home.select_one(".maatlog-post-card[data-slug='one']") is None
    assert home.select_one(".maatlog-post-card[data-slug='two']") is not None
    assert len(cards) == 1


def test_home_that_is_also_a_post_keeps_explicit_canonical(
    make_project: ProjectFactory,
) -> None:
    files = {
        "one.md": """---
maatlog-post: true
maatlog-slug: one
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-canonical-url: https://elsewhere.example/one/
---
# One

First post.
""",
        "two.md": """---
maatlog-post: true
maatlog-slug: two
maatlog-published-at: 2026-07-30T09:00:00Z
---
# Two

Second post.
""",
    }
    result = make_project(
        files=files,
        config={"maatlog_home_docname": "one", "project": "Example Blog"},
    ).build()
    home = result.html("one.html")
    canonical = home.select_one('link[rel="canonical"]')

    assert home.select_one(".maatlog-hero[data-maatlog-component='hero']") is not None
    assert canonical is not None
    assert canonical["href"] == "https://elsewhere.example/one/"
    assert canonical["href"] != "https://example.test/one.html"


def test_home_that_is_the_only_post_does_not_claim_there_are_no_posts(
    make_project: ProjectFactory,
) -> None:
    files = {
        "only.md": """---
maatlog-post: true
maatlog-slug: only
maatlog-published-at: 2026-07-31T09:00:00Z
---
# Only

Only post body.
""",
    }
    result = make_project(
        files=files,
        config={"maatlog_home_docname": "only", "project": "Example Blog"},
    ).build()
    home = result.html("only.html")

    assert "1 posts" in home
    assert home.select_one(".maatlog-post-card") is None
    assert home.select_one(".maatlog-archive-empty") is None


def test_unknown_home_docname_warns_and_keeps_archive_hero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _make_app(
        tmp_path,
        monkeypatch,
        config={"maatlog_home_docname": "not-there"},
        label="unknown-docname",
    )
    app.build()
    warnings: StringIO = app.__dict__["_maatlog_test_warning_stream"]
    text = warnings.getvalue()
    assert "maatlog.home.docname-unknown" in text
    blog = (Path(app.outdir) / "blog.html").read_text(encoding="utf-8")
    assert "maatlog-hero" in blog


def test_theme_without_home_template_warns_and_renders_normal_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _make_app(
        tmp_path,
        monkeypatch,
        config={"maatlog_home_docname": "index"},
        theme="standalone",
        extensions=("maatlog", "maatlog_theme_fixtures"),
        label="no-home-template",
    )
    app.build()
    warnings: StringIO = app.__dict__["_maatlog_test_warning_stream"]
    assert "maatlog.theme.home-template-missing" in warnings.getvalue()
    home = (Path(app.outdir) / "index.html").read_text(encoding="utf-8")
    assert "Welcome to the blog." in home


def test_api11_theme_without_home_template_makes_archive_root_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Theme API 1.1 without ``home.html``: the archive root takes over as the blog top."""
    app = _make_app(
        tmp_path,
        monkeypatch,
        config={"maatlog_home_docname": "index"},
        theme="standalone_11",
        extensions=("maatlog", "maatlog_theme_fixtures"),
        label="api11-no-home-template",
    )
    app.build()
    warnings: StringIO = app.__dict__["_maatlog_test_warning_stream"]
    assert "maatlog.theme.home-template-missing" in warnings.getvalue()

    blog = (Path(app.outdir) / "blog.html").read_text(encoding="utf-8")
    assert "maatlog-hero" in blog

    home = (Path(app.outdir) / "index.html").read_text(encoding="utf-8")
    assert "Welcome to the blog." in home
    assert "maatlog-hero" not in home

    tag = (Path(app.outdir) / "blog" / "tag" / "sphinx.html").read_text(encoding="utf-8")
    assert "maatlog-hero" not in tag


def test_home_updates_after_post_title_changes_incrementally(
    make_project: ProjectFactory,
) -> None:
    project = make_project(
        files=HOME_PROJECT,
        config={"maatlog_home_docname": "index", "project": "Example Blog"},
    )
    project.build(reuse_environment=False)

    (project.srcdir / "one.md").write_text(
        HOME_PROJECT["one.md"].replace("# One", "# One Renamed"),
        encoding="utf-8",
    )
    second = project.build(reuse_environment=True)

    assert "One Renamed" in second.html("blog.html")
    assert "One Renamed" in second.html("index.html")


def test_home_updates_when_scheduled_post_becomes_published(
    make_project: ProjectFactory,
) -> None:
    files = {
        "index.rst": "Example Blog\n============\n\nWelcome to the blog.\n",
        "scheduled.md": """---
maatlog-post: true
maatlog-slug: future-post
maatlog-published-at: 2026-08-01T12:00:00Z
---
# Future Post

Scheduled body.
""",
    }
    project = make_project(
        files=files,
        source_date_epoch="1782864000",
        config={
            "maatlog_generate_feeds": False,
            "maatlog_home_docname": "index",
            "maatlog_timezone": "UTC",
        },
    )
    first = project.build(reuse_environment=False)
    assert "Future Post" not in first.html("index.html")

    project.source_date_epoch = "1786752000"
    second = project.build(reuse_environment=True)

    assert "Future Post" in second.html("blog.html")
    assert "Future Post" in second.html("index.html")
