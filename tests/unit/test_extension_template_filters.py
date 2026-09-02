"""Unit tests for template filter registration in the extension."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from sphinx.application import Sphinx

from maatlog.extension import _register_template_filters  # pyright: ignore[reportPrivateUsage]


class _DummyTemplates:
    """Minimal templates object without an ``environment`` attribute."""


def test_register_template_filters_skips_when_environment_missing() -> None:
    builder = SimpleNamespace(templates=_DummyTemplates())
    app = cast(Sphinx, SimpleNamespace(builder=builder))

    _register_template_filters(app)
