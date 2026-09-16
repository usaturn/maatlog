"""Observation helpers for the real-generator lifecycle/URL tests (issue #217, task E/T3).

Everything here observes a real ``maatlog_responsive_images = True`` build
from the outside: page HTML is parsed for managed ``<img>`` candidates,
published bytes are hashed, and incremental rebuilds go through a second
``Sphinx`` application over the same srcdir/outdir/doctreedir. The encode spy
delegates to the real Pillow encoder, so observation never changes output.
"""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from io import StringIO
from pathlib import Path
from typing import Any, Final, cast
from urllib.parse import unquote, urljoin, urlsplit

import pytest
from fixtures.responsive_image_html import img_attrs
from sphinx.application import Sphinx

import maatlog.responsive_images as responsive_backend
from maatlog.image_contracts import RESPONSIVE_CACHE_DIRNAME, RESPONSIVE_OUTPUT_SUBDIR
from maatlog.responsive_image_build import responsive_manifest

#: ``html_baseurl`` every real project fixture builds with.
BASE_URL: Final = "https://example.test/docs/"


def reopen(previous: Sphinx, *, overrides: dict[str, object] | None = None, parallel: int = 0) -> Sphinx:
    """Re-open the same project for a real incremental rebuild (test-only).

    ``freshenv=False`` keeps the doctrees so Sphinx decides what is stale.
    Config lives in ``conf.py``, so *overrides* only carries the keys the test
    changes -- forgetting them can never silently turn the feature off.
    """
    return Sphinx(
        str(previous.srcdir),
        str(previous.confdir),
        str(previous.outdir),
        str(previous.doctreedir),
        previous.builder.name,
        confoverrides=overrides or {},
        freshenv=False,
        parallel=parallel,
        status=StringIO(),
        warning=StringIO(),
        warningiserror=True,
    )


def file_snapshot(root: Path) -> dict[str, str]:
    """Map every file under *root* to its SHA-256 hex digest (test-only)."""
    assert root.is_dir(), root
    return {
        p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def local_image_path(outdir: Path, page_path: str, url: str) -> Path:
    """Resolve a page-relative or site-absolute image URL to an output file.

    Asserts the URL stays on ``example.test`` below ``/docs/`` and resolves to
    an existing file inside *outdir*, so a double-quoted or escaped URL fails.
    """
    full = urljoin(BASE_URL + page_path, url)
    parsed = urlsplit(full)
    assert parsed.netloc == "example.test"
    relative = unquote(parsed.path.removeprefix("/docs/"))
    target = (outdir / relative).resolve()
    assert target.is_relative_to(outdir.resolve())
    assert target.is_file()
    return target


def page_path(builder_name: str, docname: str) -> str:
    """Outdir-relative HTML path for *docname* under the real builders.

    ``dirhtml`` writes ``index`` to the root ``index.html`` and every other
    docname (``x`` or ``x/index``) to ``<docname>/index.html``.
    """
    if builder_name == "html":
        return f"{docname}.html"
    return f"{docname}.html" if docname == "index" else f"{docname.removesuffix('/index')}/index.html"


def variant_dir(outdir: Path) -> Path:
    """The published responsive-variant directory inside *outdir*."""
    return outdir / "_images" / RESPONSIVE_OUTPUT_SUBDIR


def published_variants(outdir: Path) -> dict[str, bytes]:
    """Published variant bytes keyed by basename, ownership manifest excluded."""
    root = variant_dir(outdir)
    if not root.is_dir():
        return {}
    return {
        path.name: path.read_bytes()
        for path in sorted(root.iterdir())
        if path.is_file() and not path.name.startswith(".")
    }


def manifest_basenames(app: Sphinx) -> set[str]:
    """Basenames every manifest entry publishes this build."""
    return {variant.public_basename for entry in responsive_manifest(app.env).values() for variant in entry.variants}


def cache_dir(app: Sphinx) -> Path:
    """The doctreedir variant cache directory the real pipeline uses."""
    return Path(app.doctreedir) / RESPONSIVE_CACHE_DIRNAME


def cache_files(app: Sphinx) -> list[Path]:
    """Every file inside the variant cache (images and sidecars)."""
    root = cache_dir(app)
    return sorted(path for path in root.rglob("*") if path.is_file())


def managed_image_urls(html: str) -> set[str]:
    """Every fetchable URL of a managed ``<img>`` on one page (src + srcset)."""
    urls: set[str] = set()
    for attrs in img_attrs(html):
        if "data-maatlog-srcset" not in attrs:
            continue
        if attrs.get("src"):
            urls.add(attrs["src"])
        for part in attrs.get("srcset", "").split(","):
            token = part.strip().split(" ")[0]
            if token:
                urls.add(token)
    return urls


def candidate_basename(url: str) -> str:
    """The final URL path segment of a responsive candidate URL."""
    return url.rsplit("/", 1)[-1]


def collect_managed_refs(outdir: Path) -> dict[str, set[str]]:
    """Map each emitted HTML page to the managed candidate basenames it uses.

    Parses the emitted markup -- not the template context -- so a consumer page
    the build forgot to rewrite shows up with stale basenames instead of going
    unnoticed. Every referenced URL is also resolved to a real output file.
    """
    refs: dict[str, set[str]] = {}
    for page in sorted(outdir.rglob("*.html")):
        relpath = page.relative_to(outdir).as_posix()
        urls = managed_image_urls(page.read_text(encoding="utf-8"))
        for url in urls:
            local_image_path(outdir, relpath, url)
        if urls:
            refs[relpath] = {candidate_basename(url) for url in urls}
    return refs


def forbidden_encode() -> Callable[..., None]:
    """An ``_encode_variant`` stand-in that fails the test when called."""

    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("responsive variant re-encoded on this rebuild")

    return boom


class EncodeCounter:
    """Delegating ``_encode_variant`` observation wrapper (test-only).

    Counts real encodes; every call reaches the production encoder unchanged,
    so output bytes are exactly what an unobserved build produces.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls = 0
        real = cast(Any, responsive_backend._encode_variant)  # pyright: ignore[reportPrivateUsage]

        def counted(source_bytes: bytes, request: Any, encoder: Any, target: Path) -> None:
            self.calls += 1
            real(source_bytes, request, encoder, target)

        monkeypatch.setattr(responsive_backend, "_encode_variant", counted)
