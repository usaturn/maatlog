"""Scroll fixture for responsive-image Infinite Scroll tests (issue #216, Task 3).

Builds a minimal three-page archive that reproduces the DOM shape
``maatlog.js`` expects (see ``tests/acceptance/test_infinite_scroll.py`` and
``maatlog-base/maatlog/components/pagination.html``). The pages load the real
``maatlog-base`` runtime so append behaviour is exercised, not mocked.
"""

from __future__ import annotations

import html
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TypedDict, cast
from urllib.parse import unquote

from fixtures.responsive_image_fixtures import (
    make_test_png,
    sample_responsive_image_entry,
    sample_responsive_image_view,
)

from maatlog.image_contracts import ImageUsage, ResponsiveImageEntry, scaled_height

if TYPE_CHECKING:
    from playwright.sync_api import Page, Response
    from sphinx.application import Sphinx

_BASE_STATIC = Path(__file__).resolve().parents[2] / "src" / "maatlog" / "themes" / "maatlog-base" / "static"


def _tall_excerpt(repeat: int = 28) -> str:
    sentence = "Filler copy that pads this card past the fold so the sentinel starts out of view. "
    return (sentence * repeat).strip()


TALL_EXCERPT = _tall_excerpt()


def _img_html(srcset: str, marker: str | None, src: str | None) -> str:
    attrs = 'class="maatlog-post-card-image"'
    if src is not None:
        attrs += f' src="{html.escape(src, quote=True)}"'
    attrs += f' srcset="{html.escape(srcset, quote=True)}"'
    attrs += ' sizes="100vw" width="1600" height="900" alt="" loading="eager"'
    attrs += ' fetchpriority="high" decoding="async"'
    if marker is not None:
        attrs += f' data-maatlog-srcset="{html.escape(marker, quote=True)}"'
    return f"<img {attrs}>"


def _source_html(srcset: str, marker: str | None) -> str:
    # A managed-looking source sibling: the runtime must leave <source>
    # untouched even when the grammar would be valid for an <img>.
    attrs = f'srcset="{html.escape(srcset, quote=True)}"'
    if marker is not None:
        attrs += f' data-maatlog-srcset="{html.escape(marker, quote=True)}"'
    return f"<source {attrs}>"


def _card_html(slug: str, title: str, srcset: str, marker: str | None, src: str | None) -> str:
    return (
        '<article class="maatlog-post-card" data-maatlog-component="post-card"'
        f' data-slug="{html.escape(slug, quote=True)}">'
        f"<picture>{_source_html(srcset, marker)}{_img_html(srcset, marker, src)}</picture>"
        f'<h2 class="maatlog-post-card-title"><a href="#{html.escape(slug, quote=True)}">'
        f"{html.escape(title)}</a></h2>"
        f'<p class="maatlog-post-card-excerpt">{html.escape(TALL_EXCERPT)}</p>'
        "</article>"
    )


def _nav_html(
    *,
    prev_href: str | None,
    pages: list[tuple[int, str | None]],
    next_href: str | None,
    root_img: str | None = None,
) -> str:
    parts = ['<nav class="maatlog-pagination" data-maatlog-component="pagination" aria-label="Pagination">']
    if prev_href is not None:
        parts.append(
            f'<a class="maatlog-pagination-prev" href="{html.escape(prev_href, quote=True)}" rel="prev">Previous</a>'
        )
    for number, href in pages:
        if href is None:
            parts.append(f'<span class="maatlog-pagination-current" aria-current="page">{number}</span>')
        else:
            parts.append(f'<a class="maatlog-pagination-page" href="{html.escape(href, quote=True)}">{number}</a>')
    if next_href is not None:
        escaped = html.escape(next_href, quote=True)
        parts.append(f'<a class="maatlog-pagination-next" href="{escaped}" rel="next">Next</a>')
        parts.append(f'<a class="maatlog-pagination-more" href="{escaped}" rel="next">Older posts</a>')
    if root_img is not None:
        parts.append(root_img)
    parts.append("</nav>")
    return "".join(parts)


def _page_html(title: str, cards: str, nav: str) -> str:
    return (
        "<!doctype html>"
        '<html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title>"
        '<link rel="stylesheet" href="/_static/maatlog.css">'
        '<script src="/_static/maatlog.js"></script>'
        "</head><body>"
        '<section class="maatlog-archive" data-maatlog-component="archive">'
        '<div class="maatlog-post-list"><div class="maatlog-post-grid">'
        f"{cards}</div></div>{nav}</section></body></html>"
    )


def _candidate_urls(srcset: str, src: str | None) -> list[str]:
    urls: list[str] = []
    for part in srcset.split(","):
        tokens = part.strip().split()
        if tokens:
            urls.append(tokens[0])
    if src is not None:
        urls.append(src)
    return urls


def _is_local(url: str) -> bool:
    if url == "":
        return False
    if url.startswith(("#", "/", "data:", "blob:", "javascript:", "mailto:", "tel:")):
        # Root-absolute ("/...") images are out of scope for this fixture;
        # every case in the table uses document-relative URLs or absolute http(s).
        return False
    if "://" in url:
        return False
    lower = url.lower()
    for scheme in ("http:", "https:", "data:", "blob:", "javascript:", "mailto:", "tel:"):
        if lower.startswith(scheme):
            return False
    return True


def _write_local_images(root: Path, page_dirs: list[Path], srcset: str, src: str | None) -> None:
    payload = make_test_png(64, 36)
    seen: set[str] = set()
    for raw_url in _candidate_urls(srcset, src):
        if not _is_local(raw_url):
            continue
        path_part = raw_url.split("#", 1)[0].split("?", 1)[0]
        if path_part == "":
            continue
        decoded = unquote(path_part)
        if decoded == "":
            continue
        for page_dir in page_dirs:
            target = (page_dir / decoded).resolve()
            try:
                target.relative_to(root.resolve())
            except ValueError:
                continue
            key = str(target)
            if key in seen:
                continue
            seen.add(key)
            # Stay inside the served tree; escapes above the root are skipped.
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file():
                target.write_bytes(payload)


def write_scroll_site(
    root: Path,
    *,
    builder: str,
    srcset: str,
    marker: str | None = "w-v1",
    src: str | None = "../images/hero.png",
) -> str:
    """Write a three-page scroll fixture under *root* and return the entry URL.

    *builder* selects the on-disk layout (``"html"`` or ``"dirhtml"``).
    Page two and page three carry a managed image built from *srcset*,
    *marker* and *src*; the entry page carries a text-only card so the
    sentinel starts out of view. Images are valid PNG bytes placed where the
    relative URLs resolve after URL-decoding.
    """
    if builder not in ("html", "dirhtml"):
        msg = f"unknown builder: {builder!r}"
        raise ValueError(msg)
    static_dir = root / "_static"
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "maatlog.js").write_bytes((_BASE_STATIC / "maatlog.js").read_bytes())
    (static_dir / "maatlog.css").write_bytes((_BASE_STATIC / "maatlog.css").read_bytes())

    if builder == "html":
        entry_path = root / "nested" / "blog.html"
        page2_path = root / "nested" / "blog" / "page" / "2.html"
        page3_path = root / "nested" / "blog" / "page" / "3.html"
        entry_url = "nested/blog.html"
        entry_nav = _nav_html(
            prev_href=None,
            pages=[(1, None), (2, "blog/page/2.html"), (3, "blog/page/3.html")],
            next_href="blog/page/2.html",
        )
        page2_nav = _nav_html(
            prev_href="../../blog.html",
            pages=[(1, "../../blog.html"), (2, None), (3, "3.html")],
            next_href="3.html",
            root_img=_img_html(srcset, marker, src),
        )
        page3_nav = _nav_html(
            prev_href="2.html",
            pages=[(1, "../../blog.html"), (2, "2.html"), (3, None)],
            next_href=None,
        )
    else:
        entry_path = root / "nested" / "blog" / "index.html"
        page2_path = root / "nested" / "blog" / "page" / "2" / "index.html"
        page3_path = root / "nested" / "blog" / "page" / "3" / "index.html"
        entry_url = "nested/blog/"
        entry_nav = _nav_html(
            prev_href=None,
            pages=[(1, None), (2, "page/2/"), (3, "page/3/")],
            next_href="page/2/",
        )
        page2_nav = _nav_html(
            prev_href="../../",
            pages=[(1, "../../"), (2, None), (3, "../3/")],
            next_href="../3/",
            root_img=_img_html(srcset, marker, src),
        )
        page3_nav = _nav_html(
            prev_href="../2/",
            pages=[(1, "../../"), (2, "../2/"), (3, None)],
            next_href=None,
        )

    entry_cards = (
        '<article class="maatlog-post-card" data-maatlog-component="post-card"'
        ' data-slug="page-one">'
        '<h2 class="maatlog-post-card-title"><a href="#page-one">Page one</a></h2>'
        f'<p class="maatlog-post-card-excerpt">{html.escape(TALL_EXCERPT)}</p>'
        "</article>"
    )
    page2_cards = _card_html("page-two", "Page two", srcset, marker, src)
    page3_cards = _card_html("page-three", "Page three", srcset, marker, src)

    for path, title, cards, nav in (
        (entry_path, "Blog", entry_cards, entry_nav),
        (page2_path, "Blog page 2", page2_cards, page2_nav),
        (page3_path, "Blog page 3", page3_cards, page3_nav),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_page_html(title, cards, nav), encoding="utf-8")

    _write_local_images(root, [page2_path.parent, page3_path.parent], srcset, src)
    return entry_url


# ---------------------------------------------------------------------------
# Task 4: independent geometry/loading fixture (issue #216).
#
# Builds a real site with the responsive feature OFF (no generator
# registered) and injects sample views through a dedicated
# ``html-page-context`` callback, exactly like Task 2's integration tests.
# Candidate PNG bytes are materialised at every outdir location the built
# HTML references, so the pages serve over plain HTTP with no 404s.
# ---------------------------------------------------------------------------

WIDTHS: Final = [
    390,
    768,
    1280,
    1920,
    2560,
    3840,
    639,
    640,
    641,
    767,
    769,
    1023,
    1024,
    1025,
    575,
    576,
    577,
    815,
    816,
    817,
    1127,
    1128,
    1129,
    1223,
    1224,
    1225,
    2221,
    2222,
    2223,
    3021,
    3022,
    3023,
]

MAIN_WIDTHS: Final = [390, 768, 1280, 1920, 2560, 3840]

THIRD_PARTY_THEME: Final = "task4-override"

_POST_COUNT: Final = 12
_PORTRAIT_SLUG: Final = "post11"
_TINY_SLUG: Final = "post12"
_PROFILE_POSTS: Final = 6


class ImageRect(TypedDict):
    x: float
    y: float
    width: float
    height: float


class ImageRecord(TypedDict):
    src: str | None
    srcset: str | None
    sizes: str | None
    width_attr: str | None
    height_attr: str | None
    loading: str | None
    fetchpriority: str | None
    decoding: str | None
    marker: str | None
    slug: str | None
    css_class: str
    rect: ImageRect
    current_src: str
    natural_width: int
    natural_height: int
    complete: bool


class SlotRecord(TypedDict):
    rendered_width: float
    evaluated_sizes: float
    precision: str
    viewport_width: int


class ResponseSample(TypedDict):
    url: str
    status: int
    bytes: int


_LANDSCAPE_ENTRY = sample_responsive_image_entry()
_PORTRAIT_ENTRY = sample_responsive_image_entry(
    source_relpath="posts/img/portrait.png",
    natural_width=900,
    natural_height=1600,
    widths=(240, 480, 768, 900),
)
_TINY_ENTRY = sample_responsive_image_entry(
    source_relpath="posts/img/tiny.png",
    natural_width=240,
    natural_height=135,
    widths=(240,),
)

_OVERRIDE_POLICY: Final = """\
{% macro image_sizes(usage, presentation='standalone', has_rail=none, featured_count=0) -%}
{{ '321px' if usage == 'post-top' else '123px' }}{%- endmacro %}
{% macro image_loading(usage, early=true) -%}eager{%- endmacro %}
{% macro image_fetchpriority(usage, high=false) -%}auto{%- endmacro %}
"""


def _natural_for_slug(slug: str | None) -> tuple[int, int]:
    if slug == _PORTRAIT_SLUG:
        return (900, 1600)
    if slug == _TINY_SLUG:
        return (240, 135)
    return (1600, 900)


def _entry_for_slug(slug: str | None) -> ResponsiveImageEntry:
    if slug == _PORTRAIT_SLUG:
        return _PORTRAIT_ENTRY
    if slug == _TINY_SLUG:
        return _TINY_ENTRY
    return _LANDSCAPE_ENTRY


def _png_registry() -> dict[str, tuple[int, int]]:
    """Map every referenced image basename to its deterministic PNG size."""
    registry: dict[str, tuple[int, int]] = {}
    for entry in (_LANDSCAPE_ENTRY, _PORTRAIT_ENTRY, _TINY_ENTRY):
        view = sample_responsive_image_view(entry=entry)
        for candidate in view.candidates:
            registry[candidate.url.rsplit("/", 1)[-1]] = (
                candidate.width,
                scaled_height(
                    natural_width=entry.natural_width,
                    natural_height=entry.natural_height,
                    target_width=candidate.width,
                ),
            )
    for number in range(1, _POST_COUNT + 1):
        slug = f"post{number}"
        registry[f"{slug}-full.png"] = _natural_for_slug(slug)
        registry[f"{slug}-top.png"] = (1600, 900)
    return registry


_SIZE_REGISTRY: Final = _png_registry()

_POST_ROLES: Final = {"post1": "both", "post2": "top", "post3": "hero", "post4": "none"}


def _post_md(number: int) -> str:
    slug = f"post{number}"
    lines = [
        "---",
        "maatlog-post: true",
        f"maatlog-slug: {slug}",
        f"maatlog-published-at: 2026-07-{number:02d}T09:00:00Z",
        f"maatlog-image: images/{slug}-full.png",
    ]
    if number <= _PROFILE_POSTS:
        lines.append("maatlog-authors: [alice]")
    lines.extend(["---", f"# Post {number}", "", f"Body of {slug}.", ""])
    return "\n".join(lines)


def _site_files(post_count: int = _POST_COUNT) -> dict[str, str | bytes]:
    files: dict[str, str | bytes] = {"index.rst": "Example Blog\n============\n\nWelcome to the photo blog.\n"}
    for number in range(1, post_count + 1):
        slug = f"post{number}"
        files[f"{slug}.md"] = _post_md(number)
        natural_width, natural_height = _natural_for_slug(slug)
        files[f"images/{slug}-full.png"] = make_test_png(natural_width, natural_height)
    files["showcase.rst"] = "Showcase\n========\n\n.. maatlog:post-list::\n   :limit: 3\n"
    return files


def _override_theme_files() -> dict[str, str]:
    return {
        "_task4_theme/maatlog/components/image-policy.html": _OVERRIDE_POLICY,
        "_task4_theme/theme.conf": "[theme]\ninherit = maatlog-default\nstylesheet = maatlog.css\n",
        "_task4_theme/maatlog-theme.toml": '[maatlog]\napi = "1.0"\nimplementation = "inherits-base"\n',
    }


def _override_conf_prefix() -> str:
    return (
        "def setup(app):\n"
        "    from pathlib import Path\n"
        "    app.add_html_theme('task4-override', str(Path(__file__).resolve().parent / '_task4_theme'))\n"
    )


def _card_list(page_map: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], page_map.get(key) or [])


def _inject_featured_latest(page_map: dict[str, Any]) -> None:
    featured = _card_list(page_map, "featured")
    page_map["featured"] = [
        _card_with_view(card, ImageUsage.HOME_LEAD if index == 0 else ImageUsage.HOME_SECONDARY)
        for index, card in enumerate(featured)
    ]
    latest_cards = _card_list(page_map, "latest")
    page_map["latest"] = [_card_with_view(card, ImageUsage.HOME_LATEST) for card in latest_cards]


def _card_with_view(card: dict[str, Any], usage: ImageUsage) -> dict[str, Any]:
    slug = card.get("slug")
    view = sample_responsive_image_view(usage, entry=_entry_for_slug(slug if isinstance(slug, str) else None))
    return {**card, "responsive_image": asdict(view)}


def build_image_site(
    make_sphinx: Callable[..., Sphinx],
    *,
    builder: str,
    theme: str,
    responsive: bool,
    featured_count: int = 3,
    has_rail: bool = True,
) -> Sphinx:
    """Build the Task 4 photo-blog site and materialise its image bytes.

    Twelve posts (``post11`` portrait, ``post12`` single-candidate tiny,
    ``post1``–``post6`` by alice for the profile page), a home page, a legacy
    archive page, four post-image role pages (top+hero / top-only / hero-only /
    none) and a ``post-list`` showcase page. ``page_size`` covers every post so
    no page 2 (and no Infinite Scroll append) can move cards across grids while
    a test measures. With *responsive* true, sample views are injected per page
    kind and card position; otherwise the build stays on single-src fallbacks.
    Returns the built Sphinx app.
    """
    return _build(
        make_sphinx,
        builder=builder,
        theme=theme,
        responsive=responsive,
        featured_count=featured_count,
        has_rail=has_rail,
        post_count=_POST_COUNT,
        page_size=_POST_COUNT,
    )


def build_archive_site(
    make_sphinx: Callable[..., Sphinx],
    *,
    builder: str,
    theme: str,
    responsive: bool,
    post_count: int,
    has_rail: bool = True,
) -> Sphinx:
    """Build a single-page plain-archive site with exactly *post_count* cards.

    Page 1 holds every post, so there is no page 2 and no Infinite Scroll
    append can move cards across grids while a test measures. Covers the
    1/2/4/9-card archive grids ``build_image_site`` cannot size.
    """
    return _build(
        make_sphinx,
        builder=builder,
        theme=theme,
        responsive=responsive,
        featured_count=0,
        has_rail=has_rail,
        post_count=post_count,
        page_size=10,
    )


def _build(
    make_sphinx: Callable[..., Sphinx],
    *,
    builder: str,
    theme: str,
    responsive: bool,
    featured_count: int,
    has_rail: bool,
    post_count: int,
    page_size: int,
) -> Sphinx:
    files = _site_files(post_count)
    config: dict[str, object] = {
        "maatlog_home_docname": "index",
        "maatlog_page_size": page_size,
        "maatlog_authors": {"alice": "Alice"},
        "maatlog_author_profiles": {"alice": {"role": "Editor"}},
        "maatlog_default_author": "alice",
    }
    if featured_count == 0:
        config["maatlog_featured_posts"] = []
    else:
        # Landscapes first: the portrait/tiny posts stay in the latest column,
        # so the lead (used by the bytes comparison) always has full-size
        # originals to downselect from.
        landscapes = [
            f"post{number}"
            for number in range(post_count, 0, -1)
            if f"post{number}" not in (_PORTRAIT_SLUG, _TINY_SLUG)
        ]
        config["maatlog_featured_posts"] = landscapes[:featured_count]
    conf_py_prefix = ""
    if theme == THIRD_PARTY_THEME:
        files.update(_override_theme_files())
        conf_py_prefix = _override_conf_prefix()
    app = make_sphinx(files=files, builder=builder, theme=theme, config=config, conf_py_prefix=conf_py_prefix)

    def inject(app: Sphinx, pagename: str, templatename: str, context: dict[str, Any], doctree: object) -> None:
        del app, templatename, doctree
        maatlog = context.get("maatlog")
        if responsive and isinstance(maatlog, dict):
            page_map = cast(dict[str, Any], maatlog)
            kind = page_map.get("page_kind")
            if kind == "home":
                _inject_featured_latest(page_map)
            elif kind == "archive":
                archive = cast(dict[str, Any], page_map.get("archive") or {})
                if archive.get("is_home"):
                    _inject_featured_latest(page_map)
                else:
                    page_map["posts"] = [
                        _card_with_view(card, ImageUsage.ARCHIVE_CARD) for card in _card_list(page_map, "posts")
                    ]
            elif kind == "profile":
                page_map["posts"] = [
                    _card_with_view(card, ImageUsage.ARCHIVE_CARD) for card in _card_list(page_map, "posts")
                ]
            elif kind == "post":
                _inject_post(page_map)
        if not has_rail:
            context["maatlog_has_toc"] = False
            context["maatlog_has_author_summary"] = False
        if featured_count > 0 and pagename == "blog":
            context["featured_count"] = featured_count

    app.connect("html-page-context", inject, priority=999)
    app.build()
    _write_referenced_images(Path(str(app.outdir)))
    return app


def _inject_post(maatlog: dict[str, Any]) -> None:
    post = maatlog.get("post")
    if not isinstance(post, dict):
        return
    post_map = cast(dict[str, Any], post)
    slug = post_map.get("slug")
    role = _POST_ROLES.get(slug, "hero") if isinstance(slug, str) else "hero"
    if role in ("both", "top") and isinstance(slug, str):
        post_map["top_image_url"] = f"images/{slug}-top.png"
        post_map["top_image_alt"] = f"Top image for {slug}"
        post_map["responsive_top_image"] = asdict(sample_responsive_image_view(ImageUsage.POST_TOP))
    if role in ("both", "hero"):
        post_map["responsive_image"] = asdict(
            sample_responsive_image_view(
                ImageUsage.POST_REPRESENTATIVE,
                entry=_entry_for_slug(slug if isinstance(slug, str) else None),
            )
        )
    if role == "none":
        post_map["image_url"] = None


class _ImgCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.images: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "img":
            self.images.append({key: value or "" for key, value in attrs})


def _write_referenced_images(outdir: Path) -> None:
    """Materialise every image URL the built HTML references.

    Files the Sphinx image pipeline already copied are left alone; candidate
    and injected-fallback URLs resolve per page and are written with the
    deterministic size from the registry. Unknown basenames fail loudly so a
    mispredicted URL can never hide as a wrong-sized file.
    """
    root = outdir.resolve()
    for html_path in sorted(root.rglob("*.html")):
        collector = _ImgCollector()
        collector.feed(html_path.read_text(encoding="utf-8"))
        for attrs in collector.images:
            urls: list[str] = []
            for part in attrs.get("srcset", "").split(","):
                tokens = part.strip().split()
                if tokens:
                    urls.append(tokens[0])
            if attrs.get("src"):
                urls.append(attrs["src"])
            for url in urls:
                _materialise_image(root, html_path.parent, url)


def _materialise_image(root: Path, page_dir: Path, url: str) -> None:
    if url == "" or url.startswith(("#", "/", "data:", "blob:", "javascript:", "mailto:", "tel:")):
        return
    if "://" in url:
        return
    path_part = url.split("#", 1)[0].split("?", 1)[0]
    if path_part == "":
        return
    target = (page_dir / unquote(path_part)).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return
    if target.is_file():
        return
    size = _SIZE_REGISTRY.get(target.name)
    if size is None:
        msg = f"Task 4 fixture has no PNG size for {target.name} (from {url})"
        raise AssertionError(msg)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(make_test_png(size[0], size[1]))


_PAGE_DOCNAMES: Final = {
    "home": "index",
    "archive": "blog",
    "profile": "blog/author/alice",
    "showcase": "showcase",
}


def site_page(builder: str, name: str) -> str:
    """Return the start path of one Task 4 fixture page for *builder*."""
    docname = _PAGE_DOCNAMES.get(name, name)
    if builder == "html":
        return "index.html" if docname == "index" else f"{docname}.html"
    if builder == "dirhtml":
        return "index.html" if docname == "index" else f"{docname}/index.html"
    msg = f"unknown builder: {builder!r}"
    raise ValueError(msg)


_MEASURE_JS: Final = """() => Array.from(document.querySelectorAll('img')).map((img) => {
  const rect = img.getBoundingClientRect();
  const host = img.closest('[data-slug]');
  return {
    src: img.getAttribute('src'),
    srcset: img.getAttribute('srcset'),
    sizes: img.getAttribute('sizes'),
    width_attr: img.getAttribute('width'),
    height_attr: img.getAttribute('height'),
    loading: img.getAttribute('loading'),
    fetchpriority: img.getAttribute('fetchpriority'),
    decoding: img.getAttribute('decoding'),
    marker: img.getAttribute('data-maatlog-srcset'),
    slug: host ? host.getAttribute('data-slug') : null,
    css_class: img.getAttribute('class') || '',
    rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
    current_src: img.currentSrc,
    natural_width: img.naturalWidth,
    natural_height: img.naturalHeight,
    complete: img.complete,
  };
})"""

_EVALUATE_SIZES_JS: Final = """(sizes) => {
  const parts = [];
  let depth = 0, current = '';
  for (const ch of sizes) {
    if (ch === '(') depth += 1;
    else if (ch === ')') depth -= 1;
    if (ch === ',' && depth === 0) { parts.push(current); current = ''; }
    else { current += ch; }
  }
  parts.push(current);
  let selected = parts[parts.length - 1].trim();
  for (const part of parts.slice(0, -1)) {
    const text = part.trim();
    if (!text.startsWith('(')) continue;
    let level = 0, end = -1;
    for (let i = 0; i < text.length; i++) {
      if (text[i] === '(') level += 1;
      else if (text[i] === ')') {
        level -= 1;
        if (level === 0) { end = i; break; }
      }
    }
    if (end < 0) continue;
    if (window.matchMedia(text.slice(0, end + 1)).matches) {
      selected = text.slice(end + 1).trim();
      break;
    }
  }
  const probe = document.createElement('div');
  probe.setAttribute('aria-hidden', 'true');
  probe.style.cssText = 'position:fixed;top:0;left:0;height:0;visibility:hidden;pointer-events:none;';
  probe.style.width = selected;
  document.body.appendChild(probe);
  const width = probe.getBoundingClientRect().width;
  probe.remove();
  return {length: selected, width: width};
}"""


def measure_images(page: Page) -> list[ImageRecord]:
    """Collect attributes, DOMRect and currentSrc for every ``<img>`` in document order.

    Note: for ``srcset`` images Chromium reports density-corrected
    ``naturalWidth``/``naturalHeight`` (file pixels divided by the selected
    density), so compare ratios — not absolute values — with file geometry.
    """
    raw = page.evaluate(_MEASURE_JS)
    records: list[ImageRecord] = []
    for entry in raw:
        records.append(
            ImageRecord(
                src=entry["src"],
                srcset=entry["srcset"],
                sizes=entry["sizes"],
                width_attr=entry["width_attr"],
                height_attr=entry["height_attr"],
                loading=entry["loading"],
                fetchpriority=entry["fetchpriority"],
                decoding=entry["decoding"],
                marker=entry["marker"],
                slug=entry["slug"],
                css_class=entry["css_class"],
                rect=ImageRect(
                    x=float(entry["rect"]["x"]),
                    y=float(entry["rect"]["y"]),
                    width=float(entry["rect"]["width"]),
                    height=float(entry["rect"]["height"]),
                ),
                current_src=str(entry["current_src"]),
                natural_width=int(entry["natural_width"]),
                natural_height=int(entry["natural_height"]),
                complete=bool(entry["complete"]),
            )
        )
    return records


def evaluate_sizes(page: Page, sizes: str) -> tuple[str, float]:
    """Evaluate a ``sizes`` value against the real CSS.

    Splits only on depth-0 commas (never inside ``min()``/``clamp()``),
    matches the first media condition with ``matchMedia`` and reads the
    chosen length through a hidden probe ``div`` that is removed at once.
    Returns the selected length and its pixel width.
    """
    result = page.evaluate(_EVALUATE_SIZES_JS, sizes)
    return (str(result["length"]), float(result["width"]))


def assert_slot(record: SlotRecord) -> None:
    """The brief's slot gate: exact layouts match, fallbacks stay conservative."""
    actual = record["rendered_width"]
    slot = record["evaluated_sizes"]
    if record["precision"] == "exact":
        assert abs(slot - actual) <= max(2, actual * 0.01)
    else:
        assert 0 < actual <= slot + 2
        assert slot <= record["viewport_width"] + 2


def collect_image_responses(page: Page, samples: list[ResponseSample]) -> None:
    """Record every image response; ``body()`` failures propagate, never swallowed."""

    def _on_response(response: Response) -> None:
        if response.request.resource_type == "image":
            samples.append({"url": response.url, "status": response.status, "bytes": len(response.body())})

    page.on("response", _on_response)


def decode_all_images(page: Page) -> None:
    """Scroll every image into view and wait until each reports complete."""
    page.evaluate("""async () => {
      const imgs = Array.from(document.querySelectorAll('img'));
      for (const img of imgs) {
        img.scrollIntoView({block: 'nearest'});
        if (!(img.complete && img.naturalWidth > 0)) {
          await img.decode().catch(() => {});
        }
      }
      window.scrollTo(0, 0);
    }""")
    page.wait_for_function(
        "() => Array.from(document.querySelectorAll('img')).every((img) => img.complete)",
        timeout=15000,
    )


def write_observations(path: Path, records: Sequence[Mapping[str, object]]) -> Path:
    """Write observation records to *path* as pretty-printed JSON."""
    path.write_text(json.dumps(records, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path
