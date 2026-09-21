"""Regression tests for the shipped ``docs/`` project (Issue #357)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pytest
from conftest import HtmlPage
from sphinx.application import Sphinx
from sphinx.environment import BuildEnvironment

DOCS_ROOT = Path(__file__).resolve().parents[2] / "docs"
REPO_ROOT = DOCS_ROOT.parent

EXPECTED_CAPTIONS = ("初めての方", "目的別ガイド", "トラブルシューティング", "リファレンス")
SOURCE_DATE_EPOCH = "1785542400"


@dataclass(frozen=True)
class DocsBuild:
    """Output of one subprocess ``python -m sphinx`` build of ``docs/``."""

    result: subprocess.CompletedProcess[str]
    outdir: Path

    def html(self, relative: str) -> HtmlPage:
        return HtmlPage((self.outdir / relative).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def built_docs(tmp_path_factory: pytest.TempPathFactory) -> DocsBuild:
    """Build ``docs/`` in a fresh subprocess: ``python -m sphinx -W --keep-going``.

    A subprocess isolates the build from node registrations left behind by
    other Sphinx apps in this pytest worker, so ``-W`` measures docs warnings
    alone. ``--keep-going`` reports every warning instead of stopping early.
    """
    outdir = tmp_path_factory.mktemp("docs") / "html"
    command = [
        sys.executable,
        "-m",
        "sphinx",
        "-W",
        "--keep-going",
        "-b",
        "html",
        "-d",
        str(outdir.parent / "doctrees"),
        str(DOCS_ROOT),
        str(outdir),
    ]
    env = dict(os.environ)
    env["SOURCE_DATE_EPOCH"] = SOURCE_DATE_EPOCH
    env.pop("PYTHONPATH", None)
    result = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False)
    return DocsBuild(result=result, outdir=outdir)


@pytest.fixture(scope="module")
def docs_env(tmp_path_factory: pytest.TempPathFactory) -> BuildEnvironment:
    """In-process build used only to inspect environment internals.

    Its warning stream is irrelevant (the subprocess fixture owns the
    warning-free assertion); this exists for ``found_docs`` /
    ``files_to_rebuild`` / ``metadata`` access.
    """
    outdir = tmp_path_factory.mktemp("docs-env")
    app = Sphinx(
        str(DOCS_ROOT),
        str(DOCS_ROOT),
        str(outdir / "html"),
        str(outdir / "doctrees"),
        "html",
        status=StringIO(),
        warning=StringIO(),
        freshenv=True,
    )
    app.build()
    return app.env


def test_docs_build_has_no_warnings(built_docs: DocsBuild) -> None:
    assert built_docs.result.returncode == 0, built_docs.result.stderr
    assert "WARNING" not in built_docs.result.stderr


def test_docs_index_shows_expected_captions(built_docs: DocsBuild) -> None:
    """Captions of the ``index.rst`` toctrees, in declaration order.

    ``span.caption-text`` also marks figure and code-block captions, so
    collect only inside ``.toctree-wrapper`` blocks: a non-toctree caption
    on the landing page must not fail this test. Order is significant —
    the toctree sequence is part of the navigation design.
    """
    index = built_docs.html("index.html")
    wrappers = re.findall(r'<div class="toctree-wrapper[^"]*">(.*?)</div>', index.text, re.DOTALL)
    captions = [
        caption
        for wrapper in wrappers
        for caption in re.findall(r'<span class="caption-text">([^<]+)</span>', wrapper)
    ]
    assert captions == list(EXPECTED_CAPTIONS)


def test_docs_index_links_all_pages(built_docs: DocsBuild) -> None:
    """Every source page must be reachable from the index navigation.

    The expectation derives from the on-disk sources rather than toctree
    bookkeeping so that a page silently dropped from every toctree still fails
    here instead of shrinking the expected set.
    """
    index = built_docs.html("index.html")
    for source in sorted(DOCS_ROOT.rglob("*.rst")):
        relative = source.relative_to(DOCS_ROOT)
        if relative.parts[0] == "_build" or relative.as_posix() == "index.rst":
            continue
        docname = relative.with_suffix("").as_posix()
        assert index.select_one(f"a[href='{docname}.html']") is not None, docname


def test_docs_orphan_marks_only_pages_outside_toctrees(docs_env: BuildEnvironment) -> None:
    """``:orphan:`` must be present exactly on docs unreachable from any toctree.

    A toctree-registered page keeping ``:orphan:`` (the glossary regression) is
    invisible to the build: Sphinx only warns on non-included non-orphan docs.
    The membership sets below mirror ``check_consistency``: the root doc,
    ``files_to_rebuild`` keys (every docname listed in some toctree), and
    ``env.included`` targets (``.. include::`` sources).
    """
    included: set[str] = {docs_env.config.root_doc}
    included.update(docs_env.files_to_rebuild)
    included.update(*docs_env.included.values())
    orphans = {docname for docname in docs_env.found_docs if "orphan" in docs_env.metadata[docname]}
    assert docs_env.found_docs == included | orphans
    assert included.isdisjoint(orphans)
