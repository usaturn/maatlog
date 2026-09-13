"""Lifecycle and builder pins for social metadata (issue #212).

The semantic signature (ordered metadata, canonical, Atom discovery) must stay
stable across incremental and parallel builds. Byte-for-byte HTML comparison is
out of scope: Sphinx emits non-essential differences between builds.
"""

from __future__ import annotations

import pytest
from conftest import HtmlPage, ProjectFactory
from social_metadata import (
    MetaCollector,
    assert_no_duplicate_social_metadata,
    json_ld_objects,
)

LIFECYCLE_FILES: dict[str, str | bytes] = {
    "index.rst": "Home\n====\n",
    "post.rst": (
        ":maatlog-post: true\n:maatlog-slug: post\n:maatlog-published-at: 2026-07-15T12:00:00Z\n"
        ":maatlog-tags: sphinx\n:maatlog-categories: engineering\n:maatlog-authors: alice\n\nPost\n====\n"
    ),
    "normal.rst": "Normal\n======\n",
    "authors/alice.md": "# Alice\n",
}

LIFECYCLE_CONFIG: dict[str, object] = {
    "html_baseurl": "https://example.test/",
    "project": "Example Blog",
    "maatlog_home_docname": "index",
    "maatlog_authors": {"alice": "Alice"},
    "maatlog_author_profiles": {"alice": {"about_docname": "authors/alice"}},
}

#: Every rendered page kind: configured Home, internal post, archive, author
#: profile, and one ordinary page without any metadata.
PAGE_PATHS = (
    "index.html",
    "post.html",
    "blog.html",
    "blog/author/alice.html",
    "normal.html",
)


def _signature(page: HtmlPage) -> tuple[object, ...]:
    collector = MetaCollector()
    collector.feed(page.text)
    collector.close()
    canonical = tuple(item["href"] for item in page.select('link[rel="canonical"]'))
    atom = tuple(item["href"] for item in page.select('link[type="application/atom+xml"]'))
    return (
        tuple(collector.open_graph_items),
        tuple(collector.twitter_items),
        tuple(json_ld_objects(page)),
        canonical,
        atom,
    )


def test_incremental_rebuild_preserves_all_page_metadata(make_project: ProjectFactory) -> None:
    project = make_project(files=LIFECYCLE_FILES, config=LIFECYCLE_CONFIG)
    first = project.build()
    before = {path: _signature(first.html(path)) for path in PAGE_PATHS}
    project.write("normal.rst", "Normal\n======\n\nChanged body only.\n")
    second = project.build(reuse_environment=True)
    assert {path: _signature(second.html(path)) for path in PAGE_PATHS} == before
    for path in PAGE_PATHS:
        assert_no_duplicate_social_metadata(second.html(path))


def test_parallel_build_matches_serial_metadata(make_project: ProjectFactory) -> None:
    serial = make_project(files=LIFECYCLE_FILES, config=LIFECYCLE_CONFIG).build()
    parallel = make_project(files=LIFECYCLE_FILES, config=LIFECYCLE_CONFIG).build(parallel=4)
    assert {path: _signature(parallel.html(path)) for path in PAGE_PATHS} == {
        path: _signature(serial.html(path)) for path in PAGE_PATHS
    }


@pytest.mark.parametrize("builder", ["text", "singlehtml"])
def test_lifecycle_non_full_html_builders_emit_no_metadata(make_project: ProjectFactory, builder: str) -> None:
    result = make_project(
        files=LIFECYCLE_FILES,
        config={**LIFECYCLE_CONFIG, "html_baseurl": ""},
        builder=builder,
    ).build()

    output = result.path("index.txt" if builder == "text" else "index.html").read_text(encoding="utf-8")
    assert 'property="og:' not in output
    assert 'name="twitter:' not in output
    assert "application/ld+json" not in output
    assert "baseurl-required" not in result.warnings
