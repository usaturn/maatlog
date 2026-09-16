from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import pytest
from conftest import SphinxFactory
from fixtures.responsive_build_fixtures import FILES, RecordingGenerator
from fixtures.responsive_image_fixtures import sample_responsive_image_view

from maatlog.image_contracts import ImageUsage, register_variant_generator_factory
from maatlog.views import PostCardView, post_card_template_mapping, responsive_image_for


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_projection_is_relative_to_each_target(make_sphinx: SphinxFactory, builder: str) -> None:
    app = make_sphinx(files=FILES, builder=builder, config={"maatlog_responsive_images": True})
    generator = RecordingGenerator()
    register_variant_generator_factory(app, lambda: generator)
    app.build()
    for docname in ("posts/one", "index", "blog", "blog/page/2", "listing"):
        view = responsive_image_for(app.builder, docname, "img/hero.png", usage=ImageUsage.ARCHIVE_CARD)
        assert view is not None
        assert view.src == view.candidates[-1].url
        for candidate in view.candidates:
            target_uri = app.builder.get_target_uri(docname)
            url = urljoin("https://example.test/" + target_uri, candidate.url)
            relative = unquote(urlsplit(url).path.lstrip("/"))
            assert (Path(app.outdir) / relative).is_file()


def test_card_mapping_preserves_responsive_fields() -> None:
    view = sample_responsive_image_view()
    card = PostCardView(
        title="one",
        page_url="one.html",
        published_at=None,
        excerpt=None,
        image_url="_images/original.png",
        tags=(),
        categories=(),
        authors=(),
        external_url=None,
        responsive_image=view,
    )
    data = post_card_template_mapping(card)
    assert data["image_url"] == "_images/original.png"
    assert data["responsive_image"]["srcset"] == view.srcset
    assert data["responsive_image"]["usage"] == "post-representative"
    assert data["responsive_image"]["width"] == 1600
