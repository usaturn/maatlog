from __future__ import annotations

import pytest

from maatlog.social_metadata import SocialMetadataView, dispatcher, serialize_json_ld
from maatlog.views import MaatlogTemplateContext, PageKind


@pytest.mark.parametrize(
    ("page_kind", "expected"),
    [("post", "post"), ("profile", "profile"), ("home", "site"), ("archive", "site")],
)
def test_dispatcher_routes_to_one_owned_projector(
    monkeypatch: pytest.MonkeyPatch, page_kind: PageKind, expected: str
) -> None:
    calls: list[tuple[str, str | None]] = []
    # json_ld only accepts serialize_json_ld() output, so the marker that identifies the
    # projector that ran has to be carried inside a real serialized payload.
    marker = serialize_json_ld({"@type": expected})

    def projector(context: MaatlogTemplateContext, *, page_url: str | None) -> SocialMetadataView:
        calls.append((expected, page_url))
        return SocialMetadataView(json_ld=marker)

    def fail(*args: object, **kwargs: object) -> SocialMetadataView:
        raise AssertionError("unowned projector must not run")

    for owner in ("post", "profile", "site"):
        monkeypatch.setattr(dispatcher, f"project_{owner}_metadata", fail)
    monkeypatch.setattr(dispatcher, f"project_{expected}_metadata", projector)
    result = dispatcher.project_social_metadata(
        MaatlogTemplateContext(page_kind=page_kind),
        page_url="https://example.test/page.html",
    )
    assert result.json_ld == marker
    assert calls == [(expected, "https://example.test/page.html")]


def test_normal_page_dispatches_nowhere(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> SocialMetadataView:
        raise AssertionError("projector must not run")

    monkeypatch.setattr(dispatcher, "project_post_metadata", fail)
    monkeypatch.setattr(dispatcher, "project_profile_metadata", fail)
    monkeypatch.setattr(dispatcher, "project_site_metadata", fail)
    assert dispatcher.project_social_metadata(MaatlogTemplateContext(), page_url=None) == SocialMetadataView()
