"""Subprocess driver that runs a real ``python -m sphinx`` build (task E).

The driver only materialises the source tree produced by
``fixtures.responsive_real_project.project_files`` plus a ``conf.py`` made
from ``project_config`` -- the actual generation path stays whatever the
normal extension setup registers, so tests observe real output, doctrees and
cache directories instead of injected fakes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from fixtures.responsive_real_project import project_config, project_files

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fixtures.responsive_images.worker import WorkerBarrier

_CONF_TEMPLATE = """\
extensions = ["maatlog"]
html_theme = "maatlog-default"
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
root_doc = "index"
exclude_patterns = []
"""

_SOURCE_DATE_EPOCH = "1785542400"


@dataclass(frozen=True)
class RealProject:
    """An on-disk Sphinx project plus where its build artifacts live."""

    root: Path
    srcdir: Path
    outdir: Path
    doctreedir: Path
    builder: str

    def build(
        self,
        *,
        python: Path | None = None,
        parallel: int = 1,
        fresh: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run ``python -m sphinx`` and return the captured process result."""
        executable = str(python) if python is not None else sys.executable
        command = [
            executable,
            "-m",
            "sphinx",
            "-W",
            "--keep-going",
            "-b",
            self.builder,
            "-j",
            str(parallel),
            "-d",
            str(self.doctreedir),
        ]
        if fresh:
            command.append("-E")
        command.extend((str(self.srcdir), str(self.outdir)))
        env = dict(os.environ)
        env["SOURCE_DATE_EPOCH"] = _SOURCE_DATE_EPOCH
        env.pop("PYTHONPATH", None)
        return subprocess.run(command, cwd=self.root, env=env, capture_output=True, text=True, check=False)


def _conf_source(config: Mapping[str, object]) -> str:
    lines = [_CONF_TEMPLATE]
    for name, value in config.items():
        lines.append(f"{name} = {value!r}\n")
    return "".join(lines)


def create_project(
    root: Path,
    *,
    builder: str = "html",
    enabled: bool = True,
    page_size: int = 20,
    source_name: str = "photo.jpg",
    post_count: int = 15,
    files: Mapping[str, str | bytes] | None = None,
    config: Mapping[str, object] | None = None,
) -> RealProject:
    """Write a complete Sphinx project under ``root`` and return its driver."""
    srcdir = root / "src"
    outdir = root / "_build" / builder
    doctreedir = root / "_build" / ".doctrees"
    if files is None:
        files = project_files(source_name=source_name, post_count=post_count)
    for relpath, content in files.items():
        destination = srcdir / relpath
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            destination.write_bytes(content)
        else:
            destination.write_text(content, encoding="utf-8")
    merged = project_config(enabled=enabled, page_size=page_size)
    if config is not None:
        merged.update(config)
    srcdir.mkdir(parents=True, exist_ok=True)
    (srcdir / "conf.py").write_text(_conf_source(merged), encoding="utf-8")
    return RealProject(
        root=root,
        srcdir=srcdir,
        outdir=outdir,
        doctreedir=doctreedir,
        builder=builder,
    )


def shared_cache_build_worker(
    srcdir: str,
    outdir: str,
    doctreedir: str,
    builder: str,
    shared_cache: str,
    result_path: str,
    barrier: WorkerBarrier,
) -> None:
    """Build one project in a spawned process against a shared variant cache.

    Module-level so ``multiprocessing`` ``spawn`` can pickle the call. The only
    state shared between workers is *shared_cache*: it replaces the
    ``RESPONSIVE_CACHE_DIRNAME`` composition in
    ``maatlog.responsive_image_build`` with an absolute path for the duration of
    this build (``Path(doctreedir) / absolute`` resolves to the absolute path),
    while srcdir/outdir/doctreedir stay per-process. The ``_encode_variant``
    wrapper meets the other worker at *barrier* once -- right before this
    process's first encode on a cold cache -- then delegates to the real
    encoder unchanged. Build status lands in *result_path*; a build failure
    re-raises so the process exits non-zero.
    """
    import json
    from io import StringIO
    from typing import Any, cast
    from unittest.mock import patch

    from sphinx.application import Sphinx

    import maatlog.responsive_image_build as build_module
    import maatlog.responsive_images as backend

    os.environ["SOURCE_DATE_EPOCH"] = _SOURCE_DATE_EPOCH
    warning_stream = StringIO()
    result: dict[str, object] = {"pid": os.getpid(), "built": False}
    real_encode = cast(Any, backend._encode_variant)  # pyright: ignore[reportPrivateUsage]
    rendezvoused = False

    def observed_encode(source_bytes: bytes, request: Any, encoder: Any, target: Path) -> None:
        nonlocal rendezvoused
        if not rendezvoused:
            rendezvoused = True
            barrier.wait(timeout=30)
        real_encode(source_bytes, request, encoder, target)

    try:
        app = Sphinx(
            srcdir,
            srcdir,
            outdir,
            doctreedir,
            builder,
            status=StringIO(),
            warning=warning_stream,
            warningiserror=True,
        )
        cache = str(Path(shared_cache).resolve())
        with (
            patch.object(build_module, "RESPONSIVE_CACHE_DIRNAME", cache),
            patch.object(backend, "_encode_variant", observed_encode),
        ):
            app.build()
        result["built"] = True
        result["rendezvoused"] = rendezvoused
    except Exception as exc:
        result["error"] = repr(exc)
        Path(result_path).write_text(json.dumps(result), encoding="utf-8")
        raise
    result["warnings"] = warning_stream.getvalue()
    Path(result_path).write_text(json.dumps(result), encoding="utf-8")
