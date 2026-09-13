"""Route page contexts to their fixed metadata owners."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .post import project_post_metadata
from .profile import project_profile_metadata
from .site import project_site_metadata
from .views import SocialMetadataView

if TYPE_CHECKING:
    from maatlog.views import MaatlogTemplateContext


def project_social_metadata(
    context: MaatlogTemplateContext,
    *,
    page_url: str | None,
) -> SocialMetadataView:
    if context.page_kind == "post":
        return project_post_metadata(context, page_url=page_url)
    if context.page_kind == "profile":
        return project_profile_metadata(context, page_url=page_url)
    if context.page_kind in {"home", "archive"}:
        return project_site_metadata(context, page_url=page_url)
    return SocialMetadataView()
