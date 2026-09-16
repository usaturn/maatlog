"""Integration coverage for the shared responsive image component (issue #216)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pytest
from conftest import SphinxFactory
from fixtures.responsive_image_fixtures import sample_responsive_image_entry, sample_responsive_image_view
from fixtures.responsive_image_html import img_attrs, render_component
from sphinx.application import Sphinx

from maatlog.image_contracts import ImageUsage


def test_mapping_keeps_all_candidates(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files={"index.rst": "Index\n=====\n"}, theme="maatlog-base")
    view = sample_responsive_image_view()
    (attrs,) = img_attrs(render_component(app, asdict(view), fallback_src="old.png"))
    assert attrs["src"] == view.src
    assert attrs["srcset"] == view.srcset
    assert attrs["sizes"] == "100vw"
    assert (attrs["width"], attrs["height"]) == ("1600", "900")
    assert attrs["data-maatlog-srcset"] == "w-v1"


def test_absent_view_preserves_fallback(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files={"index.rst": "Index\n=====\n"}, theme="maatlog-base")
    (attrs,) = img_attrs(render_component(app, None, fallback_src='old&".png', alt='A " B < C', css_class="existing"))
    assert attrs == {"src": 'old&".png', "alt": 'A " B < C', "class": "existing"}
    assert img_attrs(render_component(app, None, fallback_src=None)) == []


@pytest.mark.parametrize("usage", list(ImageUsage))
def test_all_usages_render_base_sizes(make_sphinx: SphinxFactory, usage: ImageUsage) -> None:
    app = make_sphinx(files={"index.rst": "Index\n=====\n"}, theme="maatlog-base")
    view = sample_responsive_image_view(usage)
    (attrs,) = img_attrs(render_component(app, view, fallback_src="old.png"))
    assert attrs["src"] == view.src
    assert attrs["srcset"] == view.srcset
    assert attrs["sizes"] == "100vw"
    assert attrs["loading"] == "eager"
    assert attrs["fetchpriority"] == "auto"
    assert attrs["decoding"] == "async"
    assert attrs["data-maatlog-srcset"] == "w-v1"


def test_single_candidate_small_image(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files={"index.rst": "Index\n=====\n"}, theme="maatlog-base")
    entry = sample_responsive_image_entry(natural_width=480, natural_height=270, widths=(480,))
    view = sample_responsive_image_view(entry=entry)
    (attrs,) = img_attrs(render_component(app, view, fallback_src="old.png"))
    assert attrs["src"] == view.src
    assert attrs["srcset"] == view.srcset
    assert "," not in attrs["srcset"]
    assert (attrs["width"], attrs["height"]) == ("480", "270")


def test_portrait_dimensions(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files={"index.rst": "Index\n=====\n"}, theme="maatlog-base")
    entry = sample_responsive_image_entry(natural_width=900, natural_height=1600, widths=(480, 900))
    view = sample_responsive_image_view(entry=entry)
    (attrs,) = img_attrs(render_component(app, asdict(view), fallback_src="old.png"))
    assert (attrs["width"], attrs["height"]) == ("900", "1600")
    assert attrs["srcset"] == view.srcset


@pytest.mark.parametrize("as_mapping", [False, True])
def test_dataclass_and_mapping_render_same_dom(make_sphinx: SphinxFactory, as_mapping: bool) -> None:
    app = make_sphinx(files={"index.rst": "Index\n=====\n"}, theme="maatlog-base")
    view = sample_responsive_image_view()
    image: Any = asdict(view) if as_mapping else view
    (attrs,) = img_attrs(render_component(app, image, fallback_src="old.png"))
    assert attrs["src"] == view.src
    assert attrs["srcset"] == view.srcset
    assert attrs["sizes"] == "100vw"
    assert (attrs["width"], attrs["height"]) == ("1600", "900")


@pytest.mark.parametrize("fallback", ["cover.svg", "anim.gif", "old.png"])
def test_fallback_formats_keep_single_src(make_sphinx: SphinxFactory, fallback: str) -> None:
    app = make_sphinx(files={"index.rst": "Index\n=====\n"}, theme="maatlog-base")
    (attrs,) = img_attrs(render_component(app, None, fallback_src=fallback, alt="Alt", css_class="cls"))
    assert attrs == {"src": fallback, "alt": "Alt", "class": "cls"}
    assert "srcset" not in attrs
    assert "sizes" not in attrs
    assert "width" not in attrs
    assert "height" not in attrs


def test_missing_attrs_render_without_raising(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files={"index.rst": "Index\n=====\n"}, theme="maatlog-base")
    html = render_component(app, {"src": "only-src.png"}, fallback_src="old.png")
    (attrs,) = img_attrs(html)
    assert attrs["src"] == "only-src.png"
    assert attrs["srcset"] == ""


def test_malicious_usage_value_stays_inert(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files={"index.rst": "Index\n=====\n"}, theme="maatlog-base")
    view = sample_responsive_image_view()
    image = asdict(view)
    image["usage"] = '"><script>alert(1)</script>'
    html = render_component(app, image, fallback_src="old.png")
    (attrs,) = img_attrs(html)
    assert attrs["sizes"] == "100vw"
    assert attrs["loading"] == "eager"
    assert attrs["fetchpriority"] == "auto"
    assert "<script>" not in html


def test_escape_malicious_mapping(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files={"index.rst": "Index\n=====\n"}, theme="maatlog-base")
    src = 'a"b<c&d>.png'
    candidate_url = 'v"x<y&z>.png'
    alt = 'A " B < C & D'
    css_class = 'c"l<a&s'
    width = '1600"><script>alert(1)</script>'
    height = '900"&<>.png'
    image = {
        "src": src,
        "candidates": [{"url": candidate_url, "width": 480}],
        "width": width,
        "height": height,
        "usage": "post-top",
    }
    html = render_component(app, image, fallback_src="old.png", alt=alt, css_class=css_class)
    (attrs,) = img_attrs(html)
    assert attrs["src"] == src
    assert attrs["srcset"] == f"{candidate_url} 480w"
    assert attrs["alt"] == alt
    assert attrs["class"] == css_class
    assert attrs["width"] == width
    assert attrs["height"] == height
    assert set(attrs) == {
        "src",
        "srcset",
        "sizes",
        "width",
        "height",
        "alt",
        "loading",
        "fetchpriority",
        "decoding",
        "class",
        "data-maatlog-srcset",
    }
    assert "<script>" not in html


@pytest.mark.parametrize(
    ("early", "high", "loading", "fetchpriority"),
    [(True, False, "eager", "auto"), (False, False, "lazy", "auto"), (True, True, "eager", "high")],
)
def test_loading_and_fetchpriority_flags(
    make_sphinx: SphinxFactory, early: bool, high: bool, loading: str, fetchpriority: str
) -> None:
    app = make_sphinx(files={"index.rst": "Index\n=====\n"}, theme="maatlog-base")
    view = sample_responsive_image_view()
    (attrs,) = img_attrs(render_component(app, view, fallback_src="old.png", early=early, high=high))
    assert attrs["loading"] == loading
    assert attrs["fetchpriority"] == fetchpriority


def test_base_policy_macros_return_plain_strings(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files={"index.rst": "Index\n=====\n"}, theme="maatlog-base")
    templates = app.builder.templates
    sizes = templates.render_string(
        "{% from 'maatlog/components/image-policy.html' import image_sizes with context %}{{ image_sizes(usage) }}",
        {"usage": "post-top"},
    )
    assert sizes == "100vw"
    loading = templates.render_string(
        "{% from 'maatlog/components/image-policy.html' import image_loading with context %}"
        "{{ image_loading(usage, early) }}",
        {"usage": "post-top", "early": False},
    )
    assert loading == "lazy"
    priority = templates.render_string(
        "{% from 'maatlog/components/image-policy.html' import image_fetchpriority with context %}"
        "{{ image_fetchpriority(usage, high) }}",
        {"usage": "post-top", "high": True},
    )
    assert priority == "high"


HOSTILE_POLICY = """\
{% macro image_sizes(usage, presentation='standalone', has_rail=none, featured_count=0) -%}
123px" onload="bad{%- endmacro %}
{% macro image_loading(usage, early=true) -%}lazy" autofocus="x{%- endmacro %}
{% macro image_fetchpriority(usage, high=false) -%}auto" data-pwn="1{%- endmacro %}
"""

SAFE_POLICY = """\
{% macro image_sizes(usage, presentation='standalone', has_rail=none, featured_count=0) -%}
{{ '50vw" onload="evil'|safe }}{%- endmacro %}
{% macro image_loading(usage, early=true) -%}eager{%- endmacro %}
{% macro image_fetchpriority(usage, high=false) -%}auto{%- endmacro %}
"""


def _make_sphinx_with_policy(make_sphinx: SphinxFactory, policy_source: str) -> Sphinx:
    return make_sphinx(
        files={
            "index.rst": "Index\n=====\n",
            "_templates/maatlog/components/image-policy.html": policy_source,
        },
        theme="maatlog-base",
        config={"templates_path": ["_templates"]},
    )


def test_hostile_policy_output_is_escaped(make_sphinx: SphinxFactory) -> None:
    app = _make_sphinx_with_policy(make_sphinx, HOSTILE_POLICY)
    view = sample_responsive_image_view()
    html = render_component(app, view, fallback_src="old.png")
    (attrs,) = img_attrs(html)
    assert attrs["sizes"] == '123px" onload="bad'
    assert attrs["loading"] == 'lazy" autofocus="x'
    assert attrs["fetchpriority"] == 'auto" data-pwn="1'
    assert "onload" not in attrs
    assert "autofocus" not in attrs
    assert "data-pwn" not in attrs
    assert "&#34;" in html  # Jinja escapes double quotes as &#34;
    assert 'onload="bad' not in html
    assert 'autofocus="x' not in html
    assert 'data-pwn="1' not in html


def test_safe_policy_output_is_still_escaped(make_sphinx: SphinxFactory) -> None:
    app = _make_sphinx_with_policy(make_sphinx, SAFE_POLICY)
    view = sample_responsive_image_view()
    html = render_component(app, view, fallback_src="old.png")
    (attrs,) = img_attrs(html)
    assert attrs["sizes"] == '50vw" onload="evil'
    assert "onload" not in attrs
    assert 'onload="evil' not in html
