"""Parallel writers and cross-process shared cache (issue #215 lane C, Task 5).

The Sphinx writer-parallel test shows page writing fanning out to workers
while variant generation stays in the parent process: the generator appends
every probe/generate PID to a log file, so generation inside a forked worker
would be visible to the parent, with identical manifests and published bytes
across serial and parallel builds. The OS-process test proves two independent
drivers can share one explicit cache root through the adapter publication path
(``AtomicTestGenerator.generate`` -> ``publish_variants`` ->
``commit_owned_variants``) without a shared Sphinx environment.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import SphinxFactory
from fixtures import responsive_build_fixtures as build_fixtures
from fixtures.responsive_build_fixtures import RecordingGenerator, parallel_files, reopen_build
from sphinx.application import Sphinx

from maatlog.image_contracts import register_variant_generator_factory
from maatlog.responsive_image_build import responsive_manifest
from maatlog.responsive_image_output import commit_owned_variants

#: Sidecar directory (under the output directory) holding one PID file per
#: written page. Each writer process writes only its own pagename file, so
#: parallel workers never contend.
_WRITER_PID_DIRNAME = "_responsive_worker_pids"

_DRIVER_PATH = str(Path(build_fixtures.__file__).resolve())
_TESTS_DIR = str(Path(build_fixtures.__file__).resolve().parent.parent)


def _record_writer_pid(app: Any, pagename: str, templatename: str, context: Any, doctree: Any) -> None:
    """Persist the writing process PID for one page (test-only).

    Connected at ``html-page-context``. Each worker writes only its own
    pagename file, so parallel writers never contend.
    """
    del templatename, context, doctree
    sidecar = Path(str(app.outdir)) / _WRITER_PID_DIRNAME / f"{pagename}.txt"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(f"{os.getpid()}\n", encoding="utf-8")


def _writer_pids(app: Sphinx) -> dict[str, int]:
    """Process IDs recorded per written page, keyed by pagename (test-only)."""
    root = Path(app.outdir) / _WRITER_PID_DIRNAME
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).with_suffix("").as_posix(): int(path.read_text(encoding="utf-8").strip())
        for path in sorted(root.rglob("*.txt"))
    }


def _output_bytes(output_root: Path) -> dict[str, bytes]:
    """Published variant bytes by basename for an explicit output root (test-only)."""
    return {
        path.name: path.read_bytes()
        for path in sorted(output_root.iterdir())
        if path.is_file() and not path.name.startswith(".")
    }


def _public_state(app: Sphinx) -> dict[str, bytes]:
    """Published variant bytes by basename, ignoring ownership records (test-only)."""
    return _output_bytes(Path(app.outdir) / str(app.builder.imagedir) / "maatlog")


def _tree_bytes(root: Path) -> dict[str, bytes]:
    """Every file under *root* by relative POSIX path (test-only)."""
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _assert_no_temp_leftovers(root: Path) -> None:
    """No publication or cache temporary files may survive a build (test-only)."""
    leftovers = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and (path.name.startswith(".maatlog-") or path.name.startswith("tmp") or path.name.endswith(".tmp"))
    ]
    assert leftovers == []


def _merge_recorder(sink: list[frozenset[str]]) -> Callable[[Any, Any, Any, Any], None]:
    """Return an ``env-merge-info`` callback appending merged docnames to *sink* (test-only)."""

    def on_merge(app: Any, env: Any, docnames: Any, other: Any) -> None:
        del app, env, other
        sink.append(frozenset(docnames))

    return on_merge


def _generation_pids(pid_log: Path) -> set[int]:
    """Generation PIDs recorded on disk, empty when nothing was logged (test-only)."""
    if not pid_log.is_file():
        return set()
    return {int(line) for line in pid_log.read_text(encoding="utf-8").split()}


def _driver_env() -> dict[str, str]:
    """Environment for the OS-process drivers: the venv plus the tests tree."""
    env = dict(os.environ)
    pythonpath = _TESTS_DIR
    if env.get("PYTHONPATH"):
        pythonpath += os.pathsep + env["PYTHONPATH"]
    env["PYTHONPATH"] = pythonpath
    return env


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
@pytest.mark.parametrize("parallel", [2, 4])
def test_parallel_preserves_manifest_and_public_bytes(
    make_sphinx: SphinxFactory, builder: str, parallel: int, tmp_path: Path
) -> None:
    parent_pid = os.getpid()
    files = parallel_files()
    post_pagenames = {
        Path(name).with_suffix("").as_posix() for name in files if name.startswith("posts/") and name.endswith(".rst")
    }
    assert len(post_pagenames) >= 9

    generator = RecordingGenerator()
    pid_log = tmp_path / f"generate-{builder}-{parallel}.log"
    generator.pid_log = pid_log
    merges: list[frozenset[str]] = []

    app = make_sphinx(files=files, config={"maatlog_responsive_images": True}, builder=builder, parallel=parallel)
    register_variant_generator_factory(app, lambda: generator)
    app.connect("env-merge-info", _merge_recorder(merges))
    app.connect("html-page-context", _record_writer_pid)
    app.build()
    assert app.builder.parallel_ok
    assert set(generator.pids) == {parent_pid}
    assert _generation_pids(pid_log) == {parent_pid}
    assert merges, "expected env-merge-info calls as read-parallel evidence"
    writer_pids = _writer_pids(app)
    assert post_pagenames <= set(writer_pids)
    assert set(writer_pids.values()) - {parent_pid}, "expected worker PIDs beyond the parent"
    snapshot = dict(responsive_manifest(app.env))
    assert set(snapshot) == {"img/hero.png", "img/top.png"}
    bytes_before = _public_state(app)
    assert len(bytes_before) == 10

    serial_generator = RecordingGenerator()
    serial_pid_log = tmp_path / f"generate-{builder}-serial.log"
    serial_generator.pid_log = serial_pid_log
    serial_merges: list[frozenset[str]] = []

    serial_app = make_sphinx(files=files, config={"maatlog_responsive_images": True}, builder=builder)
    register_variant_generator_factory(serial_app, lambda: serial_generator)
    serial_app.connect("env-merge-info", _merge_recorder(serial_merges))
    serial_app.connect("html-page-context", _record_writer_pid)
    serial_app.build()
    assert not serial_app.builder.parallel_ok
    assert serial_merges == []
    assert set(_writer_pids(serial_app).values()) == {parent_pid}
    assert set(serial_generator.pids) == {parent_pid}
    assert _generation_pids(serial_pid_log) == {parent_pid}
    assert dict(responsive_manifest(serial_app.env)) == snapshot
    assert _public_state(serial_app) == bytes_before

    serial = reopen_build(app, generator, parallel=1)
    assert dict(responsive_manifest(serial.env)) == snapshot
    assert _public_state(app) == bytes_before
    assert _generation_pids(pid_log) == {parent_pid}


def test_two_processes_share_one_cache_root(tmp_path: Path) -> None:
    cache_root = tmp_path / "shared-cache"
    out_first = tmp_path / "out-first" / "_images" / "maatlog"
    out_second = tmp_path / "out-second" / "_images" / "maatlog"
    builder_name = "html"
    first = subprocess.Popen(
        [sys.executable, _DRIVER_PATH, str(cache_root), str(out_first), builder_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_driver_env(),
    )
    second = subprocess.Popen(
        [sys.executable, _DRIVER_PATH, str(cache_root), str(out_second), builder_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_driver_env(),
    )
    try:
        first_out, first_err = first.communicate(timeout=60)
        second_out, second_err = second.communicate(timeout=60)
    finally:
        for proc in (first, second):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
    assert first.returncode == 0, first_err
    assert second.returncode == 0, second_err
    assert "pid=" in first_out
    assert "pid=" in second_out
    assert "variants=10 files=10" in first_out
    assert "variants=10 files=10" in second_out
    assert (out_first / ".manifest.json").read_bytes() == (out_second / ".manifest.json").read_bytes()
    first_bytes = _output_bytes(out_first)
    assert first_bytes
    assert _output_bytes(out_second) == first_bytes
    _assert_no_temp_leftovers(cache_root)
    _assert_no_temp_leftovers(out_first)
    _assert_no_temp_leftovers(out_second)

    second_before = _output_bytes(out_second)
    cache_before = _tree_bytes(cache_root)
    commit_owned_variants(output_root=out_first, builder_name=builder_name, current={})
    assert _output_bytes(out_first) == {}
    assert _output_bytes(out_second) == second_before
    assert _tree_bytes(cache_root) == cache_before
