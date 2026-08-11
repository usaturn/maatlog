"""Regression suite for the MaatLog diagnostic contract (Spec 06 §4)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import SphinxFactory
from sphinx.application import Sphinx

import maatlog.feeds as feeds_mod
import maatlog.theme_api as theme_api_mod
from maatlog.domain import MaatlogDomain
from maatlog.errors import Diagnostic, MaatlogBuildError, format_diagnostic, safe_value
from maatlog.feeds import write_feeds_after_success
from maatlog.model import Post, PublicationStatus
from maatlog.outputs import safe_owned_path
from maatlog.theme_api import CORE_THEME_API, ThemeApiVersion, parse_and_validate_manifest

# Unit raisers call the same private raise helpers production uses (not re-implemented).
_stage_all_xml = feeds_mod._stage_all_xml  # pyright: ignore[reportPrivateUsage]
_StagedFeed = feeds_mod._StagedFeed  # pyright: ignore[reportPrivateUsage]
_validate_all_xml = feeds_mod._validate_all_xml  # pyright: ignore[reportPrivateUsage]
_validate_stylesheet = theme_api_mod._validate_stylesheet  # pyright: ignore[reportPrivateUsage]

_THEME_FIXTURE_EXTENSIONS = ("fixtures.maatlog_theme_fixtures",)
_THEME_FIXTURE_PREFIX = "import fixtures.maatlog_theme_fixtures  # noqa: F401\n"

# Quoted ``maatlog.<area>.<name>`` strings in production sources (diagnostic codes).
_PRODUCTION_CODE_RE = re.compile(r"""['"](maatlog\.[a-z0-9-]+\.[a-z0-9._-]+)['"]""")

# Warnings / non-fatal codes that appear as string literals but are not MaatlogBuildError fatals.
NON_FATAL_CODE_INVENTORY: frozenset[str] = frozenset(
    {
        "maatlog.builder.partial-support",
    }
)

# Fatal codes that must remain actionable. Covered by Sphinx fixtures and/or unit raise paths.
# Keep in sync with production raise sites; inventory + production-scan tests enforce coverage.
FATAL_CODE_INVENTORY: frozenset[str] = frozenset(
    {
        "maatlog.metadata.unknown",
        "maatlog.metadata.required",
        "maatlog.metadata.type",
        "maatlog.metadata.value",
        "maatlog.metadata.without-post",
        "maatlog.metadata.combination",
        "maatlog.slug.invalid",
        "maatlog.slug.duplicate",
        "maatlog.taxonomy.undefined",
        "maatlog.taxonomy-id.invalid",
        "maatlog.image.missing",
        "maatlog.image.invalid",
        "maatlog.url.invalid",
        "maatlog.datetime.invalid",
        "maatlog.datetime.order",
        "maatlog.config.invalid",
        "maatlog.feed.baseurl-required",
        "maatlog.feed.output-unsafe",
        "maatlog.feed.render-failed",
        "maatlog.feed.xml-invalid",
        "maatlog.theme.api-incompatible",
        "maatlog.theme.manifest-missing",
        "maatlog.theme.manifest-invalid",
        "maatlog.theme.block-missing",
        "maatlog.theme.template-missing",
        "maatlog.theme.stylesheet-missing",
        "maatlog.theme.base-not-inherited",
        "maatlog.archive.option-invalid",
        "maatlog.archive.filter-undefined",
        "maatlog.archive.output-unsafe",
        "maatlog.domain.merge-conflict",
        "maatlog.generated-docname.conflict",
        "maatlog.source-date-epoch.invalid",
    }
)


def _post_rst(*, slug: str = "valid", extra_fields: str = "", title: str = "Title") -> str:
    body = f":maatlog-post: true\n:maatlog-slug: {slug}\n"
    if extra_fields:
        body += extra_fields if extra_fields.endswith("\n") else f"{extra_fields}\n"
    body += f"\n{title}\n{'=' * len(title)}\n"
    return body


def _post_md(*, slug: str = "valid", extra_frontmatter: str = "", title: str = "Title") -> str:
    lines = ["---", "maatlog-post: true", f"maatlog-slug: {slug}"]
    if extra_frontmatter:
        lines.extend(extra_frontmatter.strip().splitlines())
    lines.extend(["---", f"# {title}", ""])
    return "\n".join(lines)


def build_error(
    make_sphinx: SphinxFactory,
    *,
    files: Mapping[str, str | bytes],
    config: Mapping[str, object] | None = None,
    theme: str | None = None,
    extensions: tuple[str, ...] | None = None,
    conf_py_prefix: str = "",
    source_date_epoch: str = "1785542400",
) -> MaatlogBuildError:
    """Build until the first MaatLog fatal diagnostic.

    Some contracts (config, theme API, baseurl, SOURCE_DATE_EPOCH) fail during
    Sphinx application construction; others raise on ``app.build()``.
    """
    try:
        app = make_sphinx(
            files=files,
            config=config,
            theme=theme,
            extensions=extensions,
            conf_py_prefix=conf_py_prefix,
            source_date_epoch=source_date_epoch,
        )
    except MaatlogBuildError as error:
        return error
    with pytest.raises(MaatlogBuildError) as caught:
        app.build()
    return caught.value


# fixture name → (files factory kwargs path handled below)
DIAGNOSTIC_CASES: dict[str, dict[str, Any]] = {
    "unknown-key": {
        "files": {
            "post.rst": _post_rst(extra_fields=":maatlog-publshed-at: 2026-01-01T00:00:00Z"),
        },
        "code": "maatlog.metadata.unknown",
        "field": "maatlog-publshed-at",
    },
    "duplicate": {
        "files": {
            "alpha.rst": _post_rst(slug="shared"),
            "beta.rst": _post_rst(slug="shared", title="Other"),
        },
        "code": "maatlog.slug.duplicate",
        "field": "maatlog-slug",
    },
    "undefined-tag": {
        "files": {"post.rst": _post_rst(extra_fields=":maatlog-tags: missing-tag")},
        "config": {"maatlog_tags": {"known": "Known"}},
        "code": "maatlog.taxonomy.undefined",
        "field": "maatlog-tags",
    },
    "missing-image": {
        "files": {"post.rst": _post_rst(extra_fields=":maatlog-image: missing.png")},
        "code": "maatlog.image.missing",
        "field": "maatlog-image",
    },
    "bad-theme": {
        "files": {"post.rst": _post_rst()},
        "theme": "incompatible",
        "extensions": _THEME_FIXTURE_EXTENSIONS,
        "conf_py_prefix": _THEME_FIXTURE_PREFIX,
        "code": "maatlog.theme.api-incompatible",
        "field": "api",
    },
    "bad-baseurl": {
        "files": {"post.rst": _post_rst()},
        "config": {"html_baseurl": "", "maatlog_generate_feeds": True},
        "code": "maatlog.feed.baseurl-required",
        "field": "html_baseurl",
    },
    "required-slug": {
        "files": {
            "post.rst": ":maatlog-post: true\n\nTitle\n=====\n",
        },
        "code": "maatlog.metadata.required",
        "field": "maatlog-slug",
    },
    "invalid-slug": {
        "files": {"post.rst": _post_rst(slug="NOT_VALID")},
        "code": "maatlog.slug.invalid",
        "field": "maatlog-slug",
    },
    "metadata-type": {
        "files": {
            "post.md": _post_md(extra_frontmatter="maatlog-tags: [python, 42]"),
        },
        "code": "maatlog.metadata.type",
        "field": "maatlog-tags",
    },
    "metadata-value": {
        "files": {
            "post.md": _post_md(extra_frontmatter="maatlog-excerpt: '   '"),
        },
        "code": "maatlog.metadata.value",
        "field": "maatlog-excerpt",
    },
    "without-post": {
        "files": {
            "post.rst": ":maatlog-slug: orphan\n\nTitle\n=====\n",
        },
        "code": "maatlog.metadata.without-post",
        "field": "maatlog-slug",
    },
    "external-without-excerpt": {
        "files": {
            "post.md": _post_md(extra_frontmatter="maatlog-external-url: https://example.com/article"),
        },
        "code": "maatlog.metadata.combination",
        "field": "maatlog-external-url",
    },
    "invalid-url": {
        "files": {
            "post.md": _post_md(extra_frontmatter="maatlog-canonical-url: /relative"),
        },
        "code": "maatlog.url.invalid",
        "field": "maatlog-canonical-url",
    },
    "invalid-image": {
        "files": {"post.rst": _post_rst(extra_fields=":maatlog-image: https://example.com/x.png")},
        "code": "maatlog.image.invalid",
        "field": "maatlog-image",
    },
    "taxonomy-id-invalid": {
        "files": {"post.rst": _post_rst(extra_fields=":maatlog-tags: Bad Tag!")},
        "code": "maatlog.taxonomy-id.invalid",
        "field": "maatlog-tags",
    },
    "datetime-order": {
        "files": {
            "post.rst": _post_rst(
                extra_fields=(":maatlog-published-at: 2026-08-02T09:00:00Z\n:maatlog-expires-at: 2026-08-01T09:00:00Z")
            ),
        },
        "code": "maatlog.datetime.order",
        "field": "maatlog-expires-at",
    },
    "datetime-invalid": {
        "files": {
            "post.rst": _post_rst(extra_fields=":maatlog-published-at: not-a-date"),
        },
        "code": "maatlog.datetime.invalid",
        "field": "maatlog-published-at",
    },
    "config-invalid": {
        "files": {"index.rst": "Root\n====\n"},
        "config": {"maatlog_page_size": 0},
        "code": "maatlog.config.invalid",
        "field": "maatlog_page_size",
    },
    "theme-manifest-missing": {
        "files": {"post.rst": _post_rst()},
        "theme": "missing-manifest",
        "extensions": _THEME_FIXTURE_EXTENSIONS,
        "conf_py_prefix": _THEME_FIXTURE_PREFIX,
        "code": "maatlog.theme.manifest-missing",
        "field": "manifest",
    },
    "theme-block-missing": {
        "files": {"post.rst": _post_rst()},
        "theme": "missing-block",
        "extensions": _THEME_FIXTURE_EXTENSIONS,
        "conf_py_prefix": _THEME_FIXTURE_PREFIX,
        "code": "maatlog.theme.block-missing",
        "field": "block",
    },
    "theme-template-missing": {
        "files": {"post.rst": _post_rst()},
        "theme": "missing-templates",
        "extensions": _THEME_FIXTURE_EXTENSIONS,
        "conf_py_prefix": _THEME_FIXTURE_PREFIX,
        "code": "maatlog.theme.template-missing",
        "field": "template",
    },
    "theme-base-not-inherited": {
        "files": {"post.rst": _post_rst()},
        "theme": "base-not-inherited",
        "extensions": _THEME_FIXTURE_EXTENSIONS,
        "conf_py_prefix": _THEME_FIXTURE_PREFIX,
        "code": "maatlog.theme.base-not-inherited",
        "field": "implementation",
    },
    "archive-option-invalid": {
        "files": {
            "index.rst": "List\n====\n\n.. maatlog:post-list::\n   :limit: not-a-number\n",
        },
        "code": "maatlog.archive.option-invalid",
        "field": "limit",
    },
    "archive-filter-undefined": {
        "files": {
            "index.rst": "List\n====\n\n.. maatlog:post-list::\n   :tags: missing-tag\n",
        },
        "config": {"maatlog_tags": {"known": "Known"}},
        "code": "maatlog.archive.filter-undefined",
        "field": "tags",
    },
    "source-date-epoch-invalid": {
        "files": {"post.rst": _post_rst()},
        "source_date_epoch": "not-an-epoch",
        "code": "maatlog.source-date-epoch.invalid",
        "field": "SOURCE_DATE_EPOCH",
    },
    "generated-docname-conflict": {
        "files": {
            "blog.rst": "Blog\n====\n\nUser page.\n",
            "post.rst": _post_rst(
                slug="one",
                extra_fields=":maatlog-published-at: 2026-07-01T00:00:00Z",
            ),
        },
        "code": "maatlog.generated-docname.conflict",
        "field": "docname",
    },
}


def _case_kwargs(case: dict[str, Any]) -> dict[str, Any]:
    keys = ("files", "config", "theme", "extensions", "conf_py_prefix", "source_date_epoch")
    return {key: case[key] for key in keys if key in case}


@pytest.mark.parametrize("fixture_name", sorted(DIAGNOSTIC_CASES))
def test_fatal_diagnostic_has_location_field_and_expected(
    make_sphinx: SphinxFactory,
    fixture_name: str,
) -> None:
    case = DIAGNOSTIC_CASES[fixture_name]
    code = case["code"]
    field = case["field"]
    error = build_error(make_sphinx, **_case_kwargs(case))
    text = str(error)

    assert f"[{code}]" in text
    assert f"field={field}" in text
    assert "expected=" in text
    assert "ERROR:" in text
    matching = [item for item in error.diagnostics if item.code == code]
    assert matching, f"no diagnostic with code {code}"
    primary = matching[0]
    assert primary.field == field
    assert primary.expected is not None
    # Document diagnostics require a source path. Multi-location messages may
    # embed paths in the summary (e.g. slug.duplicate "found in …"). Config /
    # env diagnostics may omit source when the field names the setting.
    assert (
        primary.source is not None
        or "found in" in primary.message
        or primary.field
        in {
            "html_baseurl",
            "maatlog_page_size",
            "SOURCE_DATE_EPOCH",
            "docname",
        }
    )


def _assert_format_diagnostic_contract(error: MaatlogBuildError, *, code: str, field: str) -> Diagnostic:
    """Shared assertions for ERROR / field / expected on a raised fatal code."""
    text = str(error)
    assert f"[{code}]" in text
    assert f"field={field}" in text
    assert "expected=" in text
    assert "ERROR:" in text
    matching = [item for item in error.diagnostics if item.code == code]
    assert matching, f"no diagnostic with code {code}"
    primary = matching[0]
    assert primary.field == field
    assert primary.expected is not None
    rendered = format_diagnostic(primary)
    assert "ERROR:" in rendered
    assert f"[{code}]" in rendered
    assert f"field={field}" in rendered
    assert "expected=" in rendered
    return primary


class _FakeEnv:
    def __init__(self) -> None:
        self.domaindata: dict[str, dict[str, Any]] = {}


def _unit_post(*, slug: str, docname: str = "post") -> Post:
    return Post(
        docname=docname,
        source_path=f"{docname}.rst",
        title=slug,
        slug=slug,
        published_at=datetime(2026, 7, 1, tzinfo=UTC),
        expires_at=None,
        tags=(),
        categories=(),
        authors=(),
        excerpt=None,
        image_uri=None,
        canonical_url=None,
        external_url=None,
        status=PublicationStatus.PUBLISHED,
    )


def _raise_domain_merge_conflict() -> MaatlogBuildError:
    domain = MaatlogDomain(_FakeEnv())  # type: ignore[arg-type]
    worker = MaatlogDomain(_FakeEnv())  # type: ignore[arg-type]
    domain.note_post(_unit_post(slug="one"))
    worker.note_post(_unit_post(slug="two"))
    with pytest.raises(MaatlogBuildError) as caught:
        domain.merge(worker.data, {"post"})
    return caught.value


def _raise_theme_manifest_invalid() -> MaatlogBuildError:
    with pytest.raises(MaatlogBuildError) as caught:
        parse_and_validate_manifest(
            {},
            core_api=ThemeApiVersion(major=1, minor=0),
            theme_name="demo-theme",
        )
    return caught.value


def _raise_theme_stylesheet_missing() -> MaatlogBuildError:
    with pytest.raises(MaatlogBuildError) as caught:
        _validate_stylesheet(
            [],
            theme_name="no-css-theme",
            inheritance_chain=("no-css-theme",),
            theme_api=CORE_THEME_API,
        )
    return caught.value


def _raise_archive_output_unsafe(tmp_path: Path) -> MaatlogBuildError:
    with pytest.raises(MaatlogBuildError) as caught:
        safe_owned_path(tmp_path, PurePosixPath("../escape.html"))
    return caught.value


def _raise_feed_output_unsafe(tmp_path: Path) -> MaatlogBuildError:
    with pytest.raises(MaatlogBuildError) as caught:
        _stage_all_xml(tmp_path, [("../escape.xml", b"<feed xmlns='http://www.w3.org/2005/Atom'/>")])
    return caught.value


def _raise_feed_xml_invalid(tmp_path: Path) -> MaatlogBuildError:
    temp = tmp_path / "bad-feed.tmp"
    temp.write_bytes(b"<<<not-xml")
    staged = _StagedFeed(relative_path="atom.xml", target=tmp_path / "atom.xml", temp=temp)
    with pytest.raises(MaatlogBuildError) as caught:
        _validate_all_xml([staged])
    return caught.value


def _raise_feed_render_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MaatlogBuildError:
    import maatlog.feeds as feeds_mod
    import maatlog.html_metadata as html_metadata_mod

    outdir = tmp_path / "out"
    doctreedir = tmp_path / "doctrees"
    outdir.mkdir()
    doctreedir.mkdir()
    domain = SimpleNamespace(data={"generated_outputs": {"pages": set(), "feeds": set()}})

    def get_domain(_name: str) -> SimpleNamespace:
        return domain

    def always_true(_value: object) -> bool:
        return True

    def fail_project_feeds(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("forced render failure")

    app = SimpleNamespace(
        builder=SimpleNamespace(name="html"),
        env=SimpleNamespace(get_domain=get_domain),
        outdir=str(outdir),
        doctreedir=str(doctreedir),
    )
    monkeypatch.setattr(feeds_mod, "is_html_archive_builder", always_true)
    monkeypatch.setattr(html_metadata_mod, "discovery_feeds_enabled", always_true)
    monkeypatch.setattr(feeds_mod, "project_feeds", fail_project_feeds)
    with pytest.raises(MaatlogBuildError) as caught:
        write_feeds_after_success(app, None)  # type: ignore[arg-type]
    return caught.value


# Production raise paths exercised at unit level (Sphinx fixtures are hard / redundant).
# Each entry: (code, field, kind) where kind selects the raiser implementation.
UNIT_FATAL_CASES: tuple[tuple[str, str, str], ...] = (
    ("maatlog.domain.merge-conflict", "docname", "merge"),
    ("maatlog.theme.manifest-invalid", "api", "manifest"),
    ("maatlog.theme.stylesheet-missing", "stylesheet", "stylesheet"),
    ("maatlog.archive.output-unsafe", "path", "archive-unsafe"),
    ("maatlog.feed.output-unsafe", "path", "feed-unsafe"),
    ("maatlog.feed.xml-invalid", "path", "feed-xml"),
    ("maatlog.feed.render-failed", "feeds", "feed-render"),
)


def _raise_unit_fatal(
    kind: str,
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> MaatlogBuildError:
    if kind == "merge":
        return _raise_domain_merge_conflict()
    if kind == "manifest":
        return _raise_theme_manifest_invalid()
    if kind == "stylesheet":
        return _raise_theme_stylesheet_missing()
    if kind == "archive-unsafe":
        return _raise_archive_output_unsafe(tmp_path)
    if kind == "feed-unsafe":
        return _raise_feed_output_unsafe(tmp_path)
    if kind == "feed-xml":
        return _raise_feed_xml_invalid(tmp_path)
    if kind == "feed-render":
        return _raise_feed_render_failed(tmp_path, monkeypatch)
    msg = f"unknown unit fatal kind: {kind}"
    raise AssertionError(msg)


@pytest.mark.parametrize(("code", "field", "kind"), UNIT_FATAL_CASES)
def test_unit_fatal_raise_satisfies_format_diagnostic_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    field: str,
    kind: str,
) -> None:
    error = _raise_unit_fatal(kind, tmp_path=tmp_path, monkeypatch=monkeypatch)
    primary = _assert_format_diagnostic_contract(error, code=code, field=field)
    # merge-conflict is a document diagnostic and must carry source.
    if code == "maatlog.domain.merge-conflict":
        assert primary.source is not None


def test_fatal_code_inventory_is_covered() -> None:
    covered = {case["code"] for case in DIAGNOSTIC_CASES.values()} | {code for code, _field, _kind in UNIT_FATAL_CASES}
    missing = sorted(FATAL_CODE_INVENTORY - covered)
    assert missing == [], f"inventory codes without fixtures/unit raisers: {missing}"
    extra = sorted(covered - FATAL_CODE_INVENTORY)
    assert extra == [], f"fixture/unit codes missing from inventory: {extra}"


def _discover_production_codes() -> set[str]:
    """Collect quoted ``maatlog.<area>.<name>`` codes under ``src/maatlog``."""
    root = Path(__file__).resolve().parents[2] / "src" / "maatlog"
    codes: set[str] = set()
    for path in root.rglob("*.py"):
        codes.update(_PRODUCTION_CODE_RE.findall(path.read_text(encoding="utf-8")))
    return codes


def test_fatal_inventory_covers_production_codes() -> None:
    """Inventory must include every production fatal code discovered via source scan."""
    production_fatal = _discover_production_codes() - NON_FATAL_CODE_INVENTORY
    missing = sorted(production_fatal - FATAL_CODE_INVENTORY)
    assert missing == [], f"production fatal codes missing from inventory: {missing}"
    # Inventory may only list real production codes (or known non-fatals excluded above).
    extra = sorted(FATAL_CODE_INVENTORY - production_fatal)
    assert extra == [], f"inventory codes not found in production sources: {extra}"


def test_multi_error_order_is_deterministic(make_sphinx: SphinxFactory) -> None:
    # Same document: unknown key (line 3) and invalid slug (line 2) sort by line then code.
    error = build_error(
        make_sphinx,
        files={
            "post.rst": (":maatlog-post: true\n:maatlog-slug: BAD\n:maatlog-publshed-at: 1\n\nTitle\n=====\n"),
        },
    )
    codes = [item.code for item in error.diagnostics]
    assert codes == sorted(
        codes,
        key=lambda code: next(
            (item.line if item.line is not None else -1, item.code) for item in error.diagnostics if item.code == code
        ),
    )
    assert [item.code for item in error.diagnostics] == [
        item.code
        for item in sorted(
            error.diagnostics,
            key=lambda d: (d.source or "", d.line if d.line is not None else -1, d.code),
        )
    ]
    lines = str(error).splitlines()
    assert len(lines) >= 2
    assert all("ERROR:" in line for line in lines)
    # line 2 invalid slug before line 3 unknown key
    assert error.diagnostics[0].line == 2
    assert error.diagnostics[0].code == "maatlog.slug.invalid"
    assert error.diagnostics[1].line == 3
    assert error.diagnostics[1].code == "maatlog.metadata.unknown"


def test_userinfo_is_redacted_in_url_diagnostic(make_sphinx: SphinxFactory) -> None:
    error = build_error(
        make_sphinx,
        files={
            "post.md": _post_md(extra_frontmatter="maatlog-canonical-url: https://secret:token@example.com/path#frag"),
        },
    )
    text = str(error)
    assert "maatlog.url.invalid" in text
    assert "secret" not in text
    assert "token" not in text
    assert "example.com" in text
    diagnostic = next(item for item in error.diagnostics if item.code == "maatlog.url.invalid")
    assert diagnostic.value is not None
    assert "secret" not in diagnostic.value
    assert "token" not in diagnostic.value


def test_userinfo_is_redacted_for_invalid_baseurl(make_sphinx: SphinxFactory) -> None:
    error = build_error(
        make_sphinx,
        files={"post.rst": _post_rst()},
        config={"html_baseurl": "https://secret:token@example.com/blog", "maatlog_generate_feeds": True},
    )
    text = str(error)
    assert "maatlog.feed.baseurl-required" in text
    assert "secret" not in text
    assert "token" not in text
    assert "example.com" in text


def test_long_diagnostic_value_is_truncated_in_format() -> None:
    huge = "x" * 500
    diagnostic = Diagnostic(
        code="maatlog.metadata.value",
        message="too long",
        source="post.rst",
        line=1,
        field="maatlog-excerpt",
        value=repr(huge),
        expected="a non-empty string",
    )
    rendered = safe_value(diagnostic)
    assert rendered is not None
    assert len(rendered) <= 120
    assert rendered.endswith("...")
    text = format_diagnostic(diagnostic)
    assert "..." in text
    assert huge not in text


def test_fatal_failure_does_not_require_warning_as_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Schema / slug failures raise MaatlogBuildError without relying on Sphinx -W."""
    root = tmp_path / "nowarn"
    srcdir = root / "source"
    srcdir.mkdir(parents=True)
    (srcdir / "conf.py").write_text(
        "extensions = ['maatlog']\n"
        "source_suffix = {'.rst': 'restructuredtext'}\n"
        "root_doc = 'index'\n"
        "html_theme = 'maatlog-default'\n"
        "html_baseurl = 'https://example.test/'\n",
        encoding="utf-8",
    )
    (srcdir / "index.rst").write_text(
        "Root\n====\n\n.. toctree::\n\n   post\n",
        encoding="utf-8",
    )
    (srcdir / "post.rst").write_text(
        ":maatlog-post: true\n:maatlog-slug: BAD\n\nTitle\n=====\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1785542400")
    app = Sphinx(
        str(srcdir),
        str(srcdir),
        str(root / "output"),
        str(root / "doctrees"),
        "html",
        status=StringIO(),
        warning=StringIO(),
        warningiserror=False,
        freshenv=True,
    )
    with pytest.raises(MaatlogBuildError) as caught:
        app.build()
    assert "maatlog.slug.invalid" in str(caught.value)
    assert "ERROR:" in str(caught.value)
    assert "field=maatlog-slug" in str(caught.value)


def test_valid_project_builds_clean(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(
        files={
            "post.rst": _post_rst(
                slug="ok-post",
                extra_fields=":maatlog-published-at: 2026-07-01T00:00:00Z",
            ),
        },
        config={"maatlog_tags": None},
    )
    app.build()
    posts = app.env.get_domain("maatlog").data["posts_by_docname"]
    assert "post" in posts
