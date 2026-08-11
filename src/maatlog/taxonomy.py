from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping

from pydantic import BaseModel, ConfigDict, field_validator

from .config import MaatlogConfig, TaxonomyAxis
from .errors import Diagnostic, MaatlogBuildError
from .model import Post, PublicationStatus

_AXIS_METADATA_FIELD = {
    TaxonomyAxis.TAG: "maatlog-tags",
    TaxonomyAxis.CATEGORY: "maatlog-categories",
    TaxonomyAxis.AUTHOR: "maatlog-authors",
}


class DomainIndex(BaseModel):
    """Pickle-friendly domain index (plain dicts; model itself is frozen)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    docname_by_slug: Mapping[str, str]
    members: Mapping[TaxonomyAxis, Mapping[str, tuple[str, ...]]]
    labels: Mapping[TaxonomyAxis, Mapping[str, str]]
    published: tuple[Post, ...]

    @field_validator("docname_by_slug")
    @classmethod
    def _copy_docname_by_slug(cls, value: Mapping[str, str]) -> dict[str, str]:
        # Plain dict so Sphinx can pickle domaindata; frozen model blocks field reassignment.
        return dict(value)

    @field_validator("members")
    @classmethod
    def _copy_members(
        cls, value: Mapping[TaxonomyAxis, Mapping[str, tuple[str, ...]]]
    ) -> dict[TaxonomyAxis, dict[str, tuple[str, ...]]]:
        return {axis: {key: tuple(slugs) for key, slugs in mapping.items()} for axis, mapping in value.items()}

    @field_validator("labels")
    @classmethod
    def _copy_labels(cls, value: Mapping[TaxonomyAxis, Mapping[str, str]]) -> dict[TaxonomyAxis, dict[str, str]]:
        return {axis: dict(mapping) for axis, mapping in value.items()}


def published_sort_key(post: Post) -> tuple[float, str, str]:
    assert post.published_at is not None
    return (-post.published_at.timestamp(), post.slug, post.docname)


def build_domain_index(posts: Mapping[str, Post], config: MaatlogConfig) -> DomainIndex:
    _assert_unique_slugs(posts.values())

    published = tuple(
        sorted(
            (post for post in posts.values() if post.status is PublicationStatus.PUBLISHED),
            key=published_sort_key,
        )
    )
    diagnostics: list[Diagnostic] = []
    tag_members, tag_labels = _project_axis(
        published,
        axis=TaxonomyAxis.TAG,
        ids_for_post=lambda post: post.tags,
        configured=config.tags,
        diagnostics=diagnostics,
    )
    category_members, category_labels = _project_axis(
        published,
        axis=TaxonomyAxis.CATEGORY,
        ids_for_post=lambda post: post.categories,
        configured=config.categories,
        diagnostics=diagnostics,
    )
    author_members, author_labels = _project_axis(
        published,
        axis=TaxonomyAxis.AUTHOR,
        ids_for_post=lambda post: post.authors,
        configured=config.authors,
        diagnostics=diagnostics,
    )
    month_members, month_labels = _project_months(published, config)

    if diagnostics:
        raise MaatlogBuildError(diagnostics)

    docname_by_slug = {post.slug: post.docname for post in sorted(posts.values(), key=lambda item: item.slug)}
    return DomainIndex(
        docname_by_slug=docname_by_slug,
        members={
            TaxonomyAxis.TAG: tag_members,
            TaxonomyAxis.CATEGORY: category_members,
            TaxonomyAxis.AUTHOR: author_members,
            TaxonomyAxis.MONTH: month_members,
        },
        labels={
            TaxonomyAxis.TAG: tag_labels,
            TaxonomyAxis.CATEGORY: category_labels,
            TaxonomyAxis.AUTHOR: author_labels,
            TaxonomyAxis.MONTH: month_labels,
        },
        published=published,
    )


def _assert_unique_slugs(posts: Iterable[Post]) -> None:
    by_slug: dict[str, list[Post]] = defaultdict(list)
    for post in posts:
        by_slug[post.slug].append(post)

    diagnostics: list[Diagnostic] = []
    for slug, group in sorted(by_slug.items()):
        if len(group) < 2:
            continue
        locations = ", ".join(sorted(item.source_path for item in group))
        diagnostics.append(
            Diagnostic(
                code="maatlog.slug.duplicate",
                message=f"Duplicate slug {slug!r} found in {locations}",
                field="maatlog-slug",
                value=repr(slug),
                expected="a unique slug across all posts",
            )
        )
    if diagnostics:
        raise MaatlogBuildError(diagnostics)


def _project_axis(
    published: tuple[Post, ...],
    *,
    axis: TaxonomyAxis,
    ids_for_post: Callable[[Post], tuple[str, ...]],
    configured: Mapping[str, str] | None,
    diagnostics: list[Diagnostic],
) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    members: dict[str, list[str]] = defaultdict(list)
    for post in published:
        for taxonomy_id in ids_for_post(post):
            if configured is not None and taxonomy_id not in configured:
                diagnostics.append(
                    Diagnostic(
                        code="maatlog.taxonomy.undefined",
                        message="Taxonomy ID is not configured",
                        source=post.source_path,
                        field=_AXIS_METADATA_FIELD[axis],
                        value=repr(taxonomy_id),
                        expected="an ID present in the corresponding MaatLog taxonomy config",
                    )
                )
                continue
            if post.slug not in members[taxonomy_id]:
                members[taxonomy_id].append(post.slug)

    ordered_members = {key: tuple(slugs) for key, slugs in sorted(members.items())}
    if configured is None:
        ordered_labels = {key: key for key in ordered_members}
    else:
        ordered_labels = {key: configured[key] for key in ordered_members}
    return ordered_members, ordered_labels


def _project_months(
    published: tuple[Post, ...], config: MaatlogConfig
) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    members: dict[str, list[str]] = defaultdict(list)
    for post in published:
        assert post.published_at is not None
        month = post.published_at.astimezone(config.timezone).strftime("%Y-%m")
        if post.slug not in members[month]:
            members[month].append(post.slug)
    ordered_members = {key: tuple(slugs) for key, slugs in sorted(members.items())}
    ordered_labels = {key: key for key in ordered_members}
    return ordered_members, ordered_labels
