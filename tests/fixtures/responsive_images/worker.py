"""Spawn-safe worker entries for parallel responsive-image cache tests.

Every entry is module-level so it pickles by reference, and every argument
travels as plain data (paths as ``str``, widths as ``int``, coordination as
manager ``Barrier``/``Event`` proxies): no Pillow image or open handle is
ever pickled between processes. Observation hooks (``save``/``replace``
wrappers) are installed only inside the worker process; the production API
takes no test-only parameters.
"""

from __future__ import annotations

import os
from typing import Any, Final, Protocol


class WorkerBarrier(Protocol):
    """Structural type for the manager ``Barrier`` proxy shared with a worker."""

    def wait(self, timeout: float | None = None) -> int: ...


class WorkerEvent(Protocol):
    """Structural type for the manager ``Event`` proxies shared with a worker."""

    def set(self) -> None: ...
    def wait(self, timeout: float | None = None) -> bool: ...


#: Seconds every barrier/event rendezvous inside a worker waits before the
#: worker fails loudly instead of hanging the suite.
RENDEZVOUS_TIMEOUT: Final = 30.0

#: Marker bytes a gated writer leaves in its own temp file so the parent can
#: prove the cache target is still absent (or still the old complete image)
#: while a publication is in flight. Never a valid image.
PARTIAL_TEMP_MARKER: Final = b"partial-temp-marker-not-an-image"


def generate_once(payload: tuple[str, str, str, int]) -> tuple[str, str, int, int]:
    import hashlib
    from pathlib import Path

    from fixtures.responsive_images.helpers import make_request

    from maatlog.responsive_images import PillowImageVariantGenerator

    source, srcdir, cache, width = payload
    request = make_request(Path(source), srcdir=Path(srcdir), cache_root=Path(cache), width=width)
    result = PillowImageVariantGenerator().generate(request)
    return (
        result.public_basename,
        hashlib.sha256(result.cache_path.read_bytes()).hexdigest(),
        result.width,
        result.height,
    )


def generate_counting(payload: tuple[str, str, str, int]) -> tuple[str, str, int, int, int]:
    """Run :func:`generate_once` and append the Pillow save count as plain data.

    A warm cache hit never encodes, so the count is 0; a cold miss encodes
    once per worker that misses.
    """
    from PIL import Image

    original_save = Image.Image.save
    calls = 0

    def counted_save(self: Any, fp: Any, format: Any = None, **params: Any) -> None:
        nonlocal calls
        calls += 1
        original_save(self, fp, format=format, **params)

    Image.Image.save = counted_save
    try:
        basename, digest, width, height = generate_once(payload)
    finally:
        Image.Image.save = original_save
    return (basename, digest, width, height, calls)


def generate_gated(
    args: tuple[tuple[str, str, str, int], WorkerBarrier, WorkerEvent | None, WorkerEvent, bool],
) -> tuple[str, str, int, int]:
    """Encode behind a barrier so the parent can observe a mid-publication cache.

    When *is_writer* is true, the worker first leaves
    :data:`PARTIAL_TEMP_MARKER` in its own temp file and signals *temp_ready*.
    Every worker then meets at *barrier* (proving that many processes raced
    on the same cold candidate) and waits for *release* before encoding.
    Nothing is published before the parent sets *release*, so the parent's
    observation window is deterministic and needs no sleeps.
    """
    from PIL import Image

    payload, barrier, temp_ready, release, is_writer = args
    original_save = Image.Image.save

    def gated_save(self: Any, fp: Any, format: Any = None, **params: Any) -> None:
        if is_writer:
            assert temp_ready is not None
            with open(fp, "wb") as stream:
                stream.write(PARTIAL_TEMP_MARKER)
                stream.flush()
                os.fsync(stream.fileno())
            temp_ready.set()
        barrier.wait(timeout=RENDEZVOUS_TIMEOUT)
        if not release.wait(timeout=RENDEZVOUS_TIMEOUT):
            raise TimeoutError("parallel test release was never set")
        original_save(self, fp, format=format, **params)

    Image.Image.save = gated_save
    try:
        return generate_once(payload)
    finally:
        Image.Image.save = original_save


def generate_replace_gated(
    args: tuple[tuple[str, str, str, int], WorkerEvent, WorkerEvent],
) -> tuple[str, str, int, int]:
    """Publish the image, signal, then block so the parent can kill this worker.

    The cache publishes image-first/sidecar-second, so the first ``os.replace``
    is the image publication. The worker signals *image_replaced* right after
    it and blocks on *proceed* (which the parent never sets): the parent kills
    the worker there, leaving a target with no sidecar for recovery tests.
    """

    payload, image_replaced, proceed = args
    original_replace = os.replace
    calls = 0

    def gated_replace(src: Any, dst: Any) -> None:
        nonlocal calls
        first = calls == 0
        calls += 1
        original_replace(src, dst)
        if first:
            image_replaced.set()
            proceed.wait(timeout=RENDEZVOUS_TIMEOUT)

    os.replace = gated_replace
    try:
        return generate_once(payload)
    finally:
        os.replace = original_replace


def hold_temp_file(args: tuple[str, str, str, WorkerEvent, WorkerEvent]) -> str:
    """Create a foreign temp in a cache dir and hold it open while the parent works.

    Returns the sentinel so the parent can confirm the file survived. The file
    is owned by this worker: production cleanup must never unlink it.
    """
    from pathlib import Path

    dirname, filename, sentinel, ready, release = args
    path = Path(dirname) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as stream:
        stream.write(sentinel.encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
        ready.set()
        release.wait(timeout=RENDEZVOUS_TIMEOUT)
    return sentinel


def generate_after_delay(args: tuple[tuple[str, str, str, int], float]) -> tuple[str, str, int, int]:
    """Sleep *delay* seconds and then run :func:`generate_once`.

    Only used to shift real wall-clock time across processes for the ICC
    timestamp regression tripwire; never for race timing.
    """
    import time

    payload, delay = args
    time.sleep(delay)
    return generate_once(payload)
