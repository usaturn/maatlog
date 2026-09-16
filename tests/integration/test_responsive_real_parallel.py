"""Serial/parallel and cross-process shared-cache builds with the real backend.

Two real CLI builds (``python -m sphinx -j1`` vs ``-j2``) must publish
byte-identical candidates, with every generation PID equal to the main build
process -- writer workers never generate. The shared-cache test builds two
independent projects in two spawned OS processes that share only one
dedicated cache directory (separate srcdir/outdir/doctreedir each), meeting at
a barrier right before each process's first real encode on the cold cache.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import time
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
from fixtures.responsive_real_build import create_project, shared_cache_build_worker
from fixtures.responsive_real_inspect import published_variants
from PIL import Image

if TYPE_CHECKING:
    from collections.abc import Iterator
    from multiprocessing.managers import SyncManager

_TESTS_DIR: Final = str(Path(__file__).resolve().parents[1])

#: Marker prefixes the real pipeline uses for in-flight publication files.
_TMP_MARKERS: Final = (".maatlog-", ".tmp")


def _instrument(srcdir: Path, *, generation_log: Path, writer_dir: Path, main_pid: Path) -> None:
    """Append a ``setup`` hook to conf.py wrapping the real generator methods.

    The wrapper records the process id of every ``probe``/``generate`` call to
    *generation_log* and delegates to the real Pillow implementation
    unchanged. A per-page ``html-page-context`` hook writes the writer PID to
    one file per page, so parallel writers never share a log file.
    """
    snippet = (
        "\n"
        "import os\n"
        "from pathlib import Path\n"
        f"_GENERATION_LOG = {str(generation_log)!r}\n"
        f"_WRITER_DIR = {str(writer_dir)!r}\n"
        f"_MAIN_PID_FILE = {str(main_pid)!r}\n"
        "\n"
        "def setup(app):\n"
        "    Path(_MAIN_PID_FILE).write_text(f'{os.getpid()}\\n', encoding='utf-8')\n"
        "    from maatlog.responsive_images import PillowImageVariantGenerator\n"
        "    real_generate = PillowImageVariantGenerator.generate\n"
        "    real_probe = PillowImageVariantGenerator.probe\n"
        "\n"
        "    def generate(self, request):\n"
        "        with open(_GENERATION_LOG, 'a', encoding='utf-8') as stream:\n"
        "            stream.write(f'{os.getpid()}\\n')\n"
        "        return real_generate(self, request)\n"
        "\n"
        "    def probe(self, source_path, *, image_format):\n"
        "        with open(_GENERATION_LOG, 'a', encoding='utf-8') as stream:\n"
        "            stream.write(f'{os.getpid()}\\n')\n"
        "        return real_probe(self, source_path, image_format=image_format)\n"
        "\n"
        "    PillowImageVariantGenerator.generate = generate\n"
        "    PillowImageVariantGenerator.probe = probe\n"
        "\n"
        "    def record_writer(app, pagename, templatename, context, doctree):\n"
        "        target = Path(_WRITER_DIR) / f'{pagename}.txt'\n"
        "        target.parent.mkdir(parents=True, exist_ok=True)\n"
        "        target.write_text(f'{os.getpid()}\\n', encoding='utf-8')\n"
        "\n"
        "    app.connect('html-page-context', record_writer)\n"
    )
    conf = srcdir / "conf.py"
    conf.write_text(conf.read_text(encoding="utf-8") + snippet, encoding="utf-8")


def _has_tmp_leftovers(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and any(marker in path.name for marker in _TMP_MARKERS)
    ]


def _decode_all(published: dict[str, bytes]) -> dict[str, int]:
    widths: dict[str, int] = {}
    for name, data in published.items():
        with Image.open(BytesIO(data)) as image:
            image.load()
            widths[name] = image.width
            assert image.format == "JPEG", name
            assert not image.getexif(), name
    return widths


@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_real_parallel_build_matches_serial(tmp_path: Path, builder: str) -> None:
    serial = create_project(tmp_path / f"serial-{builder}", builder=builder)
    parallel = create_project(tmp_path / f"parallel-{builder}", builder=builder)
    generation_log = parallel.root / "generation.log"
    writer_dir = parallel.root / "writer-pids"
    main_pid_file = parallel.root / "main.pid"
    _instrument(
        parallel.srcdir,
        generation_log=generation_log,
        writer_dir=writer_dir,
        main_pid=main_pid_file,
    )

    first = serial.build(parallel=1)
    assert first.returncode == 0, first.stderr + first.stdout
    second = parallel.build(parallel=2)
    assert second.returncode == 0, second.stderr + second.stdout

    serial_published = published_variants(serial.outdir)
    parallel_published = published_variants(parallel.outdir)
    assert len(serial_published) == 6
    assert {name: sha256(data).hexdigest() for name, data in serial_published.items()} == {
        name: sha256(data).hexdigest() for name, data in parallel_published.items()
    }
    assert _decode_all(serial_published) == _decode_all(parallel_published)
    for project in (serial, parallel):
        assert _has_tmp_leftovers(project.outdir) == []
        assert _has_tmp_leftovers(project.doctreedir) == []

    main_pid = int(main_pid_file.read_text(encoding="utf-8").strip())
    generation_pids = {int(line) for line in generation_log.read_text(encoding="utf-8").split()}
    assert generation_pids == {main_pid}, "generation happened outside the main build process"
    writer_pids = {int(path.read_text(encoding="utf-8").strip()) for path in sorted(writer_dir.rglob("*.txt"))}
    assert writer_pids - {main_pid}, "expected at least one real writer worker process"


@pytest.fixture
def spawn_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expose ``tests/`` to spawn children, which start without pytest's sys.path."""
    existing = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv("PYTHONPATH", _TESTS_DIR + (os.pathsep + existing if existing else ""))


@pytest.fixture
def mp_manager() -> Iterator[SyncManager]:
    """Serve picklable Barrier proxies from the spawn context."""
    manager = multiprocessing.get_context("spawn").Manager()
    try:
        yield manager
    finally:
        manager.shutdown()


def _assert_cache_integrity(cache_root: Path) -> dict[str, str]:
    """Every cached image pairs with a sidecar recording its bytes and size."""
    images = sorted(
        path for path in cache_root.rglob("*") if path.is_file() and path.suffix in {".jpg", ".png", ".webp"}
    )
    assert images
    digests: dict[str, str] = {}
    for image_path in images:
        sidecar = image_path.with_name(image_path.name + ".json")
        assert sidecar.is_file(), f"missing sidecar for {image_path.name}"
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        payload = image_path.read_bytes()
        assert record["sha256"] == sha256(payload).hexdigest()
        assert record["byte_size"] == len(payload)
        with Image.open(image_path) as image:
            image.load()
            assert (image.width, image.height) == (record["width"], record["height"])
        digests[image_path.name] = record["sha256"]
    return digests


@pytest.mark.usefixtures("spawn_pythonpath")
def test_two_processes_share_one_dedicated_cache(tmp_path: Path, mp_manager: SyncManager) -> None:
    """Two spawned builds share only the cache dir; everything else is separate."""
    shared_cache = tmp_path / "shared-cache"
    projects = [
        create_project(tmp_path / "first", source_name="photo.jpg"),
        create_project(tmp_path / "second", source_name="photo.jpg"),
    ]
    assert projects[0].srcdir != projects[1].srcdir
    assert projects[0].doctreedir != projects[1].doctreedir
    barrier = mp_manager.Barrier(2)
    result_paths = [tmp_path / "first-result.json", tmp_path / "second-result.json"]
    ctx = multiprocessing.get_context("spawn")
    workers = [
        ctx.Process(
            target=shared_cache_build_worker,
            args=(
                str(project.srcdir),
                str(project.outdir),
                str(project.doctreedir),
                "html",
                str(shared_cache),
                str(result_path),
                barrier,
            ),
        )
        for project, result_path in zip(projects, result_paths, strict=True)
    ]
    deadline = time.monotonic() + 120
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=max(0.0, deadline - time.monotonic()))
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=10)
                if worker.is_alive():
                    worker.kill()
                    worker.join(timeout=10)
    for worker in workers:
        assert worker.exitcode == 0, f"worker pid={worker.pid} exited with {worker.exitcode}"
    results = [json.loads(path.read_text(encoding="utf-8")) for path in result_paths]
    for result in results:
        assert result["built"] is True
        assert result["rendezvoused"] is True, "worker never reached the encode barrier"
        assert result["warnings"] == ""

    _assert_cache_integrity(shared_cache)
    assert _has_tmp_leftovers(shared_cache) == []
    first_published = published_variants(projects[0].outdir)
    second_published = published_variants(projects[1].outdir)
    assert len(first_published) == 6
    assert first_published == second_published
    assert _decode_all(first_published)
    for project in projects:
        assert _has_tmp_leftovers(project.outdir) == []
        assert _has_tmp_leftovers(project.doctreedir) == []
