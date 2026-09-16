from __future__ import annotations

import sys

import pytest
from conftest import SphinxFactory
from fixtures.responsive_build_fixtures import PROBE
from fixtures.responsive_image_fixtures import FakeVariantGenerator, make_test_png

from maatlog.errors import Diagnostic, MaatlogBuildError
from maatlog.image_contracts import (
    IMAGE_BACKEND_MISSING,
    ImageProcessingError,
    register_variant_generator_factory,
)
from maatlog.responsive_images import PillowImageVariantGenerator

FILES: dict[str, str | bytes] = {
    "index.rst": "Index\n=====\n\n.. toctree::\n\n   post\n",
    "post.rst": ("Post\n====\n\n:maatlog-post: true\n:maatlog-slug: post\n:maatlog-image: img/hero.png\n\nBody.\n"),
    "img/hero.png": make_test_png(1600, 900),
}


def test_disabled_build_never_imports_pillow(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files=FILES)
    # Sphinx 9.1 may import PIL during app init (guarded optional import in
    # sphinx.builders._epub_base); this test guards the build phase only.
    for name in [m for m in list(sys.modules) if m == "PIL" or m.startswith("PIL.")]:
        sys.modules.pop(name)
    app.build()
    assert not any(m == "PIL" or m.startswith("PIL.") for m in sys.modules)


def test_disabled_build_emits_no_srcset(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files=FILES)
    app.build()
    html = (app.outdir / "post.html").read_text(encoding="utf-8")
    assert "srcset" not in html


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_enabled_with_unavailable_backend_fails_with_backend_missing(
    make_sphinx: SphinxFactory, monkeypatch: pytest.MonkeyPatch, builder: str
) -> None:
    def unavailable(self: PillowImageVariantGenerator) -> None:
        raise ImageProcessingError(
            Diagnostic(
                code=IMAGE_BACKEND_MISSING,
                message="Backend unavailable in this boundary test",
                expected='pip install "maatlog[images]"',
            )
        )

    monkeypatch.setattr(PillowImageVariantGenerator, "describe_backend", unavailable)
    with pytest.raises(MaatlogBuildError) as error:
        app = make_sphinx(files=FILES, config={"maatlog_responsive_images": True}, builder=builder)
        app.build()
    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == IMAGE_BACKEND_MISSING
    assert "maatlog[images]" in (diagnostic.expected or "")


@pytest.mark.parametrize("builder", ["text", "singlehtml"])
def test_enabled_non_full_html_builders_stay_unaffected(make_sphinx: SphinxFactory, builder: str) -> None:
    app = make_sphinx(files=FILES, config={"maatlog_responsive_images": True}, builder=builder)
    # Sphinx 9.1 may import PIL during app init (guarded optional import in
    # sphinx.builders._epub_base); this test guards the build phase only.
    for name in [m for m in list(sys.modules) if m == "PIL" or m.startswith("PIL.")]:
        sys.modules.pop(name)
    app.build()
    assert not any(m == "PIL" or m.startswith("PIL.") for m in sys.modules)


def test_registered_generator_satisfies_the_backend_gate(make_sphinx: SphinxFactory) -> None:
    calls: list[int] = []

    def factory() -> FakeVariantGenerator:
        calls.append(1)
        return FakeVariantGenerator(probes={"hero.png": PROBE})

    app = make_sphinx(files=FILES, config={"maatlog_responsive_images": True})
    register_variant_generator_factory(app, factory)
    app.build()
    assert len(calls) == 1
