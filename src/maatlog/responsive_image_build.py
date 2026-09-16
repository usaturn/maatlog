"""Collect and generate responsive image variants in the parent Sphinx build.

The parent resolves every representative image and maattop once, asks the
registered :class:`~maatlog.image_contracts.ImageVariantGenerator` for width
variants, and freezes the result as a picklable snapshot on the environment.
Page writers later project that snapshot; they never generate anything
themselves, which is what keeps parallel workers from diverging.

Nothing here imports Pillow: disabled builds only read configuration, and
unsupported sources (SVG, GIF, animations) fall back to the original image
without ever touching an image backend.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final, cast
from urllib.parse import quote

from sphinx.application import Sphinx
from sphinx.builders import Builder
from sphinx.environment import BuildEnvironment

from .builders import is_full_html_builder
from .config import MaatlogConfig
from .domain import MaatlogDomain
from .errors import Diagnostic, MaatlogBuildError
from .image_contracts import (
    IMAGE_CODEC_MISSING,
    RESPONSIVE_CACHE_DIRNAME,
    RESPONSIVE_OUTPUT_SUBDIR,
    GeneratedVariant,
    ImageFormat,
    ImageProcessingError,
    ImageVariantGenerator,
    ResponsiveImageEntry,
    ResponsiveImageManifest,
    ResponsiveVariant,
    SourceImageIdentity,
    SourceImageProbe,
    VariantRequest,
    build_source_identity,
    resolve_variant_generator,
    responsive_images_enabled,
    select_candidate_widths,
    sniff_source_format,
)
from .images import (
    IMAGE_INVALID_EXPECTED,
    IMAGE_MISSING,
    IMAGE_MISSING_EXPECTED,
    ImageValidationError,
    validate_image_uri,
)
from .model import Post
from .responsive_image_output import IMAGE_INVALID_VARIANT, commit_owned_variants, publish_variants

__all__ = [
    "IMAGE_SOURCE_UNREADABLE",
    "finish_responsive_images",
    "prepare_responsive_images",
    "publish_responsive_images",
    "register_responsive_image_build",
    "responsive_manifest",
]

#: A source image that passed collection-time validation can no longer be read.
IMAGE_SOURCE_UNREADABLE: Final = "maatlog.image.source-unreadable"

_MANIFEST_ATTR: Final = "_maatlog_responsive_image_manifest"
_PUBLICATIONS_ATTR: Final = "_maatlog_responsive_publications"
_CURRENT_ATTR: Final = "_maatlog_responsive_current"

#: Synthetic source for revalidation: stored URIs are already srcdir-relative,
#: so resolution is anchored at the source root instead of a real document.
#: Diagnostics still name the actual owning document.
_SYNTHETIC_SOURCE_NAME: Final = "__maatlog_source__.rst"


def register_responsive_image_build(app: Sphinx) -> None:
    """Run variant generation on ``env-updated`` after the domain settles.

    Priority 600 lands after ``finalize_domain`` and generator resolution (both
    at the default 500), so the posts and maattop this step reads are final and
    the generator already exists. This step is also where a missing backend
    fails the build: ``describe_backend()`` runs before any source is collected,
    so an enabled build without Pillow fails here -- still on ``env-updated``,
    before any page is written -- even with zero images.
    Publication runs on ``write-started`` at 400, before the representative
    promotion (500) that owns the original images; ownership commit runs on
    ``build-finished`` at 900, after page and feed ownership.
    """
    app.connect("env-updated", prepare_responsive_images, priority=600)
    app.connect("write-started", publish_responsive_images, priority=400)
    app.connect("build-finished", finish_responsive_images, priority=900)


def responsive_manifest(env: BuildEnvironment) -> ResponsiveImageManifest:
    """Return this build's responsive image snapshot, or an empty mapping.

    Read-only: writers project the returned entries but never mutate them.
    """
    stored = env.__dict__.get(_MANIFEST_ATTR)
    if isinstance(stored, dict):
        return MappingProxyType(cast(dict[str, ResponsiveImageEntry], stored))
    return {}


def publish_responsive_images(app: Sphinx, builder: Builder) -> None:
    """Copy prepared variants from the cache to the output directory.

    Runs on ``write-started`` at priority 400, before the existing
    representative promotion at 500 that owns the original images. Disabled
    and non-full-HTML builds store an empty current set and touch nothing, so
    a first OFF build creates no output directory; a later ``finish`` step
    still cleans previously owned files for OFF full HTML.
    """
    config = MaatlogConfig.from_sphinx(app.config)
    if not responsive_images_enabled(config, builder):
        app.__dict__[_CURRENT_ATTR] = {}
        return
    stored_raw = app.__dict__.get(_PUBLICATIONS_ATTR, ())
    if isinstance(stored_raw, tuple):
        publications = cast(tuple[GeneratedVariant, ...], stored_raw)
    elif isinstance(stored_raw, list):
        publications = tuple(cast(list[GeneratedVariant], stored_raw))
    else:
        publications = ()
    cache_root = Path(app.doctreedir) / RESPONSIVE_CACHE_DIRNAME
    imagedir = str(getattr(builder, "imagedir", "_images"))
    output_root = Path(app.outdir) / imagedir / RESPONSIVE_OUTPUT_SUBDIR
    app.__dict__[_CURRENT_ATTR] = publish_variants(publications, cache_root=cache_root, output_root=output_root)


def finish_responsive_images(app: Sphinx, exception: Exception | None) -> None:
    """Record ownership and remove stale variants after a successful build.

    Runs on ``build-finished`` at priority 900, after page and feed ownership.
    A failed build (``exception`` set) keeps the old manifest and old files so
    the next build can retry. Non-full-HTML builders never touch ownership,
    even when they share an output directory with a full HTML build.
    """
    if exception is not None:
        return
    builder = app.builder
    if not is_full_html_builder(builder):
        return
    stored_raw = app.__dict__.get(_CURRENT_ATTR, {})
    if isinstance(stored_raw, Mapping):
        current: dict[str, str] = dict(cast(Mapping[str, str], stored_raw))
    else:
        current = {}
    imagedir = str(getattr(builder, "imagedir", "_images"))
    output_root = Path(app.outdir) / imagedir / RESPONSIVE_OUTPUT_SUBDIR
    commit_owned_variants(output_root=output_root, builder_name=builder.name, current=current)


def prepare_responsive_images(app: Sphinx, env: BuildEnvironment) -> list[str]:
    """Collect sources, generate variants, and freeze the manifest snapshot.

    Revalidates every stored URI against the current source tree, so a record
    that went stale (replaced by a symlink, deleted outside Sphinx's notice)
    fails the build instead of reaching the image backend. Unsupported formats
    and animations publish the original image: they leave no manifest entry and
    cost no probe, hash, or generate call.

    Returns maattop-owning docnames still in ``found_docs`` as an additional
    rewrite instruction: Sphinx's ``Builder.read()`` extends its write targets
    with every ``env-updated`` return value, so owners Sphinx considers up to
    date (for example an image whose bytes changed without an mtime bump) are
    still rewritten against the fresh snapshot. The snapshot and the
    publication queue are assigned only after every source succeeds, so a
    failure never exposes a partial manifest to writers.
    """
    env.__dict__[_MANIFEST_ATTR] = {}
    app.__dict__[_PUBLICATIONS_ATTR] = ()
    config = MaatlogConfig.from_sphinx(app.config)
    if not responsive_images_enabled(config, app.builder):
        return []
    generator = resolve_variant_generator(app)
    try:
        backend = generator.describe_backend()
    except ImageProcessingError as error:
        raise MaatlogBuildError([error.diagnostic]) from error
    domain = cast(MaatlogDomain, env.get_domain("maatlog"))
    posts = cast(dict[str, Post], domain.data.get("posts_by_docname", {}))
    maattop = cast(dict[str, dict[str, str]], domain.data.get("maattop_by_docname", {}))
    owners = _collect_source_owners(posts, maattop)
    post_uris = {post.image_uri for post in posts.values() if post.image_uri is not None}
    srcdir = Path(app.srcdir)
    cache_root = Path(app.doctreedir) / RESPONSIVE_CACHE_DIRNAME
    manifest: dict[str, ResponsiveImageEntry] = {}
    publications: list[GeneratedVariant] = []
    for uri in sorted(owners):
        owner = min(owners[uri])
        field = "maatlog-image" if uri in post_uris else "uri"
        path = _resolve_source(uri, owner=owner, field=field, srcdir=srcdir)
        sniffed = _sniff_source(path, uri=uri, owner=owner, field=field)
        if sniffed is None:
            continue
        if sniffed not in backend.supported_formats:
            raise MaatlogBuildError(
                [
                    Diagnostic(
                        code=IMAGE_CODEC_MISSING,
                        message=f"Image backend cannot encode {sniffed.value} sources",
                        source=owner,
                        field=field,
                        value=repr(uri),
                        expected=f"a {sniffed.value} codec in the image backend",
                    )
                ]
            )
        try:
            probe = generator.probe(path, image_format=sniffed)
        except ImageProcessingError as error:
            raise MaatlogBuildError([error.diagnostic]) from error
        if probe.is_multi_frame:
            continue
        identity = _identify_source(path, uri=uri, owner=owner, field=field, srcdir=srcdir)
        widths = select_candidate_widths(config.responsive_image_widths, probe.width)
        generated = [_generate_variant(generator, path, identity, probe, width, cache_root) for width in widths]
        manifest[identity.source_relpath] = ResponsiveImageEntry(
            identity=identity,
            natural_width=probe.width,
            natural_height=probe.height,
            image_format=probe.image_format,
            variants=tuple(
                ResponsiveVariant(
                    width=variant.width,
                    height=variant.height,
                    image_format=variant.image_format,
                    public_basename=variant.public_basename,
                )
                for variant in generated
            ),
        )
        publications.extend(generated)
    env.__dict__[_MANIFEST_ATTR] = manifest
    app.__dict__[_PUBLICATIONS_ATTR] = tuple(publications)
    found = set(env.found_docs)
    return sorted(docname for docname in maattop if docname in found)


def _collect_source_owners(
    posts: Mapping[str, Post],
    maattop: Mapping[str, Mapping[str, str]],
) -> dict[str, set[str]]:
    """Map each stored srcdir-relative URI to the docnames that reference it."""
    owners: dict[str, set[str]] = {}
    for docname, post in posts.items():
        if post.image_uri is not None:
            owners.setdefault(post.image_uri, set()).add(docname)
    for docname, entry in maattop.items():
        owners.setdefault(entry["uri"], set()).add(docname)
    return owners


def _resolve_source(uri: str, *, owner: str, field: str, srcdir: Path) -> Path:
    """Revalidate a stored URI; stale records are build errors, not fallbacks."""
    try:
        return validate_image_uri(
            quote(uri, safe="/"),
            source=srcdir / _SYNTHETIC_SOURCE_NAME,
            srcdir=srcdir,
        )
    except ImageValidationError as error:
        raise MaatlogBuildError(
            [
                Diagnostic(
                    code=error.code,
                    message=error.message,
                    source=owner,
                    field=field,
                    value=repr(uri),
                    expected=IMAGE_MISSING_EXPECTED if error.code == IMAGE_MISSING else IMAGE_INVALID_EXPECTED,
                )
            ]
        ) from error


def _sniff_source(path: Path, *, uri: str, owner: str, field: str) -> ImageFormat | None:
    """Identify *path* by content; ``None`` means "publish the original"."""
    try:
        return sniff_source_format(path)
    except OSError as error:
        raise MaatlogBuildError([_unreadable(uri, owner=owner, field=field, error=error)]) from error


def _identify_source(path: Path, *, uri: str, owner: str, field: str, srcdir: Path) -> SourceImageIdentity:
    try:
        return build_source_identity(path, srcdir=srcdir)
    except OSError as error:
        raise MaatlogBuildError([_unreadable(uri, owner=owner, field=field, error=error)]) from error


def _generate_variant(
    generator: ImageVariantGenerator,
    path: Path,
    identity: SourceImageIdentity,
    probe: SourceImageProbe,
    width: int,
    cache_root: Path,
) -> GeneratedVariant:
    try:
        variant = generator.generate(
            VariantRequest(
                source_path=path,
                identity=identity,
                probe=probe,
                width=width,
                cache_root=cache_root,
            )
        )
    except ImageProcessingError as error:
        raise MaatlogBuildError([error.diagnostic]) from error
    if variant.width != width or variant.image_format != probe.image_format or variant.height <= 0:
        raise MaatlogBuildError(
            [
                Diagnostic(
                    code=IMAGE_INVALID_VARIANT,
                    message=(
                        "Image backend returned a variant that does not match its request: "
                        f"{variant.public_basename!r}"
                    ),
                    value=variant.public_basename,
                    expected="a validated responsive variant artifact",
                )
            ]
        )
    return variant


def _unreadable(uri: str, *, owner: str, field: str, error: OSError) -> Diagnostic:
    return Diagnostic(
        code=IMAGE_SOURCE_UNREADABLE,
        message=f"Cannot read responsive image source: {error}",
        source=owner,
        field=field,
        value=repr(uri),
        expected="a readable image file",
    )
