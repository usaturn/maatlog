"""Rendering contract for the built-in ``author-links`` component.

#101 wires the component into no page template yet, so it is rendered directly
against the ``maatlog-base`` templates with the same Jinja environment kind
Sphinx uses (sandboxed, autoescape off — templates escape explicitly).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

import maatlog
from maatlog.views import AuthorLinkView

BASE_THEME = Path(maatlog.__file__).parent / "themes" / "maatlog-base"
COMPONENT = "maatlog/components/author-links.html"

ALL_TYPES = (
    AuthorLinkView(type="github", url="https://github.com/alice", label="GitHub", icon="github"),
    AuthorLinkView(type="x", url="https://x.com/alice", label="X", icon="x"),
    AuthorLinkView(type="bluesky", url="https://bsky.app/profile/alice", label="Bluesky", icon="bluesky"),
    AuthorLinkView(type="rss", url="https://example.com/atom.xml", label="RSS", icon="rss"),
    AuthorLinkView(type="website", url="https://example.com", label="Website", icon="website"),
    AuthorLinkView(type="linkedin", url="https://www.linkedin.com/in/alice", label="LinkedIn", icon="link"),
    AuthorLinkView(type="mastodon", url="https://example.social/@alice", label="mastodon", icon="link"),
)


def render_author_links(links: Sequence[AuthorLinkView]) -> str:
    environment = SandboxedEnvironment(loader=FileSystemLoader(str(BASE_THEME)))
    return environment.get_template(COMPONENT).render(maatlog_author_links=tuple(links))


def test_author_links_renders_one_link_per_entry() -> None:
    html = render_author_links(ALL_TYPES)

    assert 'data-maatlog-component="author-links"' in html
    assert 'class="maatlog-author-links"' in html
    assert html.count("<li") == len(ALL_TYPES)
    assert html.count("<svg") == len(ALL_TYPES)


def test_author_links_hides_decorative_icons_from_assistive_technology() -> None:
    html = render_author_links(ALL_TYPES)

    assert html.count('aria-hidden="true"') == len(ALL_TYPES)
    assert html.count('focusable="false"') == len(ALL_TYPES)


def test_author_links_gives_every_link_an_accessible_name() -> None:
    html = render_author_links(ALL_TYPES)

    assert html.count('class="maatlog-visually-hidden"') == len(ALL_TYPES)
    for link in ALL_TYPES:
        assert f'<span class="maatlog-visually-hidden">{link.label}</span>' in html


def test_author_links_marks_external_links() -> None:
    html = render_author_links(ALL_TYPES)

    assert html.count('rel="noopener"') == len(ALL_TYPES)
    assert 'href="https://github.com/alice"' in html


def test_author_links_follows_the_current_color() -> None:
    """light / dark はテーマ側のトークンで決まる。アイコンは currentColor に追従する。"""
    html = render_author_links(ALL_TYPES)

    assert "currentColor" in html
    assert 'fill="#' not in html
    assert 'stroke="#' not in html


def test_author_links_renders_a_distinct_icon_per_known_type() -> None:
    paths = {link.icon: _icon_markup(render_author_links([link])) for link in ALL_TYPES}

    assert len(set(paths.values())) == 6  # github / x / bluesky / rss / website / link
    assert paths["link"] == _icon_markup(render_author_links([ALL_TYPES[-1]]))


def test_author_links_falls_back_to_the_generic_icon() -> None:
    """未知 type と linkedin は同じ汎用アイコンを共有する。"""
    unknown = _icon_markup(render_author_links([ALL_TYPES[-1]]))
    linkedin = _icon_markup(render_author_links([ALL_TYPES[-2]]))

    assert unknown == linkedin


def test_author_links_renders_nothing_when_empty() -> None:
    assert render_author_links([]).strip() == ""


def test_author_links_renders_nothing_when_undefined() -> None:
    environment = SandboxedEnvironment(loader=FileSystemLoader(str(BASE_THEME)))

    assert environment.get_template(COMPONENT).render().strip() == ""


def test_author_links_escapes_untrusted_values() -> None:
    html = render_author_links(
        [
            AuthorLinkView(
                type="link",
                url='https://example.com/?a=1&b=2"><script>alert(1)</script>',
                label='"><script>alert(1)</script>',
                icon="link",
            )
        ]
    )

    assert "<script>" not in html
    assert "&amp;b=2" in html


def _icon_markup(html: str) -> str:
    start = html.index("<svg")
    return html[start : html.index("</svg>", start)]
