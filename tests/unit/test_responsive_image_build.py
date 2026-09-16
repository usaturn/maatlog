"""Unit tests for the parent responsive-image build step."""

from __future__ import annotations

from typing import cast

import pytest
from conftest import SphinxFactory
from fixtures.responsive_build_fixtures import RecordingGenerator

from maatlog.image_contracts import register_variant_generator_factory
from maatlog.responsive_image_build import (
    IMAGE_SOURCE_UNREADABLE,
    prepare_responsive_images,
    responsive_manifest,
)


def test_responsive_manifest_defaults_to_empty(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files={"index.rst": "Root\n====\n"})
    assert responsive_manifest(app.env) == {}


def test_responsive_manifest_is_read_only(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files={"index.rst": "Root\n====\n"})
    assert prepare_responsive_images(app, app.env) == []
    manifest = responsive_manifest(app.env)
    with pytest.raises(TypeError):
        cast(dict[str, object], manifest)["img/hero.png"] = object()


def test_prepare_disabled_resolves_no_backend_and_computes_nothing(
    make_sphinx: SphinxFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("must not be called on a disabled build")

    monkeypatch.setattr("maatlog.responsive_image_build.build_source_identity", fail)
    monkeypatch.setattr("maatlog.responsive_image_build.sniff_source_format", fail)
    monkeypatch.setattr("maatlog.responsive_image_build.select_candidate_widths", fail)
    constructed: list[int] = []

    def factory() -> RecordingGenerator:
        constructed.append(1)
        raise AssertionError("factory must not be called on a disabled build")

    app = make_sphinx(files={"index.rst": "Root\n====\n"}, config={"maatlog_responsive_images": False})
    register_variant_generator_factory(app, factory)
    assert prepare_responsive_images(app, app.env) == []
    assert constructed == []
    assert responsive_manifest(app.env) == {}


def test_image_source_unreadable_code() -> None:
    assert IMAGE_SOURCE_UNREADABLE == "maatlog.image.source-unreadable"
