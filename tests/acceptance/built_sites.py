"""Worker-local cache for immutable built acceptance sites."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping, Set
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias, cast

import pytest
from acceptance.server import serve_directory

FrozenValue: TypeAlias = tuple[str, object] | None
FrozenConfig: TypeAlias = tuple[tuple[str, FrozenValue], ...]
BuildSite: TypeAlias = Callable[[Path, pytest.MonkeyPatch], Path]


def _freeze(value: object) -> FrozenValue:
    # Every frozen form is ("tag", payload) or None, so differently-typed inputs
    # (True/1/1.0, Path("x")/"x") can never collapse into the same key.
    if value is None:
        return None
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("int", value)
    if isinstance(value, float):
        return ("float", value)
    if isinstance(value, str):
        return ("str", value)
    if isinstance(value, Path):
        return ("path", value.as_posix())
    if isinstance(value, Mapping):
        pairs: list[tuple[str, FrozenValue]] = []
        for key, item in cast("Mapping[object, object]", value).items():
            if not isinstance(key, str):
                msg = f"site config keys must be strings, got {key!r}"
                raise TypeError(msg)
            pairs.append((key, _freeze(item)))
        return ("map", tuple(sorted(pairs)))
    if isinstance(value, (list, tuple)):
        sequence = cast("list[object] | tuple[object, ...]", value)
        return ("seq", tuple(_freeze(item) for item in sequence))
    if isinstance(value, Set):
        values = cast("Set[object]", value)
        return ("set", tuple(sorted((_freeze(item) for item in values), key=repr)))
    msg = f"site config value is not stable: {value!r}"
    raise TypeError(msg)


def _freeze_config(config: Mapping[str, object] | None) -> FrozenConfig:
    if config is None:
        return ()
    frozen = _freeze(config)
    assert isinstance(frozen, tuple) and frozen[0] == "map"
    return cast("FrozenConfig", frozen[1])


@dataclass(frozen=True, init=False, slots=True)
class SiteKey:
    """All build inputs that may change an acceptance site's output."""

    fixture: str
    input_id: str
    builder: str
    theme: str | None
    config: FrozenConfig
    source_date_epoch: str
    responsive_images: bool
    warningiserror: bool
    project_root: Path | None

    def __init__(
        self,
        *,
        fixture: str,
        input_id: str,
        builder: str = "html",
        theme: str | None = None,
        config: Mapping[str, object] | None = None,
        source_date_epoch: str,
        responsive_images: bool,
        warningiserror: bool = True,
        project_root: Path | None = None,
    ) -> None:
        object.__setattr__(self, "fixture", fixture)
        object.__setattr__(self, "input_id", input_id)
        object.__setattr__(self, "builder", builder)
        object.__setattr__(self, "theme", theme)
        object.__setattr__(self, "config", _freeze_config(config))
        object.__setattr__(self, "source_date_epoch", source_date_epoch)
        object.__setattr__(self, "responsive_images", responsive_images)
        object.__setattr__(self, "warningiserror", warningiserror)
        object.__setattr__(self, "project_root", project_root)


@dataclass(frozen=True, slots=True)
class BuiltSite:
    """Immutable information consumers need from a completed build."""

    outdir: Path
    builder: str
    base_url: str


class BuiltSites:
    """Build and serve each requested key at most once in the current worker."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._sites: dict[SiteKey, BuiltSite] = {}
        self._resources = ExitStack()
        self._next_site = 1
        self._closed = False

    def __enter__(self) -> BuiltSites:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get(self, key: SiteKey, build: BuildSite) -> BuiltSite:
        """Return the cached site for *key*, building and serving it on demand."""
        if self._closed:
            msg = "built-sites manager is closed"
            raise RuntimeError(msg)
        cached = self._sites.get(key)
        if cached is not None:
            return cached

        site_root = self._root / f"site-{self._next_site:04d}"
        self._next_site += 1
        if site_root.exists():
            shutil.rmtree(site_root)
        site_root.mkdir(parents=True)
        try:
            with pytest.MonkeyPatch.context() as monkeypatch:
                outdir = build(site_root, monkeypatch)
            resolved_root = site_root.resolve()
            resolved_outdir = outdir.resolve()
            if not resolved_outdir.is_relative_to(resolved_root) or not resolved_outdir.is_dir():
                msg = f"site builder returned an invalid outdir: {outdir}"
                raise ValueError(msg)
            base_url = self._resources.enter_context(serve_directory(resolved_outdir))
        except BaseException:
            shutil.rmtree(site_root, ignore_errors=True)
            raise

        built = BuiltSite(outdir=resolved_outdir, builder=key.builder, base_url=base_url)
        self._sites[key] = built
        return built

    def close(self) -> None:
        """Stop every owned HTTP server. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        self._resources.close()


__all__ = ["BuildSite", "BuiltSite", "BuiltSites", "FrozenConfig", "FrozenValue", "SiteKey"]
