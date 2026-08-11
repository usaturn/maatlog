"""Integration coverage for MaatLog representative image validation."""

from pathlib import Path

import pytest
from conftest import ProjectFactory, SphinxFactory

from maatlog.errors import MaatlogBuildError
from maatlog.views import image_url_for


def test_image_is_validated_and_registered(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "post.rst": """:maatlog-post: true
:maatlog-slug: valid
:maatlog-image: images/cover.png

Title
=====
""",
            "images/cover.png": b"png",
        }
    )

    app.build()

    post = app.env.get_domain("maatlog").data["posts_by_docname"]["post"]
    assert post.image_uri == "images/cover.png"
    assert app.env.dependencies["post"] == {Path(app.srcdir) / "images" / "cover.png"}
    assert "images/cover.png" in app.env.images
    assert "images/cover.png" in app.builder.images
    dest = app.builder.images["images/cover.png"]
    assert (Path(app.outdir) / "_images" / dest).is_file()


def test_representative_image_enters_sphinx_pipeline(make_project: ProjectFactory) -> None:
    """Validated maatlog-image is copied via builder.images and yields a real URL."""
    result = make_project(
        files={
            "post.rst": """:maatlog-post: true
:maatlog-slug: with-image
:maatlog-published-at: 2026-07-01T00:00:00Z
:maatlog-image: images/cover.png

Title
=====

Body.
""",
            "images/cover.png": b"png-bytes",
        }
    ).build()

    post = result.app.env.get_domain("maatlog").data["posts_by_docname"]["post"]
    assert post.image_uri == "images/cover.png"
    assert "images/cover.png" in result.app.builder.images
    dest = result.app.builder.images["images/cover.png"]
    assert result.path(f"_images/{dest}").is_file()
    assert result.path(f"_images/{dest}").read_bytes() == b"png-bytes"

    url = image_url_for(result.app.builder, "post", post.image_uri)
    assert url is not None
    assert dest in url
    assert "_images" in url or url == dest
    # Must not fall back to the raw source-relative path alone.
    assert url != "images/cover.png"


@pytest.mark.parametrize(
    ("uri", "code"),
    [
        ("missing.png", "maatlog.image.missing"),
        ("https://example.com/cover.png", "maatlog.image.invalid"),
        ("https://[", "maatlog.image.invalid"),
        ("bad%00.png", "maatlog.image.invalid"),
        ("images/cover.png?size=large", "maatlog.image.invalid"),
        ("images/cover.png#hero", "maatlog.image.invalid"),
        ("/absolute.png", "maatlog.image.invalid"),
        ("../../outside.png", "maatlog.image.invalid"),
        ("images", "maatlog.image.missing"),
    ],
)
def test_invalid_image_fails(make_sphinx: SphinxFactory, uri: str, code: str) -> None:
    app = make_sphinx(
        files={
            "post.rst": f""":maatlog-post: true
:maatlog-slug: valid
:maatlog-image: {uri}

Title
=====
""",
            "images/placeholder.txt": "placeholder",
        }
    )

    with pytest.raises(MaatlogBuildError) as error:
        app.build()

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == code
    assert diagnostic.field == "maatlog-image"
    assert diagnostic.line == 3
    assert app.env.dependencies["post"] == set()


def test_image_symlink_cannot_escape_source_root(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "post.rst": """:maatlog-post: true
:maatlog-slug: valid
:maatlog-image: cover.png

Title
=====
"""
        }
    )
    outside = Path(app.srcdir).parent / "outside.png"
    outside.write_bytes(b"png")
    (Path(app.srcdir) / "cover.png").symlink_to(outside)

    with pytest.raises(MaatlogBuildError) as error:
        app.build()

    assert error.value.diagnostics[0].code == "maatlog.image.invalid"
    assert app.env.dependencies["post"] == set()


@pytest.mark.parametrize("symlink_component", ["file", "directory"])
def test_internal_image_symlink_is_rejected(make_sphinx: SphinxFactory, symlink_component: str) -> None:
    app = make_sphinx(
        files={
            "post.rst": """:maatlog-post: true
:maatlog-slug: valid
:maatlog-image: IMAGE_URI

Title
=====
""",
        }
    )
    source_root = Path(app.srcdir)
    if symlink_component == "file":
        target = source_root / "actual.png"
        target.write_bytes(b"png")
        (source_root / "cover.png").symlink_to(target)
        image_uri = "cover.png"
    else:
        target = source_root / "actual-images"
        target.mkdir()
        (target / "cover.png").write_bytes(b"png")
        (source_root / "images").symlink_to(target, target_is_directory=True)
        image_uri = "images/cover.png"
    post_source = source_root / "post.rst"
    post_source.write_text(post_source.read_text(encoding="utf-8").replace("IMAGE_URI", image_uri), encoding="utf-8")

    with pytest.raises(MaatlogBuildError) as error:
        app.build()

    assert error.value.diagnostics[0].code == "maatlog.image.invalid"
    assert app.env.dependencies["post"] == set()


@pytest.mark.parametrize("parallel", [1, 4])
def test_unpublished_representative_image_is_copied_in_parallel(
    make_project: ProjectFactory,
    parallel: int,
) -> None:
    files: dict[str, str | bytes] = {
        f"post-{i:02d}.rst": f""":maatlog-post: true
:maatlog-slug: post-{i:02d}
:maatlog-published-at: 2026-07-{i + 1:02d}T00:00:00Z

Post {i}
========
"""
        for i in range(8)
    }
    files["zz-draft.rst"] = """:maatlog-post: true
:maatlog-slug: image-draft
:maatlog-image: images/cover.png

Image Draft
===========
"""
    files["images/cover.png"] = b"parallel-image"

    result = make_project(files=files).build(parallel=parallel)
    post = result.app.env.get_domain("maatlog").data["posts_by_docname"]["zz-draft"]
    destination = result.app.env.images[post.image_uri][1]
    assert result.path(f"_images/{destination}").read_bytes() == b"parallel-image"


def test_official_post_cards_render_decorative_image(make_project: ProjectFactory) -> None:
    files: dict[str, str | bytes] = {
        "index.rst": """Root
====

.. maatlog:post-list::

.. toctree::
   :hidden:

   post
""",
        "post.rst": """:maatlog-post: true
:maatlog-slug: pictured
:maatlog-published-at: 2026-07-01T00:00:00Z
:maatlog-image: images/cover.png

Pictured
========
""",
        "images/cover.png": b"card-image",
    }
    result = make_project(files=files).build()
    for relative in ("index.html", "blog.html"):
        image = result.html(relative).select_one("img.maatlog-post-card-image")
        assert image is not None
        assert image["alt"] == ""
        assert "_images/" in image["src"]
