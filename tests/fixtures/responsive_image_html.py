"""Render helper for responsive-image component tests (issue #216).

Uses Sphinx's own template loader/filters so the tests exercise the real
``maatlog-base`` Jinja environment instead of reimplementing it.
"""

from __future__ import annotations

from html.parser import HTMLParser

from sphinx.application import Sphinx

SOURCE = """{% from 'maatlog/components/image.html' import render_image with context %}
{{ render_image(image, fallback_src, alt=alt, css_class=css_class,
                presentation=presentation, has_rail=has_rail,
                featured_count=featured_count, early=early, high=high) }}"""


def render_component(app: Sphinx, image: object, **values: object) -> str:
    """Render the shared ``render_image`` macro with a Sphinx template context."""
    context: dict[str, object] = dict(
        image=image,
        fallback_src=None,
        alt="",
        css_class="",
        presentation="standalone",
        has_rail=None,
        featured_count=0,
        early=True,
        high=False,
    )
    context.update(values)
    return app.builder.templates.render_string(SOURCE, context)  # type: ignore[no-any-return, attr-defined]


def img_attrs(html: str) -> list[dict[str, str]]:
    """Collect ``<img>`` start-tag attributes with a plain HTML parser."""

    class Images(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.images: list[dict[str, str]] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag == "img":
                self.images.append({key: value or "" for key, value in attrs})

    parser = Images()
    parser.feed(html)
    return parser.images
