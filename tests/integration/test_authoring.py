from pathlib import Path

import pytest
from conftest import SphinxFactory
from sphinx.application import Sphinx

from maatlog.errors import MaatlogBuildError
from maatlog.model import PublicationStatus

RST_POST = """:maatlog-post: true
:maatlog-published-at: 2026-07-31T09:00:00Z
:maatlog-expires-at: 2026-08-02T09:00:00Z
:maatlog-slug: sphinx-extension-rst
:maatlog-tags: sphinx, python
:maatlog-categories: engineering
:maatlog-authors: alice
:maatlog-excerpt: Sphinx extension design.
:maatlog-image: images/cover.png
:maatlog-canonical-url: https://example.com/blog/sphinx-extension/?ref=maatlog
:maatlog-external-url: https://publisher.example/articles/42

Same title
==========
"""

MYST_POST = """---
maatlog-post: true
maatlog-published-at: 2026-07-31T09:00:00Z
maatlog-expires-at: 2026-08-02T09:00:00Z
maatlog-slug: sphinx-extension-md
maatlog-tags: [sphinx, python]
maatlog-categories: [engineering]
maatlog-authors: [alice]
maatlog-excerpt: Sphinx extension design.
maatlog-image: images/cover.png
maatlog-canonical-url: https://example.com/blog/sphinx-extension/?ref=maatlog
maatlog-external-url: https://publisher.example/articles/42
---
# Same title
"""


def test_rst_and_myst_produce_equal_posts(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files={"rst-post.rst": RST_POST, "md-post.md": MYST_POST, "images/cover.png": b"png"})

    app.build()

    posts = app.env.get_domain("maatlog").data["posts_by_docname"]
    rst_post = posts["rst-post"]
    md_post = posts["md-post"]
    # Slugs differ so finalize can index both posts; other fields must match.
    assert rst_post.model_copy(
        update={"docname": "same", "source_path": "same", "slug": "same"}
    ) == md_post.model_copy(update={"docname": "same", "source_path": "same", "slug": "same"})
    assert rst_post.status is PublicationStatus.PUBLISHED


def test_normal_documents_coexist_without_becoming_posts(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "plain.rst": "Plain\n=====\n",
            "explicit-false.md": "---\nmaatlog-post: false\n---\n# Plain too\n",
        }
    )

    app.build()

    assert app.env.get_domain("maatlog").data["posts_by_docname"] == {}


def test_rst_accepts_docinfo_immediately_after_document_title(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "post.rst": "Title first\n===========\n\n:maatlog-post: true\n:maatlog-slug: title-first\n",
        }
    )

    app.build()

    post = app.env.get_domain("maatlog").data["posts_by_docname"]["post"]
    assert post.title == "Title first"
    assert post.slug == "title-first"


@pytest.mark.parametrize(
    ("body", "codes", "lines"),
    [
        (
            ":maatlog-post: true\n:maatlog-slug: valid\n:maatlog-typo: value\n\nTitle\n=====\n",
            ["maatlog.metadata.unknown"],
            [3],
        ),
        (
            ":maatlog-slug: orphan\n\nTitle\n=====\n",
            ["maatlog.metadata.without-post"],
            [1],
        ),
        (
            ":maatlog-post: true\n\nBody without title.\n",
            ["maatlog.metadata.required", "maatlog.metadata.required"],
            [1, 1],
        ),
    ],
)
def test_rst_schema_diagnostics_keep_source_and_line(
    make_sphinx: SphinxFactory,
    body: str,
    codes: list[str],
    lines: list[int],
) -> None:
    app = make_sphinx(files={"post.rst": body})

    with pytest.raises(MaatlogBuildError) as error:
        app.build()

    assert [item.code for item in error.value.diagnostics] == codes
    assert [item.line for item in error.value.diagnostics] == lines
    assert all(item.source is not None and item.source.endswith("post.rst") for item in error.value.diagnostics)


def test_myst_sequences_reject_numbers_instead_of_stringifying_them(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "post.md": """---
maatlog-post: true
maatlog-slug: valid
maatlog-tags: [python, 42]
---
# Title
"""
        }
    )

    with pytest.raises(MaatlogBuildError) as error:
        app.build()

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.metadata.type"
    assert diagnostic.field == "maatlog-tags"
    assert diagnostic.line == 4


def test_myst_rejects_a_quoted_text_post_marker(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "post.md": """---
maatlog-post: "true"
maatlog-slug: valid
---
# Title
"""
        }
    )

    with pytest.raises(MaatlogBuildError) as error:
        app.build()

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.metadata.type"
    assert diagnostic.field == "maatlog-post"
    assert diagnostic.line == 2
    assert "_maatlog_sources_by_docname" not in app.__dict__


def test_myst_uses_final_source_after_later_source_read_listener(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "post.md": """---
maatlog-post: "false"
maatlog-slug: disk-version
---
# Disk title
"""
        }
    )

    def transform_source(app: Sphinx, docname: str, source: list[str]) -> None:
        del app, docname
        source[0] = """---
maatlog-post: true
maatlog-slug: transformed-version
---
# Transformed title
"""

    app.connect("source-read", transform_source, priority=1000)
    app.build()

    post = app.env.get_domain("maatlog").data["posts_by_docname"]["post"]
    assert post.slug == "transformed-version"
    assert post.title == "Transformed title"
    assert "_maatlog_sources_by_docname" not in app.__dict__


def test_myst_quoted_key_diagnostic_uses_parser_key_line(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "post.md": """---
"maatlog-post": true
"maatlog-slug": valid
"maatlog-typo": value
---
# Title
"""
        }
    )

    with pytest.raises(MaatlogBuildError) as error:
        app.build()

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.metadata.unknown"
    assert diagnostic.field == "maatlog-typo"
    assert diagnostic.line == 4


def test_myst_duplicate_key_diagnostic_uses_effective_value_line(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "post.md": """---
maatlog-post: true
maatlog-slug: valid
maatlog-slug: INVALID
---
# Title
"""
        }
    )

    with pytest.raises(MaatlogBuildError) as error:
        app.build()

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "maatlog.slug.invalid"
    assert diagnostic.field == "maatlog-slug"
    assert diagnostic.value == "'INVALID'"
    assert diagnostic.line == 4


def test_descendant_title_does_not_replace_missing_document_title(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "post.rst": """:maatlog-post: true
:maatlog-slug: valid

.. admonition:: Not the document title

   Body.
"""
        }
    )

    with pytest.raises(MaatlogBuildError) as error:
        app.build()

    assert [(item.code, item.field) for item in error.value.diagnostics] == [("maatlog.metadata.required", "title")]


@pytest.mark.parametrize(
    ("metadata", "expected_codes"),
    [
        ("maatlog-canonical-url: /relative", ["maatlog.url.invalid"]),
        ("maatlog-external-url: https://example.com/article", ["maatlog.metadata.combination"]),
        ("maatlog-excerpt: '   '", ["maatlog.metadata.value"]),
    ],
)
def test_url_excerpt_and_external_rules(
    make_sphinx: SphinxFactory,
    metadata: str,
    expected_codes: list[str],
) -> None:
    app = make_sphinx(
        files={
            "post.md": f"""---
maatlog-post: true
maatlog-slug: valid
{metadata}
---
# Title
"""
        }
    )

    with pytest.raises(MaatlogBuildError) as error:
        app.build()

    assert [item.code for item in error.value.diagnostics] == expected_codes


def test_build_replaces_existing_domain_entry_by_docname(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "post.rst": ":maatlog-post: true\n:maatlog-slug: first\n\nTitle\n=====\n",
        }
    )
    app.build()
    source = Path(app.srcdir) / "post.rst"
    source.write_text(":maatlog-post: true\n:maatlog-slug: second\n\nTitle\n=====\n", encoding="utf-8")

    app.builder.build_all()

    posts = app.env.get_domain("maatlog").data["posts_by_docname"]
    assert list(posts) == ["post"]
    assert posts["post"].slug == "second"
