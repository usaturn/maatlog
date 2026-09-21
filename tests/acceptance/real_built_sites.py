"""Lazy provider mapping each real-image variant to ``(SiteKey, BuildSite)`` (Issue #315).

Every site is a real ``python -m sphinx`` subprocess build driven by
``fixtures.responsive_real_build`` -- nothing is injected into the output.
Each ``*_site()`` accessor pairs a ``SiteKey`` with the callback
``BuiltSites.get`` runs at most once per worker; ``RealSites`` is the thin
facade the acceptance tests consume. The key records every output-affecting
input ``SiteKey`` can express (builder, the merged conf.py config,
``source_date_epoch``, ``responsive_images``); inputs it cannot express --
``source_name``, ``post_count``, the ``files_factory`` file set and
``conf_append`` -- are the caller's responsibility to encode in ``input_id``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

import pytest
from acceptance.built_sites import BuildSite, BuiltSite, BuiltSites, SiteKey
from fixtures.responsive_real_build import _SOURCE_DATE_EPOCH, create_project  # pyright: ignore[reportPrivateUsage]
from fixtures.responsive_real_project import project_config, project_files

#: Third-party theme image-policy override (verbatim from the geometry fixture).
_OVERRIDE_POLICY: Final = """\
{% macro image_sizes(usage, presentation='standalone', has_rail=none, featured_count=0) -%}
{{ '321px' if usage == 'post-top' else '123px' }}{%- endmacro %}
{% macro image_loading(usage, early=true) -%}eager{%- endmacro %}
{% macro image_fetchpriority(usage, high=false) -%}auto{%- endmacro %}
"""

#: conf.py append registering the ``inherits-base`` override theme (verbatim).
_OVERRIDE_CONF_APPEND: Final = (
    "\ndef setup(app):\n"
    + "    from pathlib import Path\n"
    + "    app.add_html_theme('inherits-base',"
    + " str(Path(__file__).resolve().parent / '_override_theme'))\n"
)


def _no_rail_files() -> dict[str, str | bytes]:
    """Default bundle minus the post front matter that renders a right rail."""
    stripped: dict[str, str | bytes] = {}
    for name, content in project_files().items():
        if isinstance(content, str) and name.startswith("posts/"):
            for field in (
                "maatlog-authors: [alice]\n",
                "maatlog-tags: [integration]\n",
                "maatlog-categories: [photos]\n",
            ):
                content = content.replace(field, "")
        stripped[name] = content
    return stripped


def _post_only_files(count: int) -> dict[str, str | bytes]:
    """Exactly *count* real posts plus their image sources and a minimal home."""
    files = project_files(post_count=max(count, 3))
    posts = {f"posts/p{index:02d}.md" for index in range(1, count + 1)}
    kept = {name: content for name, content in files.items() if name in posts or not name.endswith((".rst", ".md"))}
    entries = "\n".join(f"   posts/p{index:02d}" for index in range(1, count + 1))
    kept["index.rst"] = f"Home\n====\n\n.. toctree::\n   :hidden:\n\n{entries}\n"
    return kept


def _override_theme_files() -> dict[str, str | bytes]:
    """Default bundle plus the ``_override_theme/`` third-party theme tree."""
    files = project_files()
    files["_override_theme/theme.conf"] = "[theme]\ninherit = maatlog-base\nstylesheet = maatlog.css\n"
    files["_override_theme/maatlog-theme.toml"] = '[maatlog]\napi = "1.22"\nimplementation = "inherits-base"\n'
    files["_override_theme/maatlog/components/image-policy.html"] = _OVERRIDE_POLICY
    return files


def _spec(
    *,
    input_id: str,
    builder: str = "html",
    enabled: bool = True,
    page_size: int = 20,
    source_name: str = "photo.jpg",
    post_count: int = 15,
    files_factory: Callable[[], Mapping[str, str | bytes]] | None = None,
    config: Mapping[str, object] | None = None,
    conf_append: str | None = None,
) -> tuple[SiteKey, BuildSite]:
    """Pair the ``SiteKey`` of one variant with its real-build callback.

    The key records the *effective* conf.py config (``project_config`` merged
    with *config*), so differences like ``maatlog_page_size`` or
    ``html_theme`` always select a distinct site. ``theme`` stays ``None``
    (the theme arrives through conf.py), ``warningiserror`` keeps its ``True``
    default (real builds always run ``-W --keep-going``) and there is no
    template ``project_root``. *files_factory* is a zero-argument callable so
    the source tree is only materialised when the site is actually built.
    *input_id* must uniquely encode every output-affecting input the key does
    not carry: *source_name*, *post_count*, the *files_factory* file set and
    *conf_append*.
    """
    key = SiteKey(
        fixture="responsive-real",
        input_id=input_id,
        builder=builder,
        config=project_config(enabled=enabled, page_size=page_size) | dict(config or {}),
        source_date_epoch=_SOURCE_DATE_EPOCH,
        responsive_images=enabled,
    )

    def build(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        del monkeypatch  # the subprocess driver sets its own environment
        project = create_project(
            root,
            builder=builder,
            enabled=enabled,
            page_size=page_size,
            source_name=source_name,
            post_count=post_count,
            files=None if files_factory is None else files_factory(),
            config=config,
        )
        if conf_append is not None:
            conf = project.srcdir / "conf.py"
            conf.write_text(conf.read_text(encoding="utf-8") + conf_append, encoding="utf-8")
        result = project.build()
        assert result.returncode == 0, result.stdout + result.stderr
        return project.outdir

    return key, build


def standard_site(builder: str, *, enabled: bool) -> tuple[SiteKey, BuildSite]:
    """The default bundle: ``project_files()`` (15 posts, photo.jpg)."""
    return _spec(input_id="standard", builder=builder, enabled=enabled)


def scroll_site(builder: str) -> tuple[SiteKey, BuildSite]:
    """The default bundle with ``maatlog_page_size=4``, ON fixed."""
    return _spec(input_id="scroll", builder=builder, enabled=True, page_size=4)


def archive_count_site(count: int) -> tuple[SiteKey, BuildSite]:
    """Exactly *count* posts and no featured strip; html/ON."""
    return _spec(
        input_id=f"archive-{count}",
        files_factory=lambda: _post_only_files(count),
        config={"maatlog_featured_posts": []},
    )


def no_rail_site() -> tuple[SiteKey, BuildSite]:
    """Posts without author/tag/category front matter: no right rail."""
    return _spec(
        input_id="no-rail",
        files_factory=_no_rail_files,
        config={
            "maatlog_authors": {},
            "maatlog_author_profiles": {},
            "maatlog_default_author": None,
        },
    )


def base_theme_site() -> tuple[SiteKey, BuildSite]:
    """The default bundle rendered with the ``maatlog-base`` theme."""
    return _spec(input_id="base-theme", config={"html_theme": "maatlog-base"})


def override_theme_site() -> tuple[SiteKey, BuildSite]:
    """A third-party theme (inherits-base, api 1.22) overriding image-policy."""
    return _spec(
        input_id="override-theme",
        files_factory=_override_theme_files,
        config={"html_theme": "inherits-base"},
        conf_append=_OVERRIDE_CONF_APPEND,
    )


def format_site(source_name: str, *, enabled: bool) -> tuple[SiteKey, BuildSite]:
    """Minimal three-post site whose managed source is *source_name*; html."""
    return _spec(input_id=f"format-{source_name}", enabled=enabled, source_name=source_name, post_count=3)


def named_source_site(source_name: str) -> tuple[SiteKey, BuildSite]:
    """The default bundle rebuilt around *source_name*; html/ON."""
    return _spec(input_id=f"named-{source_name}", source_name=source_name)


class RealSites:
    """Thin facade resolving each real-image variant through ``BuiltSites``."""

    def __init__(self, sites: BuiltSites) -> None:
        self._sites = sites

    def standard(self, builder: str, *, enabled: bool) -> BuiltSite:
        return self._sites.get(*standard_site(builder, enabled=enabled))

    def scroll(self, builder: str) -> BuiltSite:
        return self._sites.get(*scroll_site(builder))

    def archive_count(self, count: int) -> BuiltSite:
        return self._sites.get(*archive_count_site(count))

    def no_rail(self) -> BuiltSite:
        return self._sites.get(*no_rail_site())

    def base_theme(self) -> BuiltSite:
        return self._sites.get(*base_theme_site())

    def override_theme(self) -> BuiltSite:
        return self._sites.get(*override_theme_site())

    def format(self, source_name: str, *, enabled: bool) -> BuiltSite:
        return self._sites.get(*format_site(source_name, enabled=enabled))

    def named_source(self, source_name: str) -> BuiltSite:
        return self._sites.get(*named_source_site(source_name))


__all__ = [
    "RealSites",
    "archive_count_site",
    "base_theme_site",
    "format_site",
    "named_source_site",
    "no_rail_site",
    "override_theme_site",
    "scroll_site",
    "standard_site",
]
