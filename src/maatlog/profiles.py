"""Author profile projection: statistics, avatars, About bodies, and views.

Profiles come from configuration, not from documents, so nothing here is stored
on the domain index. Statistics are recomputed from the published index each
build, which keeps the domain pickle, ``env-merge-info`` and ``env-purge-doc``
free of profile state.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from sphinx.builders import Builder
from sphinx.util.osutil import relative_uri

from .authors import AuthorProfile
from .config import TaxonomyAxis
from .directives import post_list
from .errors import Diagnostic, MaatlogBuildError
from .html_metadata import strip_leading_document_title
from .images import (
    IMAGE_INVALID_EXPECTED,
    IMAGE_MISSING,
    IMAGE_MISSING_EXPECTED,
    ImageValidationError,
    validate_image_uri,
)
from .model import Post
from .references import archive_docname
from .taxonomy import DomainIndex
from .views import (
    AuthorProfileView,
    AuthorStatsView,
    AuthorSummaryView,
    PostTaxonomiesView,
    TaxonomyLinkView,
    author_link_views,
    image_url_for,
    post_card_view,
    relative_page_url_for,
)

PROFILE_UNKNOWN_CODE = "maatlog.author.profile-unknown"
FEATURED_UNKNOWN_CODE = "maatlog.author.featured-unknown"
FEATURED_FOREIGN_CODE = "maatlog.author.featured-foreign"
ABOUT_UNKNOWN_CODE = "maatlog.author.about-unknown"

#: Initials never exceed two characters ("Alice Anderson" -> "AA").
_MAX_INITIALS = 2


@dataclass(frozen=True, slots=True)
class ResolvedProfiles:
    """Profile data that needed the build environment to resolve.

    ``avatars`` maps an author id to the srcdir-relative image path Sphinx image
    maps use (the same key shape as ``ImageCollector``). Authors that configure
    no avatar are absent.
    """

    avatars: Mapping[str, str]


def author_initials(display_name: str) -> str:
    """Return up to two uppercase initials derived from *display_name*.

    Used when a profile configures no avatar. Returns an empty string when the
    display name carries no words; the theme then draws an empty avatar frame.
    """
    words = [word for word in display_name.split() if word]
    return "".join(word[0].upper() for word in words[:_MAX_INITIALS])


def author_stats(published: Sequence[Post], author_id: str, *, timezone: ZoneInfo) -> AuthorStatsView:
    """Compute post count, first writing year, and latest publication for *author_id*.

    *published* must be the domain index's published posts, which are guaranteed
    to carry ``published_at``. Years are resolved in ``maatlog_timezone`` and the
    latest post is reported in ``maatlog_timezone`` as well, so both agree with
    the month archives (:func:`maatlog.taxonomy._project_months`).
    """
    dates = [post.published_at for post in published if author_id in post.authors and post.published_at is not None]
    if not dates:
        return AuthorStatsView(post_count=0, writing_since=None, latest_post=None)
    return AuthorStatsView(
        post_count=len(dates),
        writing_since=min(dates).astimezone(timezone).year,
        latest_post=max(dates).astimezone(timezone),
    )


def resolve_profiles(
    profiles: Mapping[str, AuthorProfile],
    *,
    authors: Mapping[str, str] | None,
    index: DomainIndex,
    known_docnames: Collection[str],
    srcdir: Path,
) -> ResolvedProfiles:
    """Validate profile cross-references and resolve avatar paths.

    Every problem is collected before raising, so one build reports all of them.

    The ``maatlog_authors`` membership check runs only when ``maatlog_authors``
    is configured. When it is ``None`` author ids are registered dynamically from
    posts, so there is no static set to check against and an author whose posts
    are all drafts would be reported wrongly.

    Raises:
        MaatlogBuildError: with every profile diagnostic found.
    """
    diagnostics: list[Diagnostic] = []
    avatars: dict[str, str] = {}
    author_members = index.members.get(TaxonomyAxis.AUTHOR, {})
    published_slugs = {post.slug for post in index.published}

    for author_id in sorted(profiles):
        profile = profiles[author_id]
        field = f"maatlog_author_profiles.{author_id}"

        if authors is not None and author_id not in authors:
            diagnostics.append(
                Diagnostic(
                    code=PROFILE_UNKNOWN_CODE,
                    message=f"Author profile {author_id!r} has no entry in maatlog_authors",
                    field=field,
                    value=repr(author_id),
                    expected="an author id present in maatlog_authors",
                )
            )

        owned = set(author_members.get(author_id, ()))
        for slug in profile.featured_posts:
            if slug not in published_slugs:
                diagnostics.append(
                    Diagnostic(
                        code=FEATURED_UNKNOWN_CODE,
                        message=f"Featured post {slug!r} is not a published post",
                        field=f"{field}.featured_posts",
                        value=repr(slug),
                        expected="the slug of a published post",
                    )
                )
                continue
            if slug not in owned:
                diagnostics.append(
                    Diagnostic(
                        code=FEATURED_FOREIGN_CODE,
                        message=f"Featured post {slug!r} does not belong to author {author_id!r}",
                        field=f"{field}.featured_posts",
                        value=repr(slug),
                        expected=f"a published post authored by {author_id!r}",
                    )
                )

        if profile.about_docname is not None and profile.about_docname not in known_docnames:
            diagnostics.append(
                Diagnostic(
                    code=ABOUT_UNKNOWN_CODE,
                    message=f"About document {profile.about_docname!r} does not exist",
                    field=f"{field}.about_docname",
                    value=repr(profile.about_docname),
                    expected="an existing Sphinx document name",
                )
            )

        if profile.avatar is not None:
            relative = _resolve_avatar(profile.avatar, field=field, srcdir=srcdir, diagnostics=diagnostics)
            if relative is not None:
                avatars[author_id] = relative

    if diagnostics:
        raise MaatlogBuildError(diagnostics)
    return ResolvedProfiles(avatars=avatars)


def _resolve_avatar(uri: str, *, field: str, srcdir: Path, diagnostics: list[Diagnostic]) -> str | None:
    """Validate an avatar URI against the same rules as representative images.

    ``validate_image_uri`` resolves relative to ``source.parent``; passing
    ``srcdir / "conf.py"`` therefore makes the URI source-root relative, which is
    the right shape for a configuration value with no owning document.
    """
    try:
        candidate = validate_image_uri(uri, source=srcdir / "conf.py", srcdir=srcdir)
    except ImageValidationError as error:
        expected = IMAGE_MISSING_EXPECTED if error.code == IMAGE_MISSING else IMAGE_INVALID_EXPECTED
        diagnostics.append(
            Diagnostic(
                code=error.code,
                message=error.message,
                field=f"{field}.avatar",
                value=repr(uri),
                expected=expected,
            )
        )
        return None
    # Sphinx image maps use paths relative to srcdir (same keys as ImageCollector).
    return candidate.relative_to(srcdir.resolve()).as_posix()


def profile_docname(root: str, author_id: str) -> str:
    """Docname of an author's profile page (page 1 of that author's archive)."""
    return archive_docname(root, TaxonomyAxis.AUTHOR, author_id, page=1)


def register_avatars(env: object, avatars: Mapping[str, str], *, root: str) -> None:
    """Register avatar files on ``env.images`` so Sphinx copies them to ``_images``.

    An avatar has no owning document, so the profile page's docname stands in as
    a synthetic owner. ``env.images`` is pickled with the environment, so the
    previous association is purged first and a configuration change never leaves
    a stale entry behind.
    """
    images = getattr(env, "images", None)
    if images is None:
        return
    for author_id, relative in avatars.items():
        owner = profile_docname(root, author_id)
        images.purge_doc(owner)
        images.add_file(owner, relative)


def mark_about_documents_orphan(env: object, profiles: Mapping[str, AuthorProfile]) -> None:
    """Flag every configured About document as an orphan.

    About documents are referenced from generated profile pages, not from a
    toctree, so ``env.check_consistency()`` would report them as not included
    anywhere. Setting the same metadata key ``:orphan:`` sets keeps the contract
    in the extension instead of asking every author to remember a directive.

    ``check_consistency()`` runs after ``Builder.read()`` returns while
    ``env-updated`` fires inside it, so this always lands in time.
    """
    metadata = getattr(env, "metadata", None)
    if metadata is None:
        return
    for profile in profiles.values():
        if profile.about_docname is None:
            continue
        metadata.setdefault(profile.about_docname, {})["orphan"] = True


def render_about_body(builder: Builder, *, about_docname: str, from_docname: str) -> str:
    """Render the About document's body as it should appear on *from_docname*.

    The document is re-resolved with the embedding page as the reference origin,
    so every relative URI (cross-references, images, downloads) is correct for the
    page the body lands on. Rendering the About page's own body and reusing it
    would emit URIs relative to the About document instead, which breaks links and
    images whenever the two documents sit at different depths. Post-list cards
    inside the body keep this guarantee too: their stored source docname is
    temporarily cleared so their URIs also come from the embedding page.

    ``env.get_doctree`` returns a freshly unpickled tree, so nothing shared is
    mutated. ``apply_post_transforms`` re-emits ``doctree-resolved`` for this
    document; MaatLog's own handler is idempotent.
    """
    env = builder.env
    html = cast(Any, builder)
    doctree = env.get_doctree(about_docname)
    env.apply_post_transforms(doctree, from_docname)
    html.post_process_images(doctree)

    target = builder.get_target_uri(from_docname)
    previous = (
        html.current_docname,
        html.imgpath,
        html.dlpath,
        html.secnumbers,
        html.fignumbers,
    )
    # post_list nodes keep the source document's docname as a fixed attribute
    # and the HTML visitor always prefers it. Strip it here so card URIs fall
    # back to ``builder.current_docname``, which the try block sets to the
    # embedding page.
    post_lists = list(doctree.findall(post_list))
    previous_docnames = [node.get("docname") for node in post_lists]
    for node in post_lists:
        if "docname" in node:
            del node["docname"]
    try:
        doctree.settings = html.docsettings
        html.current_docname = from_docname
        html.imgpath = relative_uri(target, html.imagedir)
        html.dlpath = relative_uri(target, "_downloads")
        # Numbering belongs to the About document even though URIs do not.
        html.secnumbers = env.toc_secnumbers.get(about_docname, {})
        html.fignumbers = env.toc_fignumbers.get(about_docname, {})
        visitor = html.create_translator(doctree, builder)
        doctree.walkabout(visitor)
        body = "".join(cast(list[str], visitor.fragment))
    finally:
        for node, original in zip(post_lists, previous_docnames, strict=True):
            if original is not None:
                node["docname"] = original
        (
            html.current_docname,
            html.imgpath,
            html.dlpath,
            html.secnumbers,
            html.fignumbers,
        ) = previous

    title_node = env.titles.get(about_docname)
    if title_node is None:
        return body
    return strip_leading_document_title(body, document_title=title_node.astext())


def build_profile_view(
    builder: Builder,
    *,
    author_id: str,
    display_name: str,
    profile: AuthorProfile,
    index: DomainIndex,
    avatar_uri: str | None,
    from_docname: str,
    timezone: ZoneInfo,
    linker: Callable[[Post], PostTaxonomiesView] | None = None,
) -> AuthorProfileView:
    """Assemble the template-facing profile view for one author.

    Featured cards resolve their URLs relative to *from_docname*, exactly like the
    archive cards on the same page. ``resolve_profiles`` has already rejected any
    featured slug that is not a published post of this author, so the lookup here
    cannot silently drop an entry the author asked for.
    """
    by_slug = {post.slug: post for post in index.published}
    featured = tuple(
        post_card_view(
            by_slug[slug],
            page_url=relative_page_url_for(builder, from_docname, by_slug[slug].docname),
            image_url=image_url_for(builder, from_docname, by_slug[slug].image_uri),
            taxonomies=linker(by_slug[slug]) if linker is not None else None,
        )
        for slug in profile.featured_posts
        if slug in by_slug
    )
    about_html: str | None = None
    if profile.about_docname is not None:
        about_html = render_about_body(builder, about_docname=profile.about_docname, from_docname=from_docname)
    return AuthorProfileView(
        slug=author_id,
        display_name=display_name,
        role=profile.role,
        avatar_url=image_url_for(builder, from_docname, avatar_uri),
        initials=author_initials(display_name),
        bio_short=profile.bio_short,
        interests=profile.interests,
        links=author_link_views(profile),
        about_html=about_html,
        featured=featured,
        stats=author_stats(index.published, author_id, timezone=timezone),
    )


def author_summary_views(
    builder: Builder,
    *,
    authors: Sequence[TaxonomyLinkView],
    profiles: Mapping[str, AuthorProfile],
    avatars: Mapping[str, str],
    from_docname: str,
) -> tuple[AuthorSummaryView, ...]:
    """Project resolved author links into the right rail's summaries.

    *authors* carries the id, the display name and the profile URL already
    resolved for the page being rendered (``PostTaxonomyLinker.for_authors``),
    so this never re-implements label lookup or archive URL construction, and
    the order it is given in is the order the rail draws.

    An author with no configured profile still gets a summary: the display name
    alone is more useful to a reader than an empty rail, and it keeps
    ``maatlog_author_profiles`` optional.
    """
    return tuple(
        AuthorSummaryView(
            slug=author.id,
            display_name=author.label,
            avatar_url=image_url_for(builder, from_docname, avatars.get(author.id)),
            initials=author_initials(author.label),
            bio_short=profile.bio_short if profile is not None else None,
            links=author_link_views(profile),
            profile_url=author.url,
        )
        for author, profile in ((author, profiles.get(author.id)) for author in authors)
    )
