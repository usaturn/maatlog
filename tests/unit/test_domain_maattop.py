"""Unit tests for MaatlogDomain maattop storage."""

from __future__ import annotations

from unittest.mock import MagicMock

from maatlog.domain import MaatlogDomain


def _make_domain() -> MaatlogDomain:
    env = MagicMock()
    env.docname = "post"
    domain = MaatlogDomain.__new__(MaatlogDomain)
    domain.env = env
    # copy initial_data (deep enough for our tests)
    domain.data = {
        "posts_by_docname": {},
        "post_list_docnames": set(),
        "maattop_by_docname": {},
        "index": None,
        "generated_docnames": set(),
        "generated_outputs": {"pages": set(), "feeds": set()},
    }
    return domain


def test_note_maattop_stores_uri_and_alt() -> None:
    domain = _make_domain()
    domain.note_maattop("posts/article", "images/hero.png", "Hero")
    result = domain.maattop_for("posts/article")
    assert result == {"uri": "images/hero.png", "alt": "Hero"}


def test_maattop_for_returns_none_when_absent() -> None:
    domain = _make_domain()
    assert domain.maattop_for("posts/no-image") is None


def test_clear_doc_removes_maattop() -> None:
    domain = _make_domain()
    domain.note_maattop("posts/article", "images/hero.png", "Hero")
    domain.clear_doc("posts/article")
    assert domain.maattop_for("posts/article") is None


def test_merge_domaindata_copies_maattop() -> None:
    domain = _make_domain()
    other_data: dict[str, object] = {
        "posts_by_docname": {},
        "post_list_docnames": set(),
        "maattop_by_docname": {"posts/article": {"uri": "images/hero.png", "alt": "Hero"}},
        "index": None,
        "generated_docnames": set(),
        "generated_outputs": {"pages": set(), "feeds": set()},
    }
    domain.merge_domaindata({"posts/article"}, other_data)
    assert domain.maattop_for("posts/article") == {"uri": "images/hero.png", "alt": "Hero"}


def test_merge_domaindata_removes_maattop_when_absent_in_other() -> None:
    domain = _make_domain()
    domain.note_maattop("posts/article", "images/hero.png", "Hero")
    other_data: dict[str, object] = {
        "posts_by_docname": {},
        "post_list_docnames": set(),
        "maattop_by_docname": {},
        "index": None,
        "generated_docnames": set(),
        "generated_outputs": {"pages": set(), "feeds": set()},
    }
    domain.merge_domaindata({"posts/article"}, other_data)
    assert domain.maattop_for("posts/article") is None
