"""Integration coverage for the default responsive image backend wiring.

``maatlog.extension.setup`` registers a factory that builds the real Pillow
generator lazily, so a normal ``maatlog_responsive_images = True`` build needs
no test-side injection -- while disabled and non-full-HTML builds must never
call that factory or import the backend module.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import SphinxFactory
from fixtures.responsive_image_fixtures import make_test_png

from maatlog.responsive_image_build import responsive_manifest

FILES: dict[str, str | bytes] = {
    "index.rst": "Index\n=====\n\n.. toctree::\n\n   post\n",
    "post.rst": (
        ":maatlog-post: true\n:maatlog-slug: real\n"
        ":maatlog-published-at: 2026-07-01T00:00:00Z\n"
        ":maatlog-image: img/hero.png\n\nPost\n====\n\n"
        ".. maatlog:maattop:: img/hero.png\n\nBody.\n"
    ),
    "img/hero.png": make_test_png(960, 540),
}


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_default_factory_builds_real_variants(make_sphinx: SphinxFactory, builder: str) -> None:
    app = make_sphinx(
        files=FILES,
        builder=builder,
        theme="maatlog-default",
        config={"maatlog_responsive_images": True, "maatlog_responsive_image_widths": (480, 768)},
    )
    app.build()
    entry = responsive_manifest(app.env)["img/hero.png"]
    assert [v.width for v in entry.variants] == [480, 768, 960]
    output = Path(app.outdir) / "_images" / "maatlog"
    assert all((output / v.public_basename).is_file() for v in entry.variants)
    html_path = Path(app.outdir) / ("post.html" if builder == "html" else "post/index.html")
    assert 'data-maatlog-srcset="w-v1"' in html_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("builder", "enabled"),
    [("html", False), ("text", True), ("singlehtml", True)],
)
def test_disabled_or_partial_build_never_calls_the_default_factory(
    make_sphinx: SphinxFactory,
    monkeypatch: pytest.MonkeyPatch,
    builder: str,
    enabled: bool,
) -> None:
    """Substituted before app construction, the factory must stay uncalled."""

    def fail_factory() -> None:
        raise AssertionError("the default image backend factory must not run on this build")

    monkeypatch.setattr("maatlog.extension._create_responsive_image_generator", fail_factory)
    app = make_sphinx(files=FILES, builder=builder, config={"maatlog_responsive_images": enabled})
    app.build()
    assert responsive_manifest(app.env) == {}
    assert [path for path in Path(app.outdir).rglob("maatlog")] == []


def test_disabled_build_never_imports_the_generator_module(tmp_path: Path) -> None:
    """In a fresh interpreter an OFF build must not import the backend module.

    Runs in a subprocess so the assertion sees the real module table: the
    in-process suite already holds ``maatlog.responsive_images`` once any
    backend test has run. Sphinx's own optional PIL import during app init is
    not a MaatLog backend call and is not asserted on.
    """
    srcdir = tmp_path / "source"
    (srcdir / "img").mkdir(parents=True)
    index = FILES["index.rst"]
    post = FILES["post.rst"]
    assert isinstance(index, str) and isinstance(post, str)
    (srcdir / "conf.py").write_text(
        "\n".join(
            [
                "extensions = ['maatlog']",
                "source_suffix = {'.rst': 'restructuredtext'}",
                "root_doc = 'index'",
                "html_theme = 'maatlog-default'",
                "html_baseurl = 'https://example.test/'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (srcdir / "index.rst").write_text(index, encoding="utf-8")
    (srcdir / "post.rst").write_text(post, encoding="utf-8")
    (srcdir / "img" / "hero.png").write_bytes(make_test_png(960, 540))
    script = (
        "import sys\n"
        "from io import StringIO\n"
        "from sphinx.application import Sphinx\n"
        f"app = Sphinx({str(srcdir)!r}, {str(srcdir)!r}, {str(tmp_path / 'output')!r},"
        f" {str(tmp_path / 'doctrees')!r}, 'html', status=StringIO(), warning=StringIO(),"
        " warningiserror=True)\n"
        "app.build()\n"
        "leaked = sorted(\n"
        "    name for name in sys.modules\n"
        "    if name == 'maatlog.responsive_images' or name.startswith('maatlog._responsive_image')\n"
        ")\n"
        "assert not leaked, leaked\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
