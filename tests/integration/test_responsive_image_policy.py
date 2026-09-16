"""Caller metadata and maatlog-default image policy (issue #216, task 2)."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from conftest import SphinxFactory
from fixtures.responsive_image_fixtures import sample_responsive_image_view
from fixtures.responsive_image_html import img_attrs
from sphinx.application import Sphinx

from maatlog.image_contracts import ImageUsage

POST_FILES: dict[str, str] = {
    "index.rst": "Index\n=====\n\n.. toctree::\n\n   post\n",
    "post.rst": "Post\n====\n\n:maatlog-post: true\n:maatlog-slug: post\n\nBody.\n",
}


def _post_md(slug: str, day: int) -> str:
    return f"""---
maatlog-post: true
maatlog-slug: {slug}
maatlog-published-at: 2026-07-{day:02d}T09:00:00Z
---
# {slug}

Body of {slug}.
"""


def _blog_files(count: int) -> dict[str, str]:
    files: dict[str, str] = {"index.rst": "Example Blog\n============\n\nWelcome.\n"}
    for n in range(1, count + 1):
        files[f"post{n}.md"] = _post_md(f"post{n}", n)
    return files


def _managed(html: str) -> list[dict[str, str]]:
    return [attrs for attrs in img_attrs(html) if attrs.get("data-maatlog-srcset") == "w-v1"]


def _norm(value: str) -> str:
    return " ".join(value.split())


def _read(app: Sphinx, relative: str) -> str:
    return Path(app.outdir, relative).read_text(encoding="utf-8")


def _with_responsive(card: dict[str, Any], usage: ImageUsage) -> dict[str, Any]:
    return {**card, "responsive_image": asdict(sample_responsive_image_view(usage))}


def test_top_and_representative_have_only_one_high(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files=POST_FILES, theme="maatlog-default")

    def inject(app: Sphinx, pagename: str, templatename: str, context: dict[str, Any], doctree: object) -> None:
        del app, pagename, templatename, doctree
        if context.get("maatlog") and context["maatlog"].get("post"):
            post = context["maatlog"]["post"]
            post.update(
                image_url="old.png",
                top_image_url="top.png",
                top_image_alt='Top "caption"',
                responsive_image=asdict(sample_responsive_image_view()),
                responsive_top_image=asdict(sample_responsive_image_view(ImageUsage.POST_TOP)),
            )

    app.connect("html-page-context", inject, priority=999)
    app.build()
    attrs = img_attrs(_read(app, "post.html"))
    managed = [a for a in attrs if a.get("data-maatlog-srcset") == "w-v1"]
    assert len(managed) == 2
    assert sum(a.get("fetchpriority") == "high" for a in managed) == 1
    assert all(a["loading"] == "eager" for a in managed)


def test_home_lead_only_high_and_seventh_latest_lazy(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files=_blog_files(10),
        theme="maatlog-default",
        config={"maatlog_home_docname": "index", "maatlog_page_size": 7},
    )

    def inject(app: Sphinx, pagename: str, templatename: str, context: dict[str, Any], doctree: object) -> None:
        del app, pagename, templatename, doctree
        maatlog = context.get("maatlog")
        if not maatlog or maatlog.get("page_kind") != "home":
            return
        maatlog["featured"] = [_with_responsive(card, ImageUsage.HOME_LEAD) for card in maatlog["featured"]]
        maatlog["latest"] = [_with_responsive(card, ImageUsage.HOME_LATEST) for card in maatlog["latest"]]

    app.connect("html-page-context", inject, priority=999)
    app.build()
    managed = _managed(_read(app, "index.html"))
    assert len(managed) == 10
    assert managed[0]["fetchpriority"] == "high"
    assert sum(a.get("fetchpriority") == "high" for a in managed) == 1
    assert [a["loading"] for a in managed] == ["eager"] * 9 + ["lazy"]
    assert all(a["sizes"] != "100vw" for a in managed)


def test_archive_root_as_home_gives_lead_high(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files=_blog_files(10), theme="maatlog-default", config={"maatlog_page_size": 7})

    def inject(app: Sphinx, pagename: str, templatename: str, context: dict[str, Any], doctree: object) -> None:
        del app, pagename, templatename, doctree
        maatlog = context.get("maatlog")
        if not maatlog or maatlog.get("page_kind") != "archive":
            return
        archive: dict[str, Any] = maatlog.get("archive") or {}
        if not archive.get("is_home"):
            return
        maatlog["featured"] = [_with_responsive(card, ImageUsage.HOME_LEAD) for card in maatlog["featured"]]
        maatlog["latest"] = [_with_responsive(card, ImageUsage.HOME_LATEST) for card in maatlog["latest"]]

    app.connect("html-page-context", inject, priority=999)
    app.build()
    managed = _managed(_read(app, "blog.html"))
    assert len(managed) == 7
    assert managed[0]["fetchpriority"] == "high"
    assert sum(a.get("fetchpriority") == "high" for a in managed) == 1
    assert [a["loading"] for a in managed] == ["eager"] * 7


def test_archive_first_six_eager_seventh_lazy(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files=_blog_files(7),
        theme="maatlog-default",
        config={"maatlog_home_docname": "index"},
    )

    def inject(app: Sphinx, pagename: str, templatename: str, context: dict[str, Any], doctree: object) -> None:
        del app, pagename, templatename, doctree
        maatlog = context.get("maatlog")
        if not maatlog or maatlog.get("page_kind") != "archive":
            return
        archive: dict[str, Any] = maatlog.get("archive") or {}
        if archive.get("is_home"):
            return
        maatlog["posts"] = [_with_responsive(card, ImageUsage.ARCHIVE_CARD) for card in maatlog["posts"]]

    app.connect("html-page-context", inject, priority=999)
    app.build()
    managed = _managed(_read(app, "blog.html"))
    assert len(managed) == 7
    assert [a["loading"] for a in managed] == ["eager"] * 6 + ["lazy"]
    assert all(a.get("fetchpriority") != "high" for a in managed)
    assert all(a["sizes"] != "100vw" for a in managed)


def test_legacy_featured_has_no_high(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files=_blog_files(7),
        theme="maatlog-default",
        config={"maatlog_home_docname": "index"},
    )

    def inject(app: Sphinx, pagename: str, templatename: str, context: dict[str, Any], doctree: object) -> None:
        del app, templatename, doctree
        maatlog = context.get("maatlog")
        if not maatlog or maatlog.get("page_kind") != "archive":
            return
        archive: dict[str, Any] = maatlog.get("archive") or {}
        if archive.get("is_home"):
            return
        maatlog["posts"] = [_with_responsive(card, ImageUsage.ARCHIVE_CARD) for card in maatlog["posts"]]
        if pagename == "blog":
            context["featured_count"] = 2

    app.connect("html-page-context", inject, priority=999)
    app.build()
    managed = _managed(_read(app, "blog.html"))
    assert len(managed) == 7
    assert all(a.get("fetchpriority") != "high" for a in managed)
    assert len({_norm(a["sizes"]) for a in managed}) >= 2
    assert all(a["sizes"] != "100vw" for a in managed)


def test_profile_cards_are_standalone_without_high(make_sphinx: SphinxFactory) -> None:
    files: dict[str, str] = {
        "index.rst": "Example Blog\n============\n\nWelcome.\n",
        "one.md": """---
maatlog-post: true
maatlog-slug: one
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-authors: [alice]
---
# One

First post.
""",
        "two.md": """---
maatlog-post: true
maatlog-slug: two
maatlog-published-at: 2026-07-30T09:00:00Z
maatlog-authors: [alice]
---
# Two

Second post.
""",
    }
    app = make_sphinx(
        files=files,
        theme="maatlog-default",
        config={"maatlog_authors": {"alice": "Alice"}, "maatlog_author_profiles": {"alice": {"role": "Editor"}}},
    )

    def inject(app: Sphinx, pagename: str, templatename: str, context: dict[str, Any], doctree: object) -> None:
        del app, pagename, templatename, doctree
        maatlog = context.get("maatlog")
        if not maatlog or maatlog.get("page_kind") != "profile":
            return
        maatlog["posts"] = [_with_responsive(card, ImageUsage.ARCHIVE_CARD) for card in maatlog["posts"]]

    app.connect("html-page-context", inject, priority=999)
    app.build()
    managed = _managed(_read(app, "blog/author/alice.html"))
    assert len(managed) == 2
    assert all(a["sizes"] == "100vw" for a in managed)
    assert all(a["loading"] == "eager" for a in managed)
    assert all(a.get("fetchpriority") != "high" for a in managed)


def test_imageless_lead_renders_no_img_and_no_high(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files=_blog_files(10),
        theme="maatlog-default",
        config={"maatlog_home_docname": "index", "maatlog_page_size": 7},
    )

    def inject(app: Sphinx, pagename: str, templatename: str, context: dict[str, Any], doctree: object) -> None:
        del app, pagename, templatename, doctree
        maatlog = context.get("maatlog")
        if not maatlog or maatlog.get("page_kind") != "home":
            return
        featured = list(maatlog["featured"])
        maatlog["featured"] = [featured[0]] + [_with_responsive(card, ImageUsage.HOME_LEAD) for card in featured[1:]]
        maatlog["latest"] = [_with_responsive(card, ImageUsage.HOME_LATEST) for card in maatlog["latest"]]

    app.connect("html-page-context", inject, priority=999)
    app.build()
    managed = _managed(_read(app, "index.html"))
    assert len(managed) == 9
    assert all(a.get("fetchpriority") != "high" for a in managed)


def test_top_fallback_keeps_single_src(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files=POST_FILES, theme="maatlog-default")

    def inject(app: Sphinx, pagename: str, templatename: str, context: dict[str, Any], doctree: object) -> None:
        del app, pagename, templatename, doctree
        if context.get("maatlog") and context["maatlog"].get("post"):
            post = context["maatlog"]["post"]
            post.update(
                image_url="old.png",
                top_image_url="top.png",
                top_image_alt="Top caption",
                responsive_image=asdict(sample_responsive_image_view()),
            )

    app.connect("html-page-context", inject, priority=999)
    app.build()
    attrs = img_attrs(_read(app, "post.html"))
    managed = [a for a in attrs if a.get("data-maatlog-srcset") == "w-v1"]
    assert len(managed) == 1
    assert managed[0].get("fetchpriority") != "high"
    top = [a for a in attrs if "maatlog-post-top-image-img" in a.get("class", "")]
    assert len(top) == 1
    assert top[0]["src"] == "top.png"
    assert "srcset" not in top[0]
    assert "sizes" not in top[0]


def test_representative_only_is_high(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files=POST_FILES, theme="maatlog-default")

    def inject(app: Sphinx, pagename: str, templatename: str, context: dict[str, Any], doctree: object) -> None:
        del app, pagename, templatename, doctree
        if context.get("maatlog") and context["maatlog"].get("post"):
            post = context["maatlog"]["post"]
            post.update(image_url="old.png", responsive_image=asdict(sample_responsive_image_view()))

    app.connect("html-page-context", inject, priority=999)
    app.build()
    html = _read(app, "post.html")
    managed = _managed(html)
    assert len(managed) == 1
    assert managed[0]["fetchpriority"] == "high"
    assert managed[0]["loading"] == "eager"
    assert "post-top-image-img" not in html


def test_no_images_render_no_managed(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files=POST_FILES, theme="maatlog-default")
    app.build()
    html = _read(app, "post.html")
    assert _managed(html) == []
    assert "post-top-image-img" not in html
    assert "post-hero-image" not in html


def test_base_policy_stays_100vw_and_default_is_detailed(make_sphinx: SphinxFactory) -> None:
    base = make_sphinx(files={"index.rst": "Index\n=====\n"}, theme="maatlog-base")
    source = (
        "{% from 'maatlog/components/image-policy.html' import image_sizes with context %}"
        "{{ image_sizes(usage, presentation, has_rail, featured_count) }}"
    )
    for presentation in ("post", "lead", "secondary", "archive", "latest", "standalone"):
        sizes = base.builder.templates.render_string(
            source,
            {"usage": "archive-card", "presentation": presentation, "has_rail": True, "featured_count": 3},
        )
        assert sizes == "100vw"
    default = make_sphinx(files={"index.rst": "Index\n=====\n"}, theme="maatlog-default")
    templates = default.builder.templates
    post_sizes = _norm(
        templates.render_string(
            source,
            {"usage": "post-representative", "presentation": "post", "has_rail": True, "featured_count": 0},
        )
    )
    assert post_sizes != "100vw"
    assert "calc(" in post_sizes
    assert "(width <= 48rem)" in post_sizes
    standalone_sizes = templates.render_string(
        source,
        {"usage": "post-representative", "presentation": "post", "has_rail": None, "featured_count": 0},
    )
    assert standalone_sizes == "100vw"


OVERRIDE_POLICY = """\
{% macro image_sizes(usage, presentation='standalone', has_rail=none, featured_count=0) -%}
{{ '321px' if usage == 'post-top' else '123px' }}{%- endmacro %}
{% macro image_loading(usage, early=true) -%}eager{%- endmacro %}
{% macro image_fetchpriority(usage, high=false) -%}auto{%- endmacro %}
"""

HOSTILE_SIZES_POLICY = """\
{% macro image_sizes(usage, presentation='standalone', has_rail=none, featured_count=0) -%}
123px" onload="bad{%- endmacro %}
{% macro image_loading(usage, early=true) -%}eager{%- endmacro %}
{% macro image_fetchpriority(usage, high=false) -%}auto{%- endmacro %}
"""


def _override_prefix(theme_dir: Path) -> str:
    return f"def setup(app):\n    app.add_html_theme('override-policy', {str(theme_dir)!r})\n"


def _write_override_theme(root: Path, policy_source: str) -> Path:
    theme_dir = root / "override-policy"
    (theme_dir / "maatlog" / "components").mkdir(parents=True)
    (theme_dir / "theme.conf").write_text("[theme]\ninherit = maatlog-default\nstylesheet = maatlog.css\n")
    (theme_dir / "maatlog-theme.toml").write_text('[maatlog]\napi = "1.0"\nimplementation = "inherits-base"\n')
    (theme_dir / "static").mkdir(exist_ok=True)
    (theme_dir / "static" / "maatlog.css").write_text(":root {\n  --maatlog-color-link: #006644;\n}\n")
    (theme_dir / "maatlog" / "components" / "image-policy.html").write_text(policy_source)
    return theme_dir


def test_third_party_policy_override_applies_to_dom(make_sphinx: SphinxFactory, tmp_path: Path) -> None:
    theme_dir = _write_override_theme(tmp_path / "themes", OVERRIDE_POLICY)
    app = make_sphinx(files=POST_FILES, theme="override-policy", conf_py_prefix=_override_prefix(theme_dir))

    def inject(app: Sphinx, pagename: str, templatename: str, context: dict[str, Any], doctree: object) -> None:
        del app, pagename, templatename, doctree
        if context.get("maatlog") and context["maatlog"].get("post"):
            post = context["maatlog"]["post"]
            post.update(
                image_url="old.png",
                top_image_url="top.png",
                top_image_alt="Top caption",
                responsive_image=asdict(sample_responsive_image_view()),
                responsive_top_image=asdict(sample_responsive_image_view(ImageUsage.POST_TOP)),
            )

    app.connect("html-page-context", inject, priority=999)
    app.build()
    attrs = img_attrs(_read(app, "post.html"))
    managed = [a for a in attrs if a.get("data-maatlog-srcset") == "w-v1"]
    assert len(managed) == 2
    by_class = {a.get("class", ""): a for a in managed}
    assert by_class["maatlog-post-top-image-img"]["sizes"] == "321px"
    assert by_class["maatlog-post-hero-image"]["sizes"] == "123px"
    assert all(a["loading"] == "eager" for a in managed)
    assert all(a["fetchpriority"] == "auto" for a in managed)


def test_hostile_override_output_is_escaped(make_sphinx: SphinxFactory, tmp_path: Path) -> None:
    theme_dir = _write_override_theme(tmp_path / "themes", HOSTILE_SIZES_POLICY)
    app = make_sphinx(files=POST_FILES, theme="override-policy", conf_py_prefix=_override_prefix(theme_dir))

    def inject(app: Sphinx, pagename: str, templatename: str, context: dict[str, Any], doctree: object) -> None:
        del app, pagename, templatename, doctree
        if context.get("maatlog") and context["maatlog"].get("post"):
            post = context["maatlog"]["post"]
            post.update(image_url="old.png", responsive_image=asdict(sample_responsive_image_view()))

    app.connect("html-page-context", inject, priority=999)
    app.build()
    html = _read(app, "post.html")
    (attrs,) = _managed(html)
    assert attrs["sizes"] == '123px" onload="bad'
    assert "onload" not in attrs
    assert 'onload="bad' not in html
