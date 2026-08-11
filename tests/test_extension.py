from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import create_autospec

import pytest
from sphinx.application import Sphinx
from sphinx.config import Config

import maatlog
from maatlog.builders import warn_partial_support_once
from maatlog.config import CONFIG_VALUES, validate_config
from maatlog.directives import process_post_list_nodes
from maatlog.extension import (
    collect_archive_pages,
    finalize_domain,
    finalize_generated_outputs,
    initialize_build_time,
    inject_maatlog_page_context,
    merge_info,
    purge_doc,
)
from maatlog.html_metadata import force_post_docs_outdated_for_feeds, prepare_body_fragment_store
from maatlog.metadata import capture_source, cleanup_sources, collect_post
from maatlog.theme_api import validate_selected_theme
from maatlog.views import as_template_mapping, empty_context, register_representative_images


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
        "builder-inited",  # html metadata / baseurl
        "source-read",
        "doctree-read",
        "env-get-outdated",  # force post rewrite for body cache when feeds on
        "env-purge-doc",
        "env-merge-info",
        "env-updated",
        "doctree-resolved",
        "html-collect-pages",
        "html-page-context",
        "write-started",
        "write-started",
        "build-finished",
        "build-finished",
    ]
    assert app.connect.call_args_list[0] == (("config-inited", validate_config), {})
    assert app.connect.call_args_list[1] == (("config-inited", initialize_build_time), {})
    assert app.connect.call_args_list[2] == (("builder-inited", warn_partial_support_once), {})
    assert app.connect.call_args_list[3] == (("builder-inited", validate_selected_theme), {})
    assert app.connect.call_args_list[5] == (("source-read", capture_source), {"priority": 999})
    assert app.connect.call_args_list[6] == (("doctree-read", collect_post), {"priority": 100})
    assert app.connect.call_args_list[7] == (("env-get-outdated", force_post_docs_outdated_for_feeds), {})
    assert app.connect.call_args_list[8] == (("env-purge-doc", purge_doc), {})
    assert app.connect.call_args_list[9] == (("env-merge-info", merge_info), {})
    assert app.connect.call_args_list[10] == (("env-updated", finalize_domain), {})
    assert app.connect.call_args_list[11] == (("doctree-resolved", process_post_list_nodes), {})
    assert app.connect.call_args_list[12] == (("html-collect-pages", collect_archive_pages), {})
    assert app.connect.call_args_list[13] == (("html-page-context", inject_maatlog_page_context), {})
    assert app.connect.call_args_list[14] == (("write-started", prepare_body_fragment_store), {})
    assert app.connect.call_args_list[15] == (("write-started", register_representative_images), {})
    assert app.connect.call_args_list[16] == (("build-finished", finalize_generated_outputs), {})
    assert app.connect.call_args_list[17] == (("build-finished", cleanup_sources), {})


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

    env = SimpleNamespace(get_domain=get_domain)
    builder = SimpleNamespace(name="html", format="html")
    return cast(Sphinx, SimpleNamespace(env=env, builder=builder))


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
    assert context["maatlog"] == as_template_mapping(empty_context())
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
