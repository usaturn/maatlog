from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from typing import Protocol

import pytest
from sphinx.application import Sphinx

from maatlog.domain import MaatlogDomain
from maatlog.model import Post
from maatlog.taxonomy import DomainIndex


class SphinxFactory(Protocol):
    def __call__(
        self,
        *,
        files: Mapping[str, str | bytes],
        source_date_epoch: str = "1785542400",
        config: Mapping[str, object] | None = None,
        builder: str = "html",
        theme: str | None = None,
        extensions: Sequence[str] | None = None,
        conf_py_prefix: str = "",
        parallel: int = 0,
        freshenv: bool = True,
    ) -> Sphinx: ...


class ProjectFactory(Protocol):
    def __call__(
        self,
        *,
        files: Mapping[str, str | bytes],
        source_date_epoch: str = "1785542400",
        config: Mapping[str, object] | None = None,
        builder: str = "html",
        theme: str | None = None,
        extensions: Sequence[str] | None = None,
        conf_py_prefix: str = "",
    ) -> SphinxProject: ...


@dataclass(frozen=True)
class DomainSnapshot:
    """Pickle-friendly projection of maatlog domain data for equality checks."""

    posts_by_docname: dict[str, Post]
    published_slugs: tuple[str, ...]
    docname_by_slug: dict[str, str]
    members: dict[str, dict[str, tuple[str, ...]]]
    labels: dict[str, dict[str, str]]

    @classmethod
    def from_domain(cls, domain: MaatlogDomain) -> DomainSnapshot:
        posts = dict(domain.data["posts_by_docname"])
        index = domain.data.get("index")
        if index is None:
            return cls(
                posts_by_docname=posts,
                published_slugs=(),
                docname_by_slug={},
                members={},
                labels={},
            )
        assert isinstance(index, DomainIndex)
        return cls(
            posts_by_docname=posts,
            published_slugs=tuple(post.slug for post in index.published),
            docname_by_slug=dict(index.docname_by_slug),
            members={axis.value: {k: tuple(v) for k, v in mapping.items()} for axis, mapping in index.members.items()},
            labels={axis.value: dict(mapping) for axis, mapping in index.labels.items()},
        )


class _MatchCollector(HTMLParser):
    """Collect start tags that match a simple CSS-like selector chain."""

    def __init__(self, steps: Sequence[tuple[str | None, frozenset[str], Mapping[str, str]]]) -> None:
        super().__init__()
        self._steps = list(steps)
        self._open: list[tuple[str, frozenset[str], dict[str, str]]] = []
        self.matches: list[dict[str, str]] = []
        self.match: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: (value or "") for name, value in attrs}
        class_tokens = frozenset(token for token in attr_map.get("class", "").split() if token)
        self._open.append((tag, class_tokens, attr_map))
        if self._matches_chain():
            self.matches.append(attr_map)
            if self.match is None:
                self.match = attr_map

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Void / self-closing tags (e.g. ``<link ... />``) never get an end tag.
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._open) - 1, -1, -1):
            if self._open[index][0] == tag:
                del self._open[index:]
                break

    def _matches_step(
        self,
        step: tuple[str | None, frozenset[str], Mapping[str, str]],
        tag: str,
        class_tokens: frozenset[str],
        attr_map: Mapping[str, str],
    ) -> bool:
        expected_tag, classes, attrs = step
        if expected_tag is not None and tag != expected_tag:
            return False
        if not classes.issubset(class_tokens):
            return False
        return all(attr_map.get(key) == expected for key, expected in attrs.items())

    def _matches_chain(self) -> bool:
        """True when the current start tag is the final selector step under ancestors."""
        if not self._steps or not self._open:
            return False
        # The last step must match the element that just opened.
        last = self._steps[-1]
        tag, class_tokens, attr_map = self._open[-1]
        if not self._matches_step(last, tag, class_tokens, attr_map):
            return False
        if len(self._steps) == 1:
            return True
        # Prior steps must appear in order among strict ancestors.
        step_index = 0
        for ancestor_tag, class_tokens, attr_map in self._open[:-1]:
            if not self._matches_step(self._steps[step_index], ancestor_tag, class_tokens, attr_map):
                continue
            step_index += 1
            if step_index == len(self._steps) - 1:
                return True
        return False


def _parse_selector(selector: str) -> list[tuple[str | None, frozenset[str], dict[str, str]]]:
    """Parse ``link[rel='canonical']``, ``.a.b[attr='v'] .c`` into match steps.

    Each step is ``(tag_or_None, classes, exact_attrs)``. Tag names are optional;
    attribute selectors support exact ``[attr='v']`` only.
    """
    steps: list[tuple[str | None, frozenset[str], dict[str, str]]] = []
    for fragment in selector.strip().split():
        classes: set[str] = set()
        attrs: dict[str, str] = {}
        remainder = fragment
        tag: str | None = None
        tag_match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*)", remainder)
        if tag_match and not remainder.startswith("."):
            tag = tag_match.group(1).lower()
            remainder = remainder[tag_match.end() :]
        while remainder:
            if remainder.startswith("."):
                match = re.match(r"\.([A-Za-z0-9_-]+)", remainder)
                if not match:
                    msg = f"unsupported selector fragment: {remainder!r}"
                    raise ValueError(msg)
                classes.add(match.group(1))
                remainder = remainder[match.end() :]
                continue
            if remainder.startswith("["):
                match = re.match(
                    r"\[([A-Za-z0-9_-]+)=(['\"])(.*?)\2\]",
                    remainder,
                )
                if not match:
                    msg = f"unsupported attribute selector: {remainder!r}"
                    raise ValueError(msg)
                attrs[match.group(1)] = match.group(3)
                remainder = remainder[match.end() :]
                continue
            msg = f"unsupported selector: {selector!r}"
            raise ValueError(msg)
        steps.append((tag, frozenset(classes), attrs))
    if not steps:
        msg = f"unsupported selector: {selector!r}"
        raise ValueError(msg)
    return steps


@dataclass(frozen=True)
class HtmlPage:
    """Minimal HTML helper for theme contract assertions (stdlib only)."""

    text: str

    def select_one(self, selector: str) -> dict[str, str] | None:
        """Return the first start-tag attributes matching a simple selector.

        Supports ``.class``, ``[attr='value']`` / ``[attr="value"]``, descendant
        combinators (``A B``), and combinations such as
        ``.maatlog-post[data-maatlog-component='post']``.
        """
        collector = _MatchCollector(_parse_selector(selector))
        collector.feed(self.text)
        return collector.match

    def select(self, selector: str) -> list[dict[str, str]]:
        """Return all start-tag attributes matching a simple selector."""
        collector = _MatchCollector(_parse_selector(selector))
        collector.feed(self.text)
        return collector.matches

    def __contains__(self, item: object) -> bool:
        return isinstance(item, str) and item in self.text


@dataclass
class BuildResult:
    app: Sphinx

    def domain_snapshot(self, name: str = "maatlog") -> DomainSnapshot:
        domain = self.app.env.get_domain(name)
        assert isinstance(domain, MaatlogDomain)
        return DomainSnapshot.from_domain(domain)

    def domain_data(self, name: str = "maatlog") -> DomainSnapshot:
        """Alias matching plan sketches; comparable domain projection."""
        return self.domain_snapshot(name)

    def path(self, relative: str) -> Path:
        return Path(self.app.outdir) / relative

    def html(self, relative: str) -> HtmlPage:
        return HtmlPage(self.path(relative).read_text(encoding="utf-8"))

    def asset(self, relative: str) -> Path:
        return self.path(relative)


class SphinxProject:
    """Mutable Sphinx project that supports incremental and parallel rebuilds."""

    def __init__(
        self,
        root: Path,
        *,
        files: Mapping[str, str | bytes],
        source_date_epoch: str = "1785542400",
        config: Mapping[str, object] | None = None,
        builder: str = "html",
        theme: str | None = None,
        extensions: Sequence[str] | None = None,
        conf_py_prefix: str = "",
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self.root = root
        self.srcdir = root / "source"
        self.outdir = root / "output"
        self.doctreedir = root / "doctrees"
        self.builder = builder
        self.source_date_epoch = source_date_epoch
        self.config = dict(config or {})
        # Official MaatLog HTML default so Theme API validation hard-fails cleanly
        # for third-party themes without a final-theme manifest (no alabaster soft-skip).
        self.config.setdefault("html_theme", theme if theme is not None else "maatlog-default")
        # Feeds default on; provide a valid base so builder-inited validation passes.
        self.config.setdefault("html_baseurl", "https://example.test/")
        self.extensions = ["maatlog", *(extensions or ())]
        self.conf_py_prefix = conf_py_prefix
        self._monkeypatch = monkeypatch
        self._files: dict[str, str | bytes] = dict(files)
        self.srcdir.mkdir(parents=True, exist_ok=True)
        self._write_tree()

    def write(self, name: str, content: str | bytes) -> None:
        self._files[name] = content
        self._write_file(name, content)
        if name.endswith((".rst", ".md")):
            self._refresh_index()

    def remove(self, name: str) -> None:
        self._files.pop(name, None)
        target = self.srcdir / name
        if target.exists():
            target.unlink()
        if name.endswith((".rst", ".md")):
            self._refresh_index()

    def build(
        self,
        *,
        reuse_environment: bool = False,
        parallel: int = 0,
        force_parallel_read: bool | None = None,
    ) -> BuildResult:
        """Build the project.

        ``reuse_environment=True`` keeps doctrees (``freshenv=False``).
        When ``parallel > 1`` and the extension still reports read-unsafe,
        ``force_parallel_read`` (default True for parallel>1) enables the
        parallel read path so merge is exercised before the safety flag flip.
        """
        self._monkeypatch.setenv("SOURCE_DATE_EPOCH", self.source_date_epoch)
        app = Sphinx(
            str(self.srcdir),
            str(self.srcdir),
            str(self.outdir),
            str(self.doctreedir),
            self.builder,
            status=StringIO(),
            warning=StringIO(),
            warningiserror=True,
            freshenv=not reuse_environment,
            parallel=parallel,
        )
        if force_parallel_read is None:
            force_parallel_read = parallel > 1
        if force_parallel_read and "maatlog" in app.extensions:
            app.extensions["maatlog"].parallel_read_safe = True
        app.build()
        return BuildResult(app=app)

    def _write_tree(self) -> None:
        self._write_conf()
        for name, content in self._files.items():
            self._write_file(name, content)
        self._refresh_index()

    def rewrite_conf(self) -> None:
        """Rewrite ``conf.py`` from the current ``config`` mapping (for rebuild tests)."""
        self._write_conf()

    def _write_conf(self) -> None:
        config_lines = [
            self.conf_py_prefix.rstrip(),
            f"extensions = {list(self.extensions)!r}",
            "source_suffix = {'.rst': 'restructuredtext', '.md': 'markdown'}",
            "root_doc = 'index'",
        ]
        config_lines = [line for line in config_lines if line]
        for name, value in self.config.items():
            config_lines.append(f"{name} = {value!r}")
        (self.srcdir / "conf.py").write_text("\n".join(config_lines) + "\n", encoding="utf-8")

    def _write_file(self, name: str, content: str | bytes) -> None:
        target = self.srcdir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    def _refresh_index(self) -> None:
        if "index.rst" in self._files:
            # Caller owns the master document.
            self._write_file("index.rst", self._files["index.rst"])
            return
        docnames = sorted(
            Path(name).with_suffix("").as_posix()
            for name in self._files
            if Path(name).suffix in {".rst", ".md"} and name != "index.rst"
        )
        entries = "\n".join(f"   {docname}" for docname in docnames)
        body = f"Root\n====\n\n.. toctree::\n\n{entries}\n"
        self._write_file("index.rst", body)


def _merge_config(
    config: Mapping[str, object] | None,
    *,
    theme: str | None,
) -> dict[str, object]:
    merged = dict(config or {})
    merged.setdefault("html_theme", theme if theme is not None else "maatlog-default")
    # Feeds default on; provide a valid base so builder-inited validation passes.
    merged.setdefault("html_baseurl", "https://example.test/")
    return merged


def _create_sphinx_app(
    *,
    root: Path,
    files: Mapping[str, str | bytes],
    source_date_epoch: str,
    config: Mapping[str, object] | None,
    builder: str,
    theme: str | None,
    extensions: Sequence[str] | None,
    conf_py_prefix: str,
    parallel: int,
    freshenv: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> Sphinx:
    """Create an unbuilt Sphinx app (legacy make_sphinx behaviour)."""
    srcdir = root / "source"
    srcdir.mkdir(parents=True)
    supplied_files = dict(files)
    docnames = sorted(
        Path(name).with_suffix("").as_posix()
        for name in supplied_files
        if Path(name).suffix in {".rst", ".md"} and name != "index.rst"
    )
    if "index.rst" not in supplied_files:
        entries = "\n".join(f"   {docname}" for docname in docnames)
        supplied_files["index.rst"] = f"Root\n====\n\n.. toctree::\n\n{entries}\n"

    extension_list = ["maatlog", *(extensions or ())]
    merged_config = _merge_config(config, theme=theme)
    config_lines = [
        conf_py_prefix.rstrip(),
        f"extensions = {list(extension_list)!r}",
        "source_suffix = {'.rst': 'restructuredtext', '.md': 'markdown'}",
        "root_doc = 'index'",
    ]
    config_lines = [line for line in config_lines if line]
    for name, value in merged_config.items():
        config_lines.append(f"{name} = {value!r}")
    (srcdir / "conf.py").write_text("\n".join(config_lines) + "\n", encoding="utf-8")
    for name, content in supplied_files.items():
        target = srcdir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    monkeypatch.setenv("SOURCE_DATE_EPOCH", source_date_epoch)
    return Sphinx(
        str(srcdir),
        str(srcdir),
        str(root / "output"),
        str(root / "doctrees"),
        builder,
        status=StringIO(),
        warning=StringIO(),
        warningiserror=True,
        freshenv=freshenv,
        parallel=parallel,
    )


@pytest.fixture
def make_sphinx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SphinxFactory:
    project_number = 0

    def factory(
        *,
        files: Mapping[str, str | bytes],
        source_date_epoch: str = "1785542400",
        config: Mapping[str, object] | None = None,
        builder: str = "html",
        theme: str | None = None,
        extensions: Sequence[str] | None = None,
        conf_py_prefix: str = "",
        parallel: int = 0,
        freshenv: bool = True,
    ) -> Sphinx:
        nonlocal project_number
        project_number += 1
        return _create_sphinx_app(
            root=tmp_path / f"project-{project_number}",
            files=files,
            source_date_epoch=source_date_epoch,
            config=config,
            builder=builder,
            theme=theme,
            extensions=extensions,
            conf_py_prefix=conf_py_prefix,
            parallel=parallel,
            freshenv=freshenv,
            monkeypatch=monkeypatch,
        )

    return factory


@pytest.fixture
def make_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjectFactory:
    project_number = 0

    def factory(
        *,
        files: Mapping[str, str | bytes],
        source_date_epoch: str = "1785542400",
        config: Mapping[str, object] | None = None,
        builder: str = "html",
        theme: str | None = None,
        extensions: Sequence[str] | None = None,
        conf_py_prefix: str = "",
    ) -> SphinxProject:
        nonlocal project_number
        project_number += 1
        return SphinxProject(
            tmp_path / f"project-{project_number}",
            files=files,
            source_date_epoch=source_date_epoch,
            config=config,
            builder=builder,
            theme=theme,
            extensions=extensions,
            conf_py_prefix=conf_py_prefix,
            monkeypatch=monkeypatch,
        )

    return factory
