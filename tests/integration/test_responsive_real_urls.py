"""Original-URL guarantees with the real Pillow generator enabled.

Every metadata-bearing consumer must keep pointing at the *original* image
file (``_images/<name>``) with byte-identical bytes, whether responsive image
variants are enabled or not. This suite builds the same real project twice --
``maatlog_responsive_images = True`` and ``=False`` -- with feeds enabled and a
stable ``html_baseurl``, then compares social metadata, JSON-LD, Atom feeds,
canonical/external links, and managed/body ``<img>`` attributes between the
two output trees.

Filenames containing spaces, commas, percent signs, and Japanese characters
must survive URL resolution without double quoting, and external URIs must
never be treated as managed responsive sources.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Final, cast
from urllib.parse import unquote, urlsplit

import pytest
from conftest import HtmlPage
from fixtures.integration_builds import BuiltProject, BuiltProjects
from fixtures.responsive_image_html import img_attrs
from fixtures.responsive_real_inspect import (
    collect_managed_refs,
    local_image_path,
    managed_image_urls,
)
from fixtures.responsive_real_project import image_cases, project_config, project_files
from social_metadata import json_ld_objects

MANAGED_SEGMENT: Final = "/_images/maatlog/"

#: Source names exercising space, comma, percent, and non-ASCII characters.
SPECIAL_NAMES: Final = ("my photo.png", "a,b.png", "日本語.png", "100%.png")

_SOCIAL_PREFIXES: Final = ("og:", "article:", "profile:", "twitter:")


def _head_metadata(page: HtmlPage) -> dict[str, list[str]]:
    """Every social/canonical URL the page head advertises, keyed stably."""
    found: dict[str, list[str]] = {}
    for attrs in page.select("meta"):
        for key in ("property", "name"):
            label = attrs.get(key, "")
            if label.startswith(_SOCIAL_PREFIXES):
                found.setdefault(f"{key}:{label}", []).append(attrs.get("content", ""))
    for attrs in page.select("link"):
        rel = attrs.get("rel", "")
        if {"canonical", "alternate", "icon", "apple-touch-icon"} & set(rel.split()):
            found.setdefault(f"link:{rel}:{attrs.get('type', '')}", []).append(attrs.get("href", ""))
    return found


def _image_value(value: object) -> list[str]:
    """URL strings inside one JSON-LD ``image`` value (str, object, or list)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        mapping = cast("dict[str, object]", value)
        return [item for key in ("url", "contentUrl") if isinstance(item := mapping.get(key), str)]
    if isinstance(value, list):
        return [item for part in cast("list[object]", value) for item in _image_value(part)]
    return []


def _jsonld_images(node: object) -> list[str]:
    """Every ``image`` URL at any depth of a JSON-LD payload."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in cast("dict[str, object]", node).items():
            if key == "image":
                found.extend(_image_value(value))
            else:
                found.extend(_jsonld_images(value))
    elif isinstance(node, list):
        for item in cast("list[object]", node):
            found.extend(_jsonld_images(item))
    return found


def _all_pages(outdir: Path) -> list[tuple[str, Path]]:
    return [(page.relative_to(outdir).as_posix(), page) for page in sorted(outdir.rglob("*.html"))]


def _source_payloads(project: BuiltProject) -> dict[str, bytes]:
    """Map every image source basename under ``images/`` to its bytes."""
    return {path.name: path.read_bytes() for path in sorted((project.srcdir / "images").iterdir()) if path.is_file()}


def _original_bytes(project: BuiltProject, url: str, page_path: str) -> bytes:
    """Resolve *url* and return bytes, asserting it is a published original."""
    path = urlsplit(url).path
    assert MANAGED_SEGMENT not in path, f"managed URL leaked into metadata: {url}"
    resolved = local_image_path(project.outdir, page_path, url)
    images_root = (project.outdir / "_images").resolve()
    assert resolved.is_relative_to(images_root), f"URL resolves outside _images/: {url}"
    assert not resolved.is_relative_to(images_root / "maatlog"), f"managed file: {url}"
    return resolved.read_bytes()


def _build_pair(
    built_projects: BuiltProjects,
    *,
    source_name: str,
    files: dict[str, str | bytes] | None = None,
) -> tuple[BuiltProject, BuiltProject]:
    """Build the same project ON and OFF into two independent output trees."""
    config = project_config(enabled=True) | {"maatlog_generate_feeds": True}
    on = built_projects.real(files=files, source_name=source_name, post_count=4, config=config)
    off = built_projects.real(
        files=files,
        source_name=source_name,
        post_count=4,
        config=config | {"maatlog_responsive_images": False},
    )
    return on, off


def _assert_page_metadata_parity(on: BuiltProject, off: BuiltProject) -> None:
    """Head metadata must be identical between the ON and OFF output trees."""
    for relpath, page in _all_pages(on.outdir):
        off_page = off.outdir / relpath
        assert off_page.is_file(), f"missing OFF page {relpath}"
        on_meta = _head_metadata(HtmlPage(page.read_text(encoding="utf-8")))
        off_meta = _head_metadata(HtmlPage(off_page.read_text(encoding="utf-8")))
        assert on_meta == off_meta, f"{relpath}: head metadata differs between ON and OFF"


def _assert_original_image_urls(project: BuiltProject) -> None:
    """Every OG/X/JSON-LD image URL resolves to byte-identical original files."""
    payloads = _source_payloads(project)
    for relpath, path in _all_pages(project.outdir):
        page = HtmlPage(path.read_text(encoding="utf-8"))
        image_urls: list[str] = []
        for key, values in _head_metadata(page).items():
            if key.endswith(":image"):
                image_urls.extend(values)
        for payload in json_ld_objects(page):
            image_urls.extend(_jsonld_images(payload))
        for url in image_urls:
            data = _original_bytes(project, url, relpath)
            name = unquote(Path(urlsplit(url).path).name)
            assert name in payloads, f"{relpath}: unexpected image URL {url}"
            assert data == payloads[name], f"{relpath}: {url} is not the original bytes"


@pytest.mark.xdist_group("integration-real-url-photo-pair")
def test_social_and_jsonld_keep_original_urls(built_projects: BuiltProjects) -> None:
    on, off = _build_pair(built_projects, source_name="photo.jpg")
    _assert_page_metadata_parity(on, off)
    _assert_original_image_urls(on)
    _assert_original_image_urls(off)
    # Managed variants exist only in the ON tree and only inside body markup.
    on_refs = collect_managed_refs(on.outdir)
    assert "posts/p01.html" in on_refs
    assert collect_managed_refs(off.outdir) == {}


@pytest.mark.xdist_group("integration-real-url-photo-pair")
def test_atom_feeds_are_identical_on_and_off(built_projects: BuiltProjects) -> None:
    on, off = _build_pair(built_projects, source_name="photo.jpg")
    on_feeds = {p.relative_to(on.outdir).as_posix(): p for p in on.outdir.rglob("atom.xml")}
    off_feeds = {p.relative_to(off.outdir).as_posix(): p for p in off.outdir.rglob("atom.xml")}
    assert on_feeds, "no Atom feeds emitted"
    assert set(on_feeds) == set(off_feeds)
    for relpath, feed in on_feeds.items():
        assert feed.read_bytes() == off_feeds[relpath].read_bytes(), f"{relpath} differs ON vs OFF"
        # Feed entry content escapes HTML; unescape once so real <img> tags parse.
        decoded = html.unescape(feed.read_text(encoding="utf-8"))
        for attrs in img_attrs(decoded):
            src = attrs.get("src", "")
            if src:
                _original_bytes(on, src, relpath)


@pytest.mark.parametrize("source_name", SPECIAL_NAMES, ids=["space", "comma", "japanese", "percent"])
def test_special_named_sources_keep_original_urls(built_projects: BuiltProjects, source_name: str) -> None:
    on, off = _build_pair(built_projects, source_name=source_name)
    _assert_page_metadata_parity(on, off)
    _assert_original_image_urls(on)
    _assert_original_image_urls(off)
    # The original asset is published verbatim under _images/<name>.
    original = on.outdir / "_images" / source_name
    assert original.read_bytes() == image_cases()[source_name].payload
    p01 = HtmlPage((on.outdir / "posts" / "p01.html").read_text(encoding="utf-8"))
    managed = managed_image_urls(p01.text)
    assert managed, "p01 lost its managed candidate set"
    for url in managed:
        # URL-unsafe characters must resolve to real files (no double quoting).
        local_image_path(on.outdir, "posts/p01.html", url)


def test_body_avatar_and_external_images_are_not_managed(built_projects: BuiltProjects) -> None:
    files = project_files(source_name="photo.jpg", post_count=4)
    files["posts/external.md"] = (
        "---\nmaatlog-post: true\nmaatlog-slug: external\n"
        "maatlog-published-at: 2026-07-19T09:00:00Z\n"
        "maatlog-external-url: https://external.test/article\n"
        "maatlog-excerpt: External excerpt.\n"
        "maatlog-image: ../images/photo.jpg\n---\n# EXTERNAL\n\nBody.\n"
    )
    index = files["index.rst"]
    assert isinstance(index, str)
    files["index.rst"] = index.replace("   posts/p01\n", "   posts/external\n   posts/p01\n")
    on, _off = _build_pair(built_projects, source_name="photo.jpg", files=files)
    payloads = _source_payloads(on)

    general = HtmlPage((on.outdir / "general.html").read_text(encoding="utf-8"))
    assert managed_image_urls(general.text) == set()
    for attrs in img_attrs(general.text):
        assert "srcset" not in attrs
        assert "data-maatlog-srcset" not in attrs
        src = attrs.get("src", "")
        if src == "https://example.test/remote.png":
            continue  # the external body image stays external
        data = _original_bytes(on, src, "general.html")
        assert data in payloads.values(), f"general body image {src} has foreign bytes"

    # p01 embeds the managed source twice: managed card/top markup carries
    # candidates while the ordinary body occurrence stays a plain <img>
    # pointing at the published original -- no srcset, sizes, or marker attr.
    p01 = HtmlPage((on.outdir / "posts" / "p01.html").read_text(encoding="utf-8"))
    assert managed_image_urls(p01.text), "p01 lost its managed candidate set"
    body_imgs = [
        attrs
        for attrs in img_attrs(p01.text)
        if "data-maatlog-srcset" not in attrs and attrs.get("src", "").rsplit("/", 1)[-1] == "photo.jpg"
    ]
    assert body_imgs, "p01 body occurrence of the managed source not found"
    for attrs in body_imgs:
        assert "srcset" not in attrs
        assert "sizes" not in attrs
        data = _original_bytes(on, attrs["src"], "posts/p01.html")
        assert data == payloads["photo.jpg"]

    # The external article shares its external URL while the local canonical
    # link and the representative image keep pointing at local originals.
    external = HtmlPage((on.outdir / "posts" / "external.html").read_text(encoding="utf-8"))
    head = _head_metadata(external)
    assert head["property:og:url"] == ["https://external.test/article"]
    og_image = head["property:og:image"][0]
    data = _original_bytes(on, og_image, "posts/external.html")
    assert data == payloads["photo.jpg"]
    canonical = [value for key, values in head.items() if key.startswith("link:canonical") for value in values]
    assert canonical == ["https://example.test/docs/posts/external.html"]
