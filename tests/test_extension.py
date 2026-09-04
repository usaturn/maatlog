from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import create_autospec

import pytest
from jinja2 import TemplateNotFound
from sphinx.application import Sphinx
from sphinx.config import Config
from sphinx.environment import BuildEnvironment

import maatlog
from maatlog.builders import warn_partial_support_once
from maatlog.config import CONFIG_VALUES, MaatlogConfig, TaxonomyAxis, validate_config
from maatlog.directives import process_post_list_nodes
from maatlog.extension import (
    apply_pygments_style,
    collect_archive_pages,
    collect_maattop,
    collect_maattop_from_myst,
    collect_post_lists,
    commit_html_shell_fingerprint,
    finalize_domain,
    finalize_generated_outputs,
    force_home_doc_updated,
    initialize_build_time,
    inject_maatlog_page_context,
    link_palette_stylesheet,
    merge_info,
    purge_doc,
    resolved_home_docname,
)
from maatlog.html_metadata import force_post_docs_outdated_for_feeds, prepare_body_fragment_store
from maatlog.metadata import capture_source, cleanup_sources, collect_post
from maatlog.theme_api import validate_selected_theme
from maatlog.views import SiteView, as_template_mapping, empty_context, register_representative_images


def _extension_config(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {name: default for name, (default, _) in CONFIG_VALUES.items()}
    values.update(overrides)
    return SimpleNamespace(**values)


def test_setup_registers_domain_and_myst(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    app = create_autospec(Sphinx, instance=True)
    app.setup_extension.side_effect = calls.append

    metadata = maatlog.setup(app)

    app.add_domain.assert_called_once()
    assert calls == ["myst_parser"]
    app.add_html_theme.assert_called()
    theme_names = [call.args[0] for call in app.add_html_theme.call_args_list]
    assert "maatlog-base" in theme_names
    assert "maatlog-default" in theme_names
    assert metadata.get("parallel_read_safe") is True
    assert metadata.get("parallel_write_safe") is True


def test_setup_registers_config_values_and_validation_handler() -> None:
    app = create_autospec(Sphinx, instance=True)

    maatlog.setup(app)

    assert app.add_config_value.call_count == len(CONFIG_VALUES)
    connect_events = [call.args[0] for call in app.connect.call_args_list]
    assert connect_events == [
        "config-inited",  # validate_config
        "config-inited",  # initialize_build_time
        "builder-inited",  # warn_partial_support_once
        "builder-inited",  # validate_selected_theme
        "builder-inited",  # link_palette_stylesheet
        "builder-inited",  # apply_pygments_style
        "builder-inited",  # html metadata / baseurl
        "source-read",
        "doctree-read",
        "doctree-read",
        "doctree-read",
        "doctree-read",
        "env-get-outdated",  # force post rewrite for body cache when feeds on
        "env-purge-doc",
        "env-merge-info",
        "env-updated",
        "env-get-updated",
        "doctree-resolved",
        "html-collect-pages",
        "html-page-context",
        "write-started",
        "write-started",
        "build-finished",
        "build-finished",
        "build-finished",  # commit_html_shell_fingerprint (last; only on success)
    ]
    assert app.connect.call_args_list[0] == (("config-inited", validate_config), {})
    assert app.connect.call_args_list[1] == (("config-inited", initialize_build_time), {})
    assert app.connect.call_args_list[2] == (("builder-inited", warn_partial_support_once), {})
    assert app.connect.call_args_list[3] == (("builder-inited", validate_selected_theme), {})
    assert app.connect.call_args_list[4] == (("builder-inited", link_palette_stylesheet), {})
    assert app.connect.call_args_list[5] == (("builder-inited", apply_pygments_style), {})
    assert app.connect.call_args_list[7] == (("source-read", capture_source), {"priority": 999})
    assert app.connect.call_args_list[8] == (
        ("doctree-read", collect_maattop_from_myst),
        {"priority": 99},
    )
    assert app.connect.call_args_list[9] == (("doctree-read", collect_post), {"priority": 100})
    assert app.connect.call_args_list[10] == (("doctree-read", collect_post_lists), {"priority": 101})
    assert app.connect.call_args_list[11] == (("doctree-read", collect_maattop), {"priority": 102})
    assert app.connect.call_args_list[12] == (("env-get-outdated", force_post_docs_outdated_for_feeds), {})
    assert app.connect.call_args_list[13] == (("env-purge-doc", purge_doc), {})
    assert app.connect.call_args_list[14] == (("env-merge-info", merge_info), {})
    assert app.connect.call_args_list[15] == (("env-updated", finalize_domain), {})
    assert app.connect.call_args_list[16] == (("env-get-updated", force_home_doc_updated), {})
    assert app.connect.call_args_list[17] == (("doctree-resolved", process_post_list_nodes), {})
    assert app.connect.call_args_list[18] == (("html-collect-pages", collect_archive_pages), {})
    assert app.connect.call_args_list[19] == (("html-page-context", inject_maatlog_page_context), {})
    assert app.connect.call_args_list[20] == (("write-started", prepare_body_fragment_store), {})
    assert app.connect.call_args_list[21] == (("write-started", register_representative_images), {})
    assert app.connect.call_args_list[22] == (("build-finished", finalize_generated_outputs), {})
    assert app.connect.call_args_list[23] == (("build-finished", cleanup_sources), {})
    assert app.connect.call_args_list[24] == (("build-finished", commit_html_shell_fingerprint), {})


def test_initialize_build_time_keeps_one_build_local_value(monkeypatch: pytest.MonkeyPatch) -> None:
    app = cast(Sphinx, SimpleNamespace())
    config = cast(Config, object())
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1785542400")

    initialize_build_time(app, config)
    first_build_time = cast(datetime, app.__dict__["_maatlog_build_time"])
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1785628800")
    initialize_build_time(app, config)

    assert first_build_time == datetime(2026, 8, 1, tzinfo=UTC)
    assert cast(datetime, app.__dict__["_maatlog_build_time"]) is first_build_time


def _app_with_empty_posts() -> Sphinx:
    domain = SimpleNamespace(data={"posts_by_docname": {}})

    def get_domain(_name: str) -> Any:
        return domain

    def get_relative_uri(_from: str, to: str) -> str:
        return f"{to}.html"

    env = SimpleNamespace(get_domain=get_domain)
    config = SimpleNamespace(
        project="Test",
        **{name: default for name, (default, _) in CONFIG_VALUES.items()},
    )
    builder = SimpleNamespace(
        name="html",
        format="html",
        get_relative_uri=get_relative_uri,
    )
    return cast(Sphinx, SimpleNamespace(env=env, builder=builder, config=config))


def test_inject_sets_empty_maatlog_when_missing_for_non_post() -> None:
    context: dict[str, Any] = {}
    result = inject_maatlog_page_context(
        _app_with_empty_posts(),
        "index",
        "page.html",
        context,
        None,
    )
    assert result is None
    assert context["maatlog"] == as_template_mapping(
        empty_context(site=SiteView(title="Test", tagline=None, archive_url="blog.html"))
    )
    assert context["maatlog"]["page_kind"] == "normal"


def test_inject_preserves_preseeded_maatlog_archive_context_for_non_post() -> None:
    """Plan 04 archive collectors may pre-seed context before html-page-context."""
    preseeded: dict[str, Any] = {
        "api_version": "1.0",
        "page_kind": "archive",
        "post": None,
        "posts": (),
        "archive": {
            "kind": "recent",
            "id": None,
            "label": "Recent",
            "docname": "archives/recent",
            "page_number": 1,
            "total_posts": 0,
        },
        "pagination": None,
        "navigation": {"newer_post": None, "older_post": None},
        "feeds": (),
        "taxonomies": {
            "tags": (),
            "categories": (),
            "authors": (),
            "months": (),
        },
    }
    context: dict[str, Any] = {"maatlog": preseeded}

    result = inject_maatlog_page_context(
        _app_with_empty_posts(),
        "archives/recent",
        "page.html",
        context,
        None,
    )

    assert result is None
    assert context["maatlog"] is preseeded
    assert context["maatlog"]["page_kind"] == "archive"
    assert context["maatlog"]["archive"]["kind"] == "recent"


def _fake_toc(*docnames: str, hidden: bool = False) -> SimpleNamespace:
    """Stand in for ``env.tocs[docname]`` with a single toctree node."""
    node: dict[str, object] = {
        "entries": [(None, docname) for docname in docnames],
        "hidden": hidden,
        "maxdepth": -1,
        "caption": None,
    }

    def findall(_node_type: object) -> list[dict[str, object]]:
        return [node]

    return SimpleNamespace(findall=findall)


def test_force_home_doc_updated_rewrites_posts_and_home(tmp_path: Path) -> None:
    def get_domain(_name: str) -> SimpleNamespace:
        return SimpleNamespace(
            data={"posts_by_docname": {"scheduled": object(), "index": object()}},
            post_list_docnames=lambda: set[str](),
        )

    def get_template(_name: str) -> object:
        return object()

    env = SimpleNamespace(
        found_docs={"index", "scheduled"},
        get_domain=get_domain,
        titles={docname: SimpleNamespace(astext=lambda name=docname: name) for docname in ("index", "scheduled")},
        tocs={"index": _fake_toc("scheduled")},
    )
    app = SimpleNamespace(
        builder=SimpleNamespace(
            name="html",
            format="html",
            templates=SimpleNamespace(environment=SimpleNamespace(get_template=get_template)),
        ),
        config=_extension_config(maatlog_home_docname="index"),
        env=env,
        outdir=tmp_path / "out",
        doctreedir=tmp_path / "doctrees",
    )

    assert force_home_doc_updated(
        cast(Sphinx, app),
        cast(BuildEnvironment, env),
    ) == ["index", "scheduled"]


def test_force_home_doc_updated_includes_post_list_pages(tmp_path: Path) -> None:
    index = SimpleNamespace(published=(SimpleNamespace(slug="scheduled"),), members={})

    def get_domain(_name: str) -> SimpleNamespace:
        return SimpleNamespace(
            data={"posts_by_docname": {"scheduled": object()}, "index": index},
            post_list_docnames=lambda: {"listing"},
        )

    env = SimpleNamespace(
        found_docs={"about", "listing", "scheduled"},
        get_domain=get_domain,
        titles={
            docname: SimpleNamespace(astext=lambda name=docname: name) for docname in ("about", "listing", "scheduled")
        },
        tocs={"about": _fake_toc("listing")},
    )
    app = SimpleNamespace(
        builder=SimpleNamespace(name="html", format="html"),
        config=_extension_config(),
        env=env,
        outdir=tmp_path / "out",
        doctreedir=tmp_path / "doctrees",
    )
    sphinx_app = cast(Sphinx, app)
    sphinx_env = cast(BuildEnvironment, env)

    first = force_home_doc_updated(sphinx_app, sphinx_env)
    commit_html_shell_fingerprint(sphinx_app, None)
    second = force_home_doc_updated(sphinx_app, sphinx_env)

    assert "listing" in first
    assert "scheduled" in first
    assert "about" in first
    assert "listing" in second
    assert "scheduled" in second
    assert "about" not in second


def test_force_home_doc_updated_rewrites_plain_pages_when_published_index_changes(
    tmp_path: Path,
) -> None:
    index = SimpleNamespace(published=(SimpleNamespace(slug="keep"),), members={})
    data: dict[str, object] = {
        "posts_by_docname": {"keep": object()},
        "index": index,
    }

    def get_domain(_name: str) -> SimpleNamespace:
        return SimpleNamespace(data=data, post_list_docnames=lambda: set[str]())

    tocs = {"index": _fake_toc("about", "keep")}
    env = SimpleNamespace(
        found_docs={"about", "index", "keep"},
        get_domain=get_domain,
        titles={docname: SimpleNamespace(astext=lambda name=docname: name) for docname in ("about", "index", "keep")},
        tocs=tocs,
    )

    def get_template(_name: str) -> object:
        return object()

    app = SimpleNamespace(
        builder=SimpleNamespace(
            name="html",
            format="html",
            templates=SimpleNamespace(environment=SimpleNamespace(get_template=get_template)),
        ),
        config=_extension_config(maatlog_home_docname="index"),
        env=env,
        outdir=tmp_path / "out",
        doctreedir=tmp_path / "doctrees",
    )
    app = cast(Sphinx, app)
    env = cast(BuildEnvironment, env)

    first = force_home_doc_updated(app, env)
    commit_html_shell_fingerprint(app, None)
    second = force_home_doc_updated(app, env)
    index.published = (SimpleNamespace(slug="keep"), SimpleNamespace(slug="fresh"))
    third = force_home_doc_updated(app, env)
    commit_html_shell_fingerprint(app, None)
    index.members = {TaxonomyAxis.TAG: {"fresh": ("keep", "fresh")}}
    fourth = force_home_doc_updated(app, env)
    commit_html_shell_fingerprint(app, None)
    fifth = force_home_doc_updated(app, env)
    tocs["index"] = _fake_toc("about", "keep", hidden=True)
    sixth = force_home_doc_updated(app, env)

    assert first == ["index", "keep", "about"]
    assert second == ["index", "keep"]
    assert third == ["index", "keep", "about"]
    assert fourth == ["index", "keep", "about"]
    assert fifth == ["index", "keep"]
    # A toctree-only edit changes the shell as much as a published-index change.
    assert sixth == ["index", "keep", "about"]


def test_force_home_doc_updated_skips_non_html_builders() -> None:
    def get_domain(_name: str) -> SimpleNamespace:
        return SimpleNamespace(data={"posts_by_docname": {"post": object()}})

    env = SimpleNamespace(
        found_docs={"post"},
        get_domain=get_domain,
    )
    app = SimpleNamespace(
        builder=SimpleNamespace(name="text", format="text"),
        config=_extension_config(),
        env=env,
    )

    assert force_home_doc_updated(cast(Sphinx, app), cast(BuildEnvironment, env)) == []


def _app_with_home_template(can_resolve: bool) -> SimpleNamespace:
    """Build a minimal app for ``resolved_home_docname`` with a stubbed theme loader."""

    def get_template(name: str) -> object:
        if not can_resolve:
            raise TemplateNotFound(name)
        return object()

    return SimpleNamespace(
        builder=SimpleNamespace(templates=SimpleNamespace(environment=SimpleNamespace(get_template=get_template))),
        config=_extension_config(maatlog_home_docname="index"),
        env=SimpleNamespace(found_docs={"index"}),
    )


def test_resolved_home_docname_returns_docname_when_theme_resolves_home_template() -> None:
    app = _app_with_home_template(can_resolve=True)
    config = MaatlogConfig.from_sphinx(cast(Config, app.config))

    assert resolved_home_docname(cast(Sphinx, app), config) == "index"


def test_resolved_home_docname_is_none_when_theme_lacks_home_template() -> None:
    app = _app_with_home_template(can_resolve=False)
    config = MaatlogConfig.from_sphinx(cast(Config, app.config))

    assert resolved_home_docname(cast(Sphinx, app), config) is None


def test_commit_html_shell_fingerprint_only_persists_success(tmp_path: Path) -> None:
    namespace = SimpleNamespace(
        builder=SimpleNamespace(name="html", format="html"),
        doctreedir=tmp_path / "doctrees",
        outdir=tmp_path / "html",
    )
    namespace._maatlog_pending_html_shell_fingerprint = (("post",), (), (("post", "Post"),))
    app = cast(Sphinx, namespace)

    commit_html_shell_fingerprint(app, RuntimeError("write failed"))
    assert not (tmp_path / "doctrees" / "maatlog_html_shell_fingerprints.pickle").exists()

    commit_html_shell_fingerprint(app, None)
    assert (tmp_path / "doctrees" / "maatlog_html_shell_fingerprints.pickle").is_file()
