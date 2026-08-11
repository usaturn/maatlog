"""Acceptance helpers: build the fixed project and assert public surfaces."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

import pytest
from sphinx.application import Sphinx
from sphinx.errors import SphinxError

from maatlog.domain import MaatlogDomain
from maatlog.errors import MaatlogBuildError
from maatlog.feeds import ATOM
from maatlog.model import Post

if TYPE_CHECKING:
    # Bare ``conftest`` is ambiguous next to ``acceptance.conftest`` for the type checker.
    @dataclass(frozen=True)
    class HtmlPage:
        text: str

        def select_one(self, selector: str) -> dict[str, str] | None: ...

        def select(self, selector: str) -> list[dict[str, str]]: ...

        def __contains__(self, item: object) -> bool: ...
else:
    from conftest import HtmlPage

PROJECT_ROOT = Path(__file__).resolve().parent / "project"
# 2026-08-15T00:00:00Z — after August posts, after expiry of the expired fixture.
DEFAULT_SOURCE_DATE_EPOCH = "1786752000"

_IDENTITY_FIELDS = frozenset({"docname", "source_path", "slug"})


class _HrefCollector(HTMLParser):
    """Collect href values from anchor and link tags."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"a", "link"}:
            return
        for name, value in attrs:
            if name == "href" and value:
                self.hrefs.append(value)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def _is_absolute_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _slug_from_url(href: str) -> str | None:
    path = urlparse(href).path.rstrip("/")
    if not path:
        return None
    stem = Path(path).stem
    if stem == "index":
        stem = Path(path).parent.name
    return stem or None


@dataclass(frozen=True)
class AtomFeedView:
    """Namespace-aware projection of an Atom feed."""

    path: Path
    root: ET.Element

    @property
    def titles(self) -> tuple[str, ...]:
        return tuple(
            title
            for title in (entry.findtext(f"{{{ATOM}}}title") for entry in self.root.findall(f"{{{ATOM}}}entry"))
            if title is not None
        )

    @property
    def ids(self) -> tuple[str, ...]:
        """Feed-level and entry-level Atom ``id`` values (document order)."""
        values: list[str] = []
        feed_id = self.root.findtext(f"{{{ATOM}}}id")
        if feed_id is not None:
            values.append(feed_id)
        for entry in self.root.findall(f"{{{ATOM}}}entry"):
            entry_id = entry.findtext(f"{{{ATOM}}}id")
            if entry_id is not None:
                values.append(entry_id)
        return tuple(values)

    @property
    def alternate_hrefs(self) -> tuple[str, ...]:
        """Entry alternate link hrefs in document order."""
        hrefs: list[str] = []
        for entry in self.root.findall(f"{{{ATOM}}}entry"):
            for link in entry.findall(f"{{{ATOM}}}link"):
                rel = link.get("rel") or "alternate"
                if rel == "alternate":
                    href = link.get("href")
                    if href:
                        hrefs.append(href)
                    break
        return tuple(hrefs)

    @property
    def slugs(self) -> tuple[str, ...]:
        """Infer entry slugs from site path URLs (id, related, then alternate)."""
        result: list[str] = []
        for entry in self.root.findall(f"{{{ATOM}}}entry"):
            candidates: list[str] = []
            entry_id = entry.findtext(f"{{{ATOM}}}id")
            if entry_id:
                candidates.append(entry_id)
            for link in entry.findall(f"{{{ATOM}}}link"):
                rel = link.get("rel") or "alternate"
                href = link.get("href") or ""
                if not href:
                    continue
                if rel == "related":
                    candidates.insert(0, href)
                elif rel == "alternate":
                    candidates.append(href)
            slug: str | None = None
            for href in candidates:
                # Prefer host paths under this site (…/posts/<slug>…), not publisher URLs.
                path = urlparse(href).path
                if "/posts/" in path or path.rstrip("/").endswith(".html"):
                    slug = _slug_from_url(href)
                    if slug:
                        break
            if slug is None:
                for href in candidates:
                    slug = _slug_from_url(href)
                    if slug:
                        break
            if slug:
                result.append(slug)
        return tuple(result)

    @property
    def all_urls_absolute(self) -> bool:
        for element in self.root.iter():
            href = element.get("href")
            if href is None:
                continue
            if not _is_absolute_http_url(href):
                return False
        for entry in self.root.findall(f"{{{ATOM}}}entry"):
            for link in entry.findall(f"{{{ATOM}}}link"):
                href = link.get("href") or ""
                if not _is_absolute_http_url(href):
                    return False
        return True

    @property
    def all_ids_absolute(self) -> bool:
        """True when every feed/entry Atom ``id`` is an absolute http(s) URL."""
        ids = self.ids
        if not ids:
            return False
        return all(_is_absolute_http_url(value) for value in ids)

    def contains_slug(self, slug: str) -> bool:
        return slug in self.slugs or any(slug in title for title in self.titles)

    def entry_by_slug(self, slug: str) -> ET.Element | None:
        """Return the first entry whose inferred slug matches *slug*."""
        for entry, entry_slug in zip(self.root.findall(f"{{{ATOM}}}entry"), self.slugs, strict=False):
            if entry_slug == slug:
                return entry
        # Fallback: match id / link paths when slug inference order diverges.
        for entry in self.root.findall(f"{{{ATOM}}}entry"):
            blob_parts = [entry.findtext(f"{{{ATOM}}}id") or ""]
            blob_parts.extend(link.get("href") or "" for link in entry.findall(f"{{{ATOM}}}link"))
            if any(f"/{slug}" in part or part.rstrip("/").endswith(slug) for part in blob_parts):
                return entry
        return None


@dataclass
class PublicSurfaces:
    """Aggregate of public listing surfaces for unpublished exclusion checks.

    Source HTML for draft/scheduled/expired documents may still be written when
    those pages are in the toctree; public surfaces are archives, post-list,
    published post navigation, and Atom only.
    """

    archive_html: dict[str, str]
    index_html: str
    published_post_html: dict[str, str]
    atom_texts: dict[str, str]
    published_slugs: tuple[str, ...]

    def contains_slug(self, slug: str) -> bool:
        """True when *slug* appears on a MaatLog public listing surface."""
        if slug in self.published_slugs:
            return True
        # Prefer explicit card markers and Atom entry URLs over Sphinx toctree chrome.
        card = f'data-slug="{slug}"'
        atom_needles = (f"/{slug}.html", f"/{slug}/", f"/{slug}<", f'/{slug}"')
        for blob in self.archive_html.values():
            if card in blob:
                return True
        if card in self.index_html:
            return True
        for blob in self.published_post_html.values():
            if card in blob:
                return True
            # MaatLog neighbor links only (not Sphinx relbar).
            if "maatlog-nav" in blob and (f"/{slug}" in blob or f"{slug}.html" in blob):
                return True
        for blob in self.atom_texts.values():
            if any(token in blob for token in atom_needles) or f">{slug}" in blob and "entry" in blob:
                if f"/{slug}" in blob or f">{slug}" in blob:
                    # Entry titles may share words; require path-like mention.
                    if any(token in blob for token in atom_needles):
                        return True
        return False


@dataclass
class AcceptanceBuildResult:
    """Result of building the acceptance site with one builder."""

    app: Sphinx
    builder: str
    outdir: Path
    warning_stream: StringIO
    status_stream: StringIO
    exception: BaseException | None = None
    _relative_files: frozenset[str] | None = field(default=None, init=False, repr=False)

    @property
    def succeeded(self) -> bool:
        return self.exception is None

    @property
    def relative_files(self) -> frozenset[str]:
        if self._relative_files is None:
            files = {path.relative_to(self.outdir).as_posix() for path in self.outdir.rglob("*") if path.is_file()}
            object.__setattr__(self, "_relative_files", frozenset(files))
        assert self._relative_files is not None
        return self._relative_files

    def relative_files_with_suffix(self, suffix: str) -> frozenset[str]:
        return frozenset(name for name in self.relative_files if name.endswith(suffix))

    def exists(self, relative: str) -> bool:
        return (self.outdir / relative).is_file()

    def path(self, relative: str) -> Path:
        return self.outdir / relative

    def text(self, relative: str) -> str:
        return self.path(relative).read_text(encoding="utf-8")

    def html(self, relative: str) -> HtmlPage:
        return HtmlPage(self.text(relative))

    def config_value(self, name: str) -> Any:
        return getattr(self.app.config, name)

    def search_index_contains(self, needle: str) -> bool:
        path = self.outdir / "searchindex.js"
        if not path.is_file():
            return False
        return needle in path.read_text(encoding="utf-8")

    def domain(self) -> MaatlogDomain:
        domain = self.app.env.get_domain("maatlog")
        assert isinstance(domain, MaatlogDomain)
        return domain

    def post(self, docname: str) -> Post:
        posts: Mapping[str, Post] = self.domain().data["posts_by_docname"]
        return posts[docname]

    def links_are_resolvable(self, relative: str) -> bool:
        """Return True when all same-site relative hrefs resolve under outdir."""
        if not self.exists(relative):
            return False
        page_path = self.path(relative)
        collector = _HrefCollector()
        collector.feed(page_path.read_text(encoding="utf-8"))
        base_dir = page_path.parent
        for href in collector.hrefs:
            if not _is_internal_relative_href(href):
                continue
            target = _resolve_href(base_dir, self.outdir, href)
            if target is None or not target.exists():
                return False
        return True

    def warnings(self) -> str:
        return self.warning_stream.getvalue()


class AcceptanceSite:
    """Self-contained acceptance Sphinx project under a temporary workdir."""

    def __init__(self, workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.workdir = workdir
        self.srcdir = workdir / "source"
        self._monkeypatch = monkeypatch
        self._build_counter = 0
        shutil.copytree(
            PROJECT_ROOT,
            self.srcdir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    def build(
        self,
        builder: str = "html",
        *,
        theme: str | None = None,
        parallel: int = 0,
        warningiserror: bool = True,
        source_date_epoch: str = DEFAULT_SOURCE_DATE_EPOCH,
        config_overrides: Mapping[str, object] | None = None,
        extra_files: Mapping[str, str | bytes] | None = None,
    ) -> AcceptanceBuildResult:
        self._build_counter += 1
        outdir = self.workdir / f"out-{builder}-{self._build_counter}"
        doctreedir = self.workdir / f"doctrees-{builder}-{self._build_counter}"
        if outdir.exists():
            shutil.rmtree(outdir)
        if doctreedir.exists():
            shutil.rmtree(doctreedir)

        if extra_files:
            for name, content in extra_files.items():
                target = self.srcdir / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(content, bytes):
                    target.write_bytes(content)
                else:
                    target.write_text(content, encoding="utf-8")

        self._apply_config_overrides(theme=theme, config_overrides=config_overrides)
        self._monkeypatch.setenv("SOURCE_DATE_EPOCH", source_date_epoch)

        warning_stream = StringIO()
        status_stream = StringIO()
        app = Sphinx(
            str(self.srcdir),
            str(self.srcdir),
            str(outdir),
            str(doctreedir),
            builder,
            status=status_stream,
            warning=warning_stream,
            warningiserror=warningiserror,
            freshenv=True,
            parallel=parallel,
        )
        try:
            app.build()
            exception: BaseException | None = None
        except BaseException as error:  # noqa: BLE001 — surface to result for A12-style checks
            exception = error
            if warningiserror or isinstance(error, (MaatlogBuildError, SphinxError, SystemExit)):
                raise
        return AcceptanceBuildResult(
            app=app,
            builder=builder,
            outdir=outdir,
            warning_stream=warning_stream,
            status_stream=status_stream,
            exception=exception,
        )

    def _reset_source(self) -> None:
        """Restore the acceptance project sources (clears prior extra_files)."""
        if self.srcdir.exists():
            shutil.rmtree(self.srcdir)
        shutil.copytree(
            PROJECT_ROOT,
            self.srcdir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    def build_invalid(
        self,
        scenario: str,
        *,
        builder: str = "html",
        source_date_epoch: str = DEFAULT_SOURCE_DATE_EPOCH,
    ) -> BaseException:
        """Build a known-invalid overlay and return the raised exception."""
        # Each scenario starts from a pristine tree so prior overlays cannot leak.
        self._reset_source()
        if scenario == "duplicate-slug":
            extra = {
                "posts/duplicate.rst": (
                    ":maatlog-post: true\n"
                    ":maatlog-slug: rst-post\n"
                    ":maatlog-published-at: 2026-08-09T12:00:00Z\n"
                    ":maatlog-tags: sphinx\n"
                    ":maatlog-categories: engineering\n"
                    ":maatlog-authors: alice\n"
                    "\n"
                    "Duplicate slug post\n"
                    "===================\n"
                    "\n"
                    "Conflicts with rst-post.\n"
                )
            }
            with pytest.raises((MaatlogBuildError, SphinxError)) as caught:
                self.build(
                    builder,
                    source_date_epoch=source_date_epoch,
                    extra_files=extra,
                )
            return caught.value

        if scenario == "invalid-slug":
            extra = {
                "posts/bad-slug.rst": (
                    ":maatlog-post: true\n"
                    ":maatlog-slug: NOT_VALID\n"
                    "\n"
                    "Bad slug post\n"
                    "=============\n"
                    "\n"
                    "Schema violation for A4.\n"
                )
            }
            with pytest.raises((MaatlogBuildError, SphinxError)) as caught:
                self.build(
                    builder,
                    source_date_epoch=source_date_epoch,
                    extra_files=extra,
                )
            return caught.value

        if scenario == "external-without-excerpt":
            extra = {
                "posts/external-bare.rst": (
                    ":maatlog-post: true\n"
                    ":maatlog-slug: external-bare\n"
                    ":maatlog-published-at: 2026-08-01T12:00:00Z\n"
                    ":maatlog-external-url: https://publisher.example/no-excerpt\n"
                    "\n"
                    "External without excerpt\n"
                    "========================\n"
                    "\n"
                    "Combination violation for A4.\n"
                )
            }
            with pytest.raises((MaatlogBuildError, SphinxError)) as caught:
                self.build(
                    builder,
                    source_date_epoch=source_date_epoch,
                    extra_files=extra,
                )
            return caught.value

        if scenario == "incompatible-theme":
            with pytest.raises((MaatlogBuildError, SphinxError)) as caught:
                self.build(
                    builder,
                    theme="incompatible_theme",
                    source_date_epoch=source_date_epoch,
                )
            return caught.value

        if scenario == "missing-manifest":
            with pytest.raises((MaatlogBuildError, SphinxError)) as caught:
                self.build(
                    builder,
                    theme="missing_manifest",
                    source_date_epoch=source_date_epoch,
                )
            return caught.value

        if scenario == "missing-block":
            with pytest.raises((MaatlogBuildError, SphinxError)) as caught:
                self.build(
                    builder,
                    theme="missing_block",
                    source_date_epoch=source_date_epoch,
                )
            return caught.value

        if scenario == "missing-templates":
            with pytest.raises((MaatlogBuildError, SphinxError)) as caught:
                self.build(
                    builder,
                    theme="missing_templates",
                    source_date_epoch=source_date_epoch,
                )
            return caught.value

        msg = f"unknown invalid scenario: {scenario}"
        raise ValueError(msg)

    def semantic_post(self, result: AcceptanceBuildResult, docname: str) -> dict[str, Any]:
        """Return Post fields excluding identity (docname / source_path / slug)."""
        post = result.post(docname)
        data = post.model_dump(mode="python")
        for key in _IDENTITY_FIELDS:
            data.pop(key, None)
        return data

    def public_surfaces(self, result: AcceptanceBuildResult) -> PublicSurfaces:
        archive_paths = sorted(
            name
            for name in result.relative_files
            if (name == "blog.html" or name.startswith("blog/")) and name.endswith(".html")
        )
        atom_paths = sorted(name for name in result.relative_files if name.endswith("atom.xml"))
        domain = result.domain()
        index = domain.data.get("index")
        published_posts = tuple(getattr(index, "published", ()))
        published = tuple(post.slug for post in published_posts)
        published_docnames = {post.docname for post in published_posts}
        published_post_html: dict[str, str] = {}
        for docname in published_docnames:
            for candidate in (f"{docname}.html", f"{docname}/index.html"):
                if result.exists(candidate):
                    published_post_html[candidate] = result.text(candidate)
        return PublicSurfaces(
            archive_html={path: result.text(path) for path in archive_paths},
            index_html=result.text("index.html") if result.exists("index.html") else "",
            published_post_html=published_post_html,
            atom_texts={path: result.text(path) for path in atom_paths},
            published_slugs=published,
        )

    def atom(self, result: AcceptanceBuildResult, relative: str) -> AtomFeedView:
        path = result.path(relative)
        root = ET.fromstring(path.read_bytes())
        return AtomFeedView(path=path, root=root)

    def expected_blog_outputs(self, builder: str, *, page_size: int | None = None) -> frozenset[str]:
        """Minimum owned blog outputs that must exist for full HTML builders.

        When *page_size* is 1 (two published posts), page-2 archive paths are
        included so pagination URI rules are exercised.
        """
        if builder == "html":
            paths = {
                "blog.html",
                "blog/atom.xml",
                "blog/tag/sphinx.html",
                "blog/tag/sphinx/atom.xml",
                "blog/category/engineering.html",
                "blog/category/engineering/atom.xml",
                "blog/author/alice.html",
                "blog/author/alice/atom.xml",
                "blog/month/2026-08.html",
                "blog/month/2026-08/atom.xml",
                "posts/rst-post.html",
                "posts/md-post.html",
            }
            if page_size == 1:
                paths.update(
                    {
                        "blog/page/2.html",
                        "blog/tag/sphinx/page/2.html",
                        "blog/category/engineering/page/2.html",
                        "blog/author/alice/page/2.html",
                        "blog/month/2026-08/page/2.html",
                    }
                )
            return frozenset(paths)
        if builder == "dirhtml":
            paths = {
                "blog/index.html",
                "blog/atom.xml",
                "blog/tag/sphinx/index.html",
                "blog/tag/sphinx/atom.xml",
                "blog/category/engineering/index.html",
                "blog/category/engineering/atom.xml",
                "blog/author/alice/index.html",
                "blog/author/alice/atom.xml",
                "blog/month/2026-08/index.html",
                "blog/month/2026-08/atom.xml",
                "posts/rst-post/index.html",
                "posts/md-post/index.html",
            }
            if page_size == 1:
                paths.update(
                    {
                        "blog/page/2/index.html",
                        "blog/tag/sphinx/page/2/index.html",
                        "blog/category/engineering/page/2/index.html",
                        "blog/author/alice/page/2/index.html",
                        "blog/month/2026-08/page/2/index.html",
                    }
                )
            return frozenset(paths)
        msg = f"no expected blog outputs for builder {builder!r}"
        raise ValueError(msg)

    def _apply_config_overrides(
        self,
        *,
        theme: str | None,
        config_overrides: Mapping[str, object] | None,
    ) -> None:
        conf_path = self.srcdir / "conf.py"
        text = conf_path.read_text(encoding="utf-8")
        # Strip previous generated overrides so repeated builds stay deterministic.
        marker = "\n# --- acceptance overrides ---\n"
        if marker in text:
            text = text.split(marker, 1)[0].rstrip() + "\n"
        overrides: dict[str, object] = {}
        if theme is not None:
            overrides["html_theme"] = theme
        if config_overrides:
            overrides.update(config_overrides)
        if not overrides:
            conf_path.write_text(text, encoding="utf-8")
            return
        lines = [marker.rstrip(), ""]
        for name, value in overrides.items():
            lines.append(f"{name} = {value!r}")
        conf_path.write_text(text + "\n".join(lines) + "\n", encoding="utf-8")


def _is_internal_relative_href(href: str) -> bool:
    if not href or href.startswith(("#", "mailto:", "tel:", "data:", "javascript:")):
        return False
    parsed = urlparse(href)
    if parsed.scheme or parsed.netloc:
        return False
    return True


def _resolve_href(base_dir: Path, outdir: Path, href: str) -> Path | None:
    path_part = unquote(urlparse(href).path)
    if not path_part or path_part.endswith("/"):
        candidate = (base_dir / path_part / "index.html").resolve()
    else:
        candidate = (base_dir / path_part).resolve()
    try:
        candidate.relative_to(outdir.resolve())
    except ValueError:
        return None
    if candidate.is_dir():
        index = candidate / "index.html"
        return index if index.exists() else candidate
    return candidate
