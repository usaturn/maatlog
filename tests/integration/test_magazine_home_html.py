"""Magazine Home markup (Issue #179). Component tests render maatlog-base Jinja directly."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup, Tag
from conftest import ProjectFactory
from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

import maatlog
from maatlog.extension import maatlog_json
from maatlog.views import PostCardView, PostTaxonomiesView, TaxonomyLinkView

BASE_THEME = Path(maatlog.__file__).parent / "themes" / "maatlog-base"
PUBLISHED = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)


def _env() -> SandboxedEnvironment:
    environment = SandboxedEnvironment(loader=FileSystemLoader(str(BASE_THEME)))
    environment.filters["maatlog_json"] = maatlog_json
    return environment


def render_template(name: str, **kwargs: object) -> BeautifulSoup:
    html = _env().get_template(name).render(**kwargs)
    return BeautifulSoup(html, "html.parser")


def render_card(**kwargs: object) -> BeautifulSoup:
    return render_template("maatlog/components/post-card.html", **kwargs)


def render_grid(**kwargs: object) -> BeautifulSoup:
    return render_template("maatlog/components/post-grid.html", **kwargs)


def make_card(
    slug: str,
    *,
    title: str | None = None,
    image_url: str | None = None,
    excerpt: str | None = "Excerpt",
    category: str | None = "engineering",
    tag: str | None = "sphinx",
    author: str | None = "alice",
) -> PostCardView:
    def links(kind: str, value: str | None) -> tuple[TaxonomyLinkView, ...]:
        if not value:
            return ()
        return (TaxonomyLinkView(id=value, label=value, url=f"blog/{kind}/{value}.html"),)

    return PostCardView(
        title=title or slug,
        page_url=f"{slug}.html",
        published_at=PUBLISHED,
        excerpt=excerpt,
        image_url=image_url,
        tags=(tag,) if tag else (),
        categories=(category,) if category else (),
        authors=(author,) if author else (),
        external_url=None,
        slug=slug,
        taxonomies=PostTaxonomiesView(
            tags=links("tag", tag),
            categories=links("category", category),
            authors=links("author", author),
        ),
    )


def _direct_child_classes(article: Tag) -> list[str]:
    classes: list[str] = []
    for child in article.children:
        if not isinstance(child, Tag):
            continue
        class_list = child.get("class")
        if isinstance(class_list, list) and class_list:
            classes.append(str(class_list[0]))
        else:
            classes.append(child.name or "")
    return classes


def test_lead_card_exposes_variant_classes_and_home_order() -> None:
    card = make_card("lead", image_url="hero.png")
    soup = render_card(card=card, card_variant="lead", card_anchor=card.slug)
    article = soup.select_one("article")
    assert article is not None
    class_names = article.get("class")
    assert class_names is not None
    assert "maatlog-post-card" in class_names
    assert "maatlog-post-card-featured" in class_names
    assert "maatlog-post-card-lead" in class_names
    assert article["data-maatlog-card-variant"] == "lead"
    assert article["id"] == "maatlog-post-lead"
    assert _direct_child_classes(article) == [
        "maatlog-post-card-image",
        "maatlog-post-card-eyebrow",
        "maatlog-post-card-title",
        "maatlog-post-card-excerpt",
        "maatlog-post-card-meta",
        "maatlog-post-card-authors",
    ]
    assert article.select_one(".maatlog-post-card-eyebrow .maatlog-post-card-categories") is not None
    image = article.select_one("img.maatlog-post-card-image")
    assert image is not None
    assert image["alt"] == ""
    assert article.select_one("h1") is None
    title_links = article.select("h2.maatlog-post-card-title a")
    assert len(title_links) == 1
    assert article.select_one("a.maatlog-taxonomy-link") is not None
    assert article.parent is not None
    assert soup.select_one("a > article") is None


def test_secondary_and_latest_variants_do_not_reuse_the_old_featured_only_class_set() -> None:
    secondary = render_card(card=make_card("two"), card_variant="secondary").select_one("article")
    latest = render_card(card=make_card("three"), card_variant="latest").select_one("article")
    assert secondary is not None and latest is not None
    assert "maatlog-post-card-secondary" in secondary["class"]
    assert "maatlog-post-card-featured" in secondary["class"]
    assert secondary["data-maatlog-card-variant"] == "secondary"
    assert "maatlog-post-card-featured" not in latest["class"]
    assert "maatlog-post-card-lead" not in latest["class"]
    assert latest["data-maatlog-card-variant"] == "latest"


def test_legacy_featured_variant_keeps_the_archive_internal_order() -> None:
    card = make_card("old", image_url="card.png")
    article = render_card(card=card, card_variant="featured").select_one("article")
    assert article is not None
    assert article["class"] == ["maatlog-post-card", "maatlog-post-card-featured"]
    assert article["data-maatlog-card-variant"] == "featured"
    assert _direct_child_classes(article) == [
        "maatlog-post-card-image",
        "maatlog-post-card-title",
        "maatlog-post-card-date",
        "maatlog-post-card-excerpt",
        "maatlog-post-card-meta",
    ]
    assert article.select_one(".maatlog-post-card-eyebrow") is None
    assert article.select_one(".maatlog-post-card-meta .maatlog-post-card-categories") is not None


def test_home_card_omits_image_and_excerpt_instead_of_placeholders() -> None:
    card = make_card("plain", image_url=None, excerpt=None, category=None, tag=None, author=None)
    article = render_card(card=card, card_variant="lead").select_one("article")
    assert article is not None
    assert article.select_one("img") is None
    assert "placeholder" not in str(article).lower()
    assert article.select_one(".maatlog-post-card-excerpt") is None
    assert article.select_one(".maatlog-post-card-eyebrow") is None


def test_home_card_escapes_untrusted_title_and_slug() -> None:
    card = make_card('"><script>x</script>', title="Title<script>x</script>")
    html = str(render_card(card=card, card_variant="latest", card_anchor=card.slug))
    assert "<script>" not in html
    assert "Title&lt;script&gt;x&lt;/script&gt;" in html


def test_split_vars_render_featured_then_latest_without_reading_cards() -> None:
    featured = (make_card("old"), make_card("p0"), make_card("p1"))
    latest = (make_card("p2"),)
    soup = render_grid(
        featured_cards=featured,
        latest_cards=latest,
        latest_heading="Latest articles",
    )
    featured_slugs = [tag["data-slug"] for tag in soup.select(".maatlog-post-featured .maatlog-post-card")]
    latest_slugs = [tag["data-slug"] for tag in soup.select(".maatlog-post-grid .maatlog-post-card")]
    assert featured_slugs == ["old", "p0", "p1"]
    assert latest_slugs == ["p2"]
    assert soup.select_one('.maatlog-post-featured[data-maatlog-component="featured"]') is not None
    assert soup.select_one('.maatlog-post-grid[data-maatlog-component="latest"]') is not None
    heading = soup.select_one("h2.maatlog-post-list-heading")
    assert heading is not None
    assert heading.text.strip() == "Latest articles"
    variants = [tag["data-maatlog-card-variant"] for tag in soup.select(".maatlog-post-card")]
    assert variants == ["lead", "secondary", "secondary", "latest"]


def test_split_vars_omit_featured_or_heading_when_empty() -> None:
    only_latest = render_grid(featured_cards=(), latest_cards=(make_card("p0"),), latest_heading="Latest articles")
    assert only_latest.select_one(".maatlog-post-featured") is None
    assert only_latest.select_one("h2.maatlog-post-list-heading") is not None
    only_featured = render_grid(featured_cards=(make_card("p0"),), latest_cards=(), latest_heading="Latest articles")
    assert only_featured.select_one(".maatlog-post-featured") is not None
    assert only_featured.select_one("h2.maatlog-post-list-heading") is None
    assert only_featured.select_one(".maatlog-post-grid") is None
    empty = render_grid(featured_cards=(), latest_cards=())
    assert empty.select_one(".maatlog-archive-empty") is not None


def test_cards_only_path_does_not_look_like_home_latest() -> None:
    soup = render_grid(cards=(make_card("a"), make_card("b")))
    assert soup.select_one(".maatlog-post-featured") is None
    assert soup.select_one("h2.maatlog-post-list-heading") is None
    assert soup.select_one('.maatlog-post-grid[data-maatlog-component="latest"]') is None
    assert soup.select_one("[data-maatlog-card-variant]") is None
    assert len(soup.select(".maatlog-post-grid .maatlog-post-card")) == 2


def test_legacy_featured_count_path_still_slices_cards() -> None:
    cards = tuple(make_card(f"p{i}") for i in range(4))
    soup = render_grid(cards=cards, featured_count=3)
    assert len(soup.select(".maatlog-post-featured .maatlog-post-card")) == 3
    older_heading = soup.select_one("h2.maatlog-post-list-heading")
    assert older_heading is not None
    assert older_heading.text.strip() == "Older posts"
    assert soup.select(".maatlog-post-featured .maatlog-post-card")[0]["data-maatlog-card-variant"] == "featured"


HOME_FILES: Mapping[str, str] = {
    "index.rst": "Example Blog\n============\n\nWelcome to the blog.\n",
    **{
        f"post{n}.md": f"""---
maatlog-post: true
maatlog-slug: post{n}
maatlog-published-at: 2026-07-2{n}T09:00:00Z
maatlog-tags: [sphinx]
---
# Post {n}

Body {n}.
"""
        for n in (1, 2, 3, 4, 5)
    },
}


def test_dedicated_home_reads_featured_and_latest_keys(make_project: ProjectFactory) -> None:
    result = make_project(
        files=HOME_FILES,
        config={
            "maatlog_home_docname": "index",
            "project": "Example Blog",
            "maatlog_tagline": "Notes",
            "maatlog_page_size": 1,
        },
    ).build()
    home = BeautifulSoup(result.html("index.html").text, "html.parser")
    featured = home.select(".maatlog-post-featured .maatlog-post-card")
    latest = home.select(".maatlog-post-grid .maatlog-post-card")
    assert [tag["data-slug"] for tag in featured] == ["post5", "post4", "post3"]
    assert [tag["data-slug"] for tag in latest] == ["post2"]
    assert "maatlog-post-card-lead" in featured[0]["class"]
    assert "maatlog-post-card-secondary" in featured[1]["class"]
    assert featured[0]["data-maatlog-card-variant"] == "lead"
    assert latest[0]["data-maatlog-card-variant"] == "latest"
    latest_heading = home.select_one("h2.maatlog-post-list-heading")
    assert latest_heading is not None
    assert latest_heading.text.strip() == "Latest articles"
    html = str(home)
    assert html.index("Example Blog") < html.index("maatlog-post-featured")
    assert html.index("Welcome to the blog.") < html.index("maatlog-post-featured")
    assert html.index("maatlog-home-intro") < html.index("maatlog-post-featured")
    assert home.select_one("h1.maatlog-hero-title") is not None
    assert home.select_one(".maatlog-post-featured h1") is None
    archive_link = home.select_one(".maatlog-home-archive-link")
    assert archive_link is not None
    assert archive_link["href"] == "blog.html"


def test_archive_home_uses_latest_articles_heading(make_project: ProjectFactory) -> None:
    files = {name: body for name, body in HOME_FILES.items() if name != "index.rst"}
    result = make_project(files=files, config={"project": "Example Blog"}).build()
    page = BeautifulSoup(result.html("blog.html").text, "html.parser")
    archive_heading = page.select_one("h2.maatlog-post-list-heading")
    assert archive_heading is not None
    assert archive_heading.text.strip() == "Latest articles"
    assert "maatlog-post-card-lead" in page.select(".maatlog-post-featured .maatlog-post-card")[0]["class"]
    tag_page = BeautifulSoup(result.html("blog/tag/sphinx.html").text, "html.parser")
    assert tag_page.select_one(".maatlog-post-featured") is None
    assert tag_page.select_one("h2.maatlog-post-list-heading") is None
    assert tag_page.select_one("[data-maatlog-card-variant]") is None


def _base_css() -> str:
    return (BASE_THEME / "static" / "maatlog.css").read_text(encoding="utf-8")


def _css_rule(css: str, selector: str) -> str:
    start = css.index(f"{selector} {{")
    return css[start : css.index("}", start) + 1]


def test_home_taxonomy_links_stay_above_the_stretched_link() -> None:
    css = _base_css()
    for selector in (
        ".maatlog-post-card-categories a",
        ".maatlog-post-card-authors a",
        ".maatlog-post-card-meta a",
    ):
        rule = _css_rule(css, selector)
        assert "position: relative" in rule
        assert "z-index: 1" in rule


def test_home_that_is_the_only_post_still_has_no_empty_copy(make_project: ProjectFactory) -> None:
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
    built = make_project(
        files=files,
        config={"maatlog_home_docname": "only", "project": "Example Blog"},
    ).build()
    home = BeautifulSoup(built.html("only.html").text, "html.parser")
    assert home.select_one(".maatlog-post-card") is None
    assert home.select_one(".maatlog-archive-empty") is None


def test_archive_pagination_keeps_older_posts_link(make_project: ProjectFactory) -> None:
    files = {name: body for name, body in HOME_FILES.items() if name != "index.rst"}
    result = make_project(files=files, config={"maatlog_page_size": 2}).build()
    page1 = BeautifulSoup(result.html("blog.html").text, "html.parser")
    more = page1.select_one("a.maatlog-pagination-more")
    assert more is not None
    assert more.text.strip() == "Older posts"
    assert page1.select_one(".maatlog-post-featured") is not None
    page2 = BeautifulSoup(result.html("blog/page/2.html").text, "html.parser")
    assert page2.select_one(".maatlog-post-featured") is None
    assert page2.select_one("[data-maatlog-card-variant]") is None
