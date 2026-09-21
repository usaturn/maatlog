"""Worker-local shared Sphinx builds for integration tests (issue #364).

``BuiltProjects`` caches successful builds keyed by the explicit inputs
merged with defaults and returns immutable snapshot objects. The key does not
capture ambient state — process environment beyond the keyed
``source_date_epoch``, package state, or other runtime conditions — so tests
that vary those need independent builds. Returned objects and their mappings
are immutable, but the build tree they point at stays writable; see
:class:`BuiltProject` for the read-only usage rule. A manager instance is
rooted under one pytest worker's basetemp, so reuse never crosses xdist
workers or pytest invocations. Failed builds are never cached.
"""

from __future__ import annotations

import hashlib
import math
import shutil
from collections.abc import Callable, Mapping, Sequence, Set
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, TypeAlias, cast

import pytest
from conftest import HtmlPage, SphinxProject, _merge_config  # pyright: ignore[reportPrivateUsage]
from fixtures.responsive_real_build import _SOURCE_DATE_EPOCH, create_project  # pyright: ignore[reportPrivateUsage]
from fixtures.responsive_real_project import project_config, project_files

from maatlog.responsive_image_build import responsive_manifest

if TYPE_CHECKING:
    from maatlog.image_contracts import ResponsiveImageEntry

FrozenValue: TypeAlias = tuple[str, object] | None
FrozenConfig: TypeAlias = tuple[tuple[str, FrozenValue], ...]
BuildRoute: TypeAlias = Literal["inprocess", "subprocess"]

_SOURCE_FILES_TAG: TypeAlias = tuple[tuple[str, tuple[str, str]], ...]


def _freeze(value: object) -> FrozenValue:
    """Reduce a config value to a hashable, type-distinguishing frozen form."""
    if value is None:
        return None
    if isinstance(value, bool):
        return ("bool", value)
    if type(value) is int:
        return ("int", value)
    if type(value) is float:
        if not math.isfinite(value):
            msg = f"build config float must be finite, got {value!r}"
            raise TypeError(msg)
        return ("float", value.hex())
    if type(value) is str:
        return ("str", value)
    if type(value) is dict:
        pairs: list[tuple[str, FrozenValue]] = []
        for key, item in cast("Mapping[object, object]", value).items():
            if type(key) is not str:
                msg = f"build config keys must be strings, got {key!r}"
                raise TypeError(msg)
            pairs.append((key, _freeze(item)))
        return ("map", tuple(sorted(pairs)))
    if type(value) is list:
        return ("list", tuple(_freeze(item) for item in cast("list[object]", value)))
    if type(value) is tuple:
        return ("tuple", tuple(_freeze(item) for item in cast("tuple[object, ...]", value)))
    if type(value) in (set, frozenset):
        values = cast("Set[object]", value)
        tag = "frozenset" if type(value) is frozenset else "set"
        return (tag, tuple(sorted((_freeze(item) for item in values), key=repr)))
    msg = f"build config value is not stable: {value!r}"
    raise TypeError(msg)


def _freeze_config(config: Mapping[str, object] | None) -> FrozenConfig:
    if config is None:
        return ()
    frozen = _freeze(dict(config))
    assert isinstance(frozen, tuple) and frozen[0] == "map"
    return cast("FrozenConfig", frozen[1])


def _freeze_files(files: Mapping[str, str | bytes]) -> _SOURCE_FILES_TAG:
    entries: list[tuple[str, tuple[str, str]]] = []
    for name, content in files.items():
        if isinstance(content, bytes):
            entries.append((name, ("bytes", hashlib.sha256(content).hexdigest())))
        else:
            entries.append((name, ("str", hashlib.sha256(content.encode("utf-8")).hexdigest())))
    return tuple(sorted(entries))


@dataclass(frozen=True, slots=True)
class BuildKey:
    """Explicit inputs, merged with defaults, that select one cached build.

    Reuse is decided by these inputs alone; process environment or
    interpreter state outside ``source_date_epoch`` is not captured.
    """

    route: BuildRoute
    files: _SOURCE_FILES_TAG
    config: FrozenConfig
    builder: str
    source_date_epoch: str
    theme: str | None
    extensions: tuple[str, ...]
    conf_py_prefix: str


def make_build_key(
    *,
    route: BuildRoute,
    files: Mapping[str, str | bytes],
    source_date_epoch: str = "1785542400",
    config: Mapping[str, object] | None = None,
    builder: str = "html",
    theme: str | None = None,
    extensions: Sequence[str] | None = None,
    conf_py_prefix: str = "",
) -> BuildKey:
    """Freeze explicit inputs merged with defaults into a hashable cache key."""
    return BuildKey(
        route=route,
        files=_freeze_files(files),
        config=_freeze_config(config),
        builder=builder,
        source_date_epoch=source_date_epoch,
        theme=theme,
        extensions=tuple(extensions or ()),
        conf_py_prefix=conf_py_prefix,
    )


@dataclass(frozen=True, slots=True)
class BuiltProject:
    """Immutable snapshot of one successful build.

    Never exposes the Sphinx ``app``/``env`` objects or mutable mappings. The
    result object and its ``manifest``/``images`` mappings are immutable, but
    the build tree under ``root``/``srcdir``/``outdir``/``doctreedir`` stays
    writable — edits there are visible to every test sharing this result, so
    consumers must treat it as read-only. Tests that mutate outputs, rebuild
    incrementally, run parallel builds, inject failures, or need a fresh
    subprocess environment use ``make_project``/``make_sphinx``/
    ``create_project`` instead.
    """

    root: Path
    srcdir: Path
    outdir: Path
    doctreedir: Path
    builder: str
    warnings: str
    stdout: str
    stderr: str
    returncode: int
    manifest: Mapping[str, ResponsiveImageEntry]
    images: Mapping[str, str]

    def path(self, relative: str) -> Path:
        """Return the output path for ``relative`` under this build's outdir."""
        return self.outdir / relative

    def html(self, relative: str) -> HtmlPage:
        """Return the rendered HTML page at ``relative`` as an ``HtmlPage``."""
        return HtmlPage(self.path(relative).read_text(encoding="utf-8"))

    def asset(self, relative: str) -> Path:
        """Return the output path for ``relative`` (alias of :meth:`path`)."""
        return self.path(relative)


class BuiltProjects:
    """Worker-local cache of successful builds keyed by explicit inputs."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._cache: dict[BuildKey, BuiltProject] = {}
        self._next_id = 0

    def get(self, key: BuildKey, build: Callable[[Path], BuiltProject]) -> BuiltProject:
        """Return the cached build for ``key``, running ``build`` on a miss.

        Only successful results are cached; failures clean up their root so a
        retry always gets a fresh directory.
        """
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        self._next_id += 1
        root = self._root / f"project-{self._next_id:04d}"
        root.mkdir(parents=True)
        try:
            result = build(root)
            if result.returncode != 0:
                raise RuntimeError(result.stdout + result.stderr)
            for path in (result.srcdir, result.outdir, result.doctreedir):
                if not path.is_dir() or not path.resolve().is_relative_to(root.resolve()):
                    raise ValueError(f"invalid build directory: {path}")
        except BaseException:
            shutil.rmtree(root, ignore_errors=True)
            raise
        self._cache[key] = result
        return result

    def project(
        self,
        *,
        files: Mapping[str, str | bytes],
        source_date_epoch: str = "1785542400",
        config: Mapping[str, object] | None = None,
        builder: str = "html",
        theme: str | None = None,
        extensions: Sequence[str] | None = None,
        conf_py_prefix: str = "",
    ) -> BuiltProject:
        """Share an in-process :class:`SphinxProject` build by explicit inputs."""
        merged = _merge_config(config, theme=theme)
        key = make_build_key(
            route="inprocess",
            files=files,
            source_date_epoch=source_date_epoch,
            config=merged,
            builder=builder,
            extensions=extensions,
            conf_py_prefix=conf_py_prefix,
        )

        def build(root: Path) -> BuiltProject:
            with pytest.MonkeyPatch.context() as patch:
                project = SphinxProject(
                    root,
                    files=files,
                    source_date_epoch=source_date_epoch,
                    config=merged,
                    builder=builder,
                    extensions=extensions,
                    conf_py_prefix=conf_py_prefix,
                    monkeypatch=patch,
                )
                result = project.build()
            manifest = MappingProxyType(dict(responsive_manifest(result.app.env)))
            images = MappingProxyType(dict(result.app.builder.images))
            return BuiltProject(
                root=root,
                srcdir=project.srcdir,
                outdir=project.outdir,
                doctreedir=project.doctreedir,
                builder=builder,
                warnings=result.warnings,
                stdout="",
                stderr="",
                returncode=0,
                manifest=manifest,
                images=images,
            )

        return self.get(key, build)

    def real(
        self,
        *,
        builder: str = "html",
        enabled: bool = True,
        page_size: int = 20,
        source_name: str = "photo.jpg",
        post_count: int = 15,
        files: Mapping[str, str | bytes] | None = None,
        config: Mapping[str, object] | None = None,
    ) -> BuiltProject:
        """Share a real ``python -m sphinx`` subprocess build by explicit inputs."""
        effective_files: Mapping[str, str | bytes] = (
            dict(files) if files is not None else project_files(source_name=source_name, post_count=post_count)
        )
        effective_config = project_config(enabled=enabled, page_size=page_size)
        if config is not None:
            effective_config.update(config)
        key = make_build_key(
            route="subprocess",
            files=effective_files,
            source_date_epoch=_SOURCE_DATE_EPOCH,
            config=effective_config,
            builder=builder,
        )

        def build(root: Path) -> BuiltProject:
            project = create_project(
                root,
                builder=builder,
                enabled=enabled,
                page_size=page_size,
                source_name=source_name,
                post_count=post_count,
                files=effective_files,
                config=config,
            )
            result = project.build()
            if result.returncode != 0:
                raise RuntimeError(
                    f"real build failed (returncode={result.returncode}):\n{result.stdout}{result.stderr}"
                )
            return BuiltProject(
                root=root,
                srcdir=project.srcdir,
                outdir=project.outdir,
                doctreedir=project.doctreedir,
                builder=builder,
                warnings="",
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode,
                manifest=MappingProxyType({}),
                images=MappingProxyType({}),
            )

        return self.get(key, build)
