"""Concurrent cache recovery and reproducible-output tests (issue #214, task 6).

Every test builds its sources with Pillow in ``tmp_path`` only. Processes use
the ``spawn`` start method; because ``spawn`` cannot pickle raw ``Barrier`` /
``Event`` objects, coordination primitives come from a spawn-context manager
(``ctx.Manager().Barrier/Event``) and travel to the module-level worker
entries in :mod:`fixtures.responsive_images.worker` as picklable proxies.

No test guesses races with ``time.sleep``: the gated writer leaves a partial
temp, meets three racers at a ``Barrier(4)`` (proving four processes really
raced on one cold candidate), and every worker waits for a ``release`` event
before encoding, so nothing is published before the parent observes. The only
sleep in this file is the mandated >1s real wall-clock shift for the ICC
timestamp tripwire, which tests time dependence, not race timing.

Warm-hit / cold-miss accounting: concurrent warm hits must encode zero times;
concurrent cold misses may encode more than once, so no test ever asserts an
exactly-once total. The primary observer test for the mutation check is
``test_parallel_cold_publish_never_exposes_partial_target``.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import struct
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from io import BytesIO
from multiprocessing.managers import SyncManager
from pathlib import Path
from typing import Any, Literal

import pytest
from fixtures.responsive_images import worker
from fixtures.responsive_images.helpers import make_request
from fixtures.responsive_images.pillow_guard import restored_pillow_modules as restored_pillow_modules
from fixtures.responsive_images.worker import generate_once
from PIL import Image, ImageCms

from maatlog._responsive_image_pixels import _srgb_profile_bytes
from maatlog.image_contracts import (
    IMAGE_ENCODE_FAILED,
    ImageProcessingError,
    compute_variant_key,
    variant_cache_relpath,
)
from maatlog.responsive_images import PillowImageVariantGenerator

#: Intentional target corruption for the recovery race; the observer tells
#: these exact bytes apart from any new partial publication.
_INTENTIONAL_CORRUPTION = b"broken-cache-intentional"


@pytest.fixture(autouse=True)
def spawn_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expose ``tests/`` to spawn children, which start without pytest's ``sys.path``."""
    tests_dir = str(Path(__file__).resolve().parents[1])
    existing = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv("PYTHONPATH", tests_dir + (os.pathsep + existing if existing else ""))


@pytest.fixture
def mp_manager() -> Iterator[SyncManager]:
    """Serve picklable Barrier/Event proxies from the spawn context."""
    manager = multiprocessing.get_context("spawn").Manager()
    try:
        yield manager
    finally:
        manager.shutdown()


def _payload(source: Path, srcdir: Path, cache_root: Path, width: int) -> tuple[str, str, str, int]:
    return (str(source), str(srcdir), str(cache_root), width)


def _save_hero(tmp_path: Path) -> Path:
    """Save the shared 64x36 RGBA source every race test starts from."""
    src = tmp_path / "hero.png"
    Image.new("RGBA", (64, 36), (20, 100, 50, 130)).save(src)
    return src


def _new_palette() -> Image.Image:
    """Build the shared 48x30 opaque palette source (exercises generated-ICC output)."""
    paletted = Image.new("P", (48, 30))
    paletted.putpalette([channel % 256 for channel in range(768)])
    return paletted


def _cache_paths(source: Path, *, srcdir: Path, cache_root: Path, width: int) -> tuple[Path, Path]:
    """Return the (image target, sidecar) paths the contracts predict for a request."""
    request = make_request(source, srcdir=srcdir, cache_root=cache_root, width=width)
    generator = PillowImageVariantGenerator()
    key = compute_variant_key(
        identity=request.identity,
        width=width,
        image_format=request.probe.image_format,
        encoder=generator.encoder,
        backend=generator.describe_backend(),
    )
    target = cache_root / variant_cache_relpath(key, request.probe.image_format)
    return (target, target.with_name(target.name + ".json"))


def _assert_complete(target: Path, *, sha: str, width: int, height: int) -> None:
    """Assert *target* holds exactly the expected bytes and decodes at the expected size."""
    assert hashlib.sha256(target.read_bytes()).hexdigest() == sha
    with Image.open(target) as image:
        image.load()
        assert image.size == (width, height)


def _run_gated_race(
    payload: tuple[str, str, str, int],
    mp_manager: SyncManager,
    *,
    observe: Callable[[], None],
) -> list[tuple[str, str, int, int]]:
    """Run one gated writer plus three gated racers over *payload*.

    Calls ``observe()`` in the pre-publication window (a partial temp is on
    disk, the barrier has not released anyone, ``release`` is unset), then
    releases the workers and returns their results. The barrier proves all
    four processes raced on the same cold candidate.
    """
    context = multiprocessing.get_context("spawn")
    barrier = mp_manager.Barrier(4)
    temp_ready = mp_manager.Event()
    release = mp_manager.Event()
    with ProcessPoolExecutor(max_workers=4, mp_context=context) as executor:
        futures = [executor.submit(worker.generate_gated, (payload, barrier, temp_ready, release, True))]
        futures.extend(
            executor.submit(worker.generate_gated, (payload, barrier, None, release, False)) for _ in range(3)
        )
        assert temp_ready.wait(timeout=30), "gated writer never left its partial temp"
        try:
            observe()
        finally:
            release.set()
        return [future.result(timeout=30) for future in futures]


def test_parallel_matches_serial(tmp_path: Path) -> None:
    src = tmp_path / "hero.png"
    Image.new("RGBA", (101, 57), (20, 100, 50, 130)).save(src)
    serial = generate_once((str(src), str(tmp_path), str(tmp_path / "serial"), 47))
    payload = (str(src), str(tmp_path), str(tmp_path / "parallel"), 47)
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=4, mp_context=context) as executor:
        outputs = list(executor.map(generate_once, [payload] * 8, timeout=30))
    assert outputs == [serial] * 8
    assert not list((tmp_path / "parallel").rglob("*.tmp"))


def test_parallel_cold_publish_never_exposes_partial_target(tmp_path: Path, mp_manager: SyncManager) -> None:
    src = _save_hero(tmp_path)
    width = 24
    cache_root = tmp_path / "parallel"
    payload = _payload(src, tmp_path, cache_root, width)
    target, sidecar = _cache_paths(src, srcdir=tmp_path, cache_root=cache_root, width=width)

    def observe() -> None:
        assert not target.exists()
        assert not sidecar.exists()
        # The writer's temp holds the marker; any racer temp that already
        # exists (mkstemp creates it empty) must still be empty: no temp
        # ever carries image bytes before release.
        partials = {partial.read_bytes() for partial in cache_root.rglob("*.tmp")}
        assert worker.PARTIAL_TEMP_MARKER in partials
        assert partials <= {worker.PARTIAL_TEMP_MARKER, b""}

    outputs = _run_gated_race(payload, mp_manager, observe=observe)
    # The serial oracle is computed after the race on an independent root: a
    # direct-write mutation trips the observer above before this is reached.
    expected = generate_once(_payload(src, tmp_path, tmp_path / "serial", width))
    assert outputs == [expected] * 4
    assert not list(cache_root.rglob("*.tmp"))
    _assert_complete(target, sha=expected[1], width=expected[2], height=expected[3])


def test_parallel_rewrite_keeps_old_complete_target(tmp_path: Path, mp_manager: SyncManager) -> None:
    src = _save_hero(tmp_path)
    width = 24
    expected = generate_once(_payload(src, tmp_path, tmp_path / "serial", width))
    cache_root = tmp_path / "parallel"
    payload = _payload(src, tmp_path, cache_root, width)
    assert generate_once(payload) == expected
    target, sidecar = _cache_paths(src, srcdir=tmp_path, cache_root=cache_root, width=width)
    old_bytes = target.read_bytes()
    sidecar.unlink()  # force a miss while the old complete image stays in place

    def observe() -> None:
        assert target.read_bytes() == old_bytes
        with Image.open(target) as image:
            image.load()
            assert image.size == (expected[2], expected[3])
        partials = {partial.read_bytes() for partial in cache_root.rglob("*.tmp")}
        assert worker.PARTIAL_TEMP_MARKER in partials
        assert partials <= {worker.PARTIAL_TEMP_MARKER, b""}

    assert _run_gated_race(payload, mp_manager, observe=observe) == [expected] * 4
    assert target.read_bytes() == old_bytes
    assert not list(cache_root.rglob("*.tmp"))


def test_killed_writer_recovers_complete_pair(tmp_path: Path, mp_manager: SyncManager) -> None:
    src = _save_hero(tmp_path)
    width = 24
    cache_root = tmp_path / "cache"
    payload = _payload(src, tmp_path, cache_root, width)
    expected = generate_once(_payload(src, tmp_path, tmp_path / "serial", width))
    serial_target, _ = _cache_paths(src, srcdir=tmp_path, cache_root=tmp_path / "serial", width=width)
    target, sidecar = _cache_paths(src, srcdir=tmp_path, cache_root=cache_root, width=width)
    image_replaced = mp_manager.Event()
    proceed = mp_manager.Event()  # never set: the writer dies waiting on it
    context = multiprocessing.get_context("spawn")
    proc = context.Process(target=worker.generate_replace_gated, args=((payload, image_replaced, proceed),))
    proc.start()
    try:
        assert image_replaced.wait(timeout=30), "writer never published its image"
        assert target.read_bytes() == serial_target.read_bytes()
        assert not sidecar.exists()
        residue_before = sorted(item.name for item in cache_root.rglob("*.tmp"))
        assert len(residue_before) == 1  # the writer's unpublished sidecar temp
        proc.terminate()
        proc.join(timeout=30)
    finally:
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=30)
    assert proc.exitcode is not None and proc.exitcode != 0
    assert generate_once(payload) == expected
    _assert_complete(target, sha=expected[1], width=expected[2], height=expected[3])
    assert json.loads(sidecar.read_bytes())["sha256"] == expected[1]
    assert sorted(item.name for item in cache_root.rglob("*.tmp")) == residue_before


def test_concurrent_recovery_from_corrupt_cache(tmp_path: Path, mp_manager: SyncManager) -> None:
    src = _save_hero(tmp_path)
    width = 24
    expected = generate_once(_payload(src, tmp_path, tmp_path / "serial", width))
    cache_root = tmp_path / "parallel"
    payload = _payload(src, tmp_path, cache_root, width)
    assert generate_once(payload) == expected
    target, sidecar = _cache_paths(src, srcdir=tmp_path, cache_root=cache_root, width=width)
    target.write_bytes(_INTENTIONAL_CORRUPTION)  # sidecar stays valid: a clean sha mismatch

    def observe() -> None:
        # The initial corruption sits untouched: no new partial publication happened.
        assert target.read_bytes() == _INTENTIONAL_CORRUPTION

    assert _run_gated_race(payload, mp_manager, observe=observe) == [expected] * 4
    _assert_complete(target, sha=expected[1], width=expected[2], height=expected[3])
    assert json.loads(sidecar.read_bytes())["sha256"] == expected[1]
    assert not list(cache_root.rglob("*.tmp"))


@pytest.mark.parametrize("kind", ["jpeg", "png", "webp", "palette"])
def test_parallel_reproducible_across_roots_and_processes(tmp_path: Path, kind: str) -> None:
    filenames = {"jpeg": "photo.jpg", "png": "hero.png", "webp": "picture.webp", "palette": "badge.png"}
    filename = filenames[kind]
    for root_name in ("root-a", "root-b"):
        directory = tmp_path / root_name / "sub"
        directory.mkdir(parents=True)
        path = directory / filename
        if kind == "jpeg":
            Image.new("RGB", (48, 30), (200, 40, 30)).save(path, format="JPEG")
        elif kind == "png":
            Image.new("RGBA", (48, 30), (20, 100, 50, 130)).save(path, format="PNG")
        elif kind == "webp":
            Image.new("RGBA", (48, 30), (20, 100, 50, 130)).save(path, format="WEBP")
        else:
            _new_palette().save(path, format="PNG")
    width = 24
    request_a = make_request(
        tmp_path / "root-a" / "sub" / filename,
        srcdir=tmp_path / "root-a",
        cache_root=tmp_path / "cache-a",
        width=width,
    )
    request_b = make_request(
        tmp_path / "root-b" / "sub" / filename,
        srcdir=tmp_path / "root-b",
        cache_root=tmp_path / "cache-b",
        width=width,
    )
    assert request_a.identity.source_relpath == request_b.identity.source_relpath == f"sub/{filename}"
    assert request_a.identity.content_hash == request_b.identity.content_hash
    serial = generate_once(_payload(request_a.source_path, tmp_path / "root-a", tmp_path / "cache-a", width))
    payload_b = _payload(request_b.source_path, tmp_path / "root-b", tmp_path / "cache-b", width)
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=4, mp_context=context) as executor:
        outputs = list(executor.map(generate_once, [payload_b] * 4, timeout=30))
    assert outputs == [serial] * 4
    target_a, _ = _cache_paths(
        request_a.source_path, srcdir=tmp_path / "root-a", cache_root=tmp_path / "cache-a", width=width
    )
    target_b, _ = _cache_paths(
        request_b.source_path, srcdir=tmp_path / "root-b", cache_root=tmp_path / "cache-b", width=width
    )
    assert target_a.parent.name == target_b.parent.name
    assert target_a.name == target_b.name
    assert target_a.read_bytes() == target_b.read_bytes()
    if kind == "palette":
        with Image.open(target_b) as image:
            image.load()
            assert image.info.get("icc_profile") == _srgb_profile_bytes()


def test_icc_creation_timestamp_canonicalized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # getattr keeps the untyped C-extension member as Any: binding
    # ImageCms.createProfile directly would leak Unknown into every caller.
    real_create_profile = getattr(ImageCms, "createProfile")  # noqa: B009 - Any, not Unknown
    stamps = [struct.pack(">6H", 2024, 5, 6, 7, 8, 9), struct.pack(">6H", 2026, 9, 14, 10, 11, 12)]
    made: list[bytes] = []

    def fake_create_profile(color_space: Literal["LAB", "XYZ", "sRGB"]) -> Any:
        # Return file-like bytes: every caller wraps this in ImageCmsProfile,
        # and later calls from the canonicalizer itself just cycle the stamps.
        raw = bytearray(ImageCms.ImageCmsProfile(real_create_profile(color_space)).tobytes())
        raw[24:36] = stamps[len(made) % len(stamps)]
        made.append(bytes(raw))
        return BytesIO(made[-1])

    monkeypatch.setattr(ImageCms, "createProfile", fake_create_profile)
    icc_first = bytes(ImageCms.ImageCmsProfile(fake_create_profile("sRGB")).tobytes())
    icc_second = bytes(ImageCms.ImageCmsProfile(fake_create_profile("sRGB")).tobytes())
    assert icc_first != icc_second  # the raw creation timestamps genuinely differ

    def save_palette(path: Path, icc: bytes) -> None:
        _new_palette().save(path, format="PNG", icc_profile=icc)

    src_a = tmp_path / "left.png"
    src_b = tmp_path / "right.png"
    save_palette(src_a, icc_first)
    save_palette(src_b, icc_second)
    request_a = make_request(src_a, srcdir=tmp_path, cache_root=tmp_path / "cache-a", width=24)
    request_b = make_request(src_b, srcdir=tmp_path, cache_root=tmp_path / "cache-b", width=24)
    assert request_a.identity.content_hash != request_b.identity.content_hash
    generator = PillowImageVariantGenerator()
    variant_a = generator.generate(request_a)
    variant_b = generator.generate(request_b)
    assert (variant_a.width, variant_a.height) == (variant_b.width, variant_b.height)
    assert variant_a.cache_path.read_bytes() == variant_b.cache_path.read_bytes()
    for variant in (variant_a, variant_b):
        with Image.open(variant.cache_path) as image:
            image.load()
            assert image.info.get("icc_profile") == _srgb_profile_bytes()


def test_wall_clock_shift_keeps_palette_output_identical(tmp_path: Path) -> None:
    # The 1.2s real-time shift below is the mandated wall-clock tripwire: it
    # catches encoder output that leaks wall time. It never times a race.
    src = tmp_path / "badge.png"
    _new_palette().save(src, format="PNG")
    width = 24
    serial = generate_once(_payload(src, tmp_path, tmp_path / "cache-a", width))
    delayed_payload = (_payload(src, tmp_path, tmp_path / "cache-b", width), 1.2)
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=context) as executor:
        (delayed,) = list(executor.map(worker.generate_after_delay, [delayed_payload], timeout=30))
    assert delayed == serial


def test_failure_preserves_foreign_temps_and_healthy_target(
    tmp_path: Path, mp_manager: SyncManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = tmp_path / "cache"
    src_a = tmp_path / "steady.png"
    Image.new("RGBA", (17, 9), (10, 40, 90, 120)).save(src_a)
    payload_a = _payload(src_a, tmp_path, cache_root, 7)
    generate_once(payload_a)  # seeds the healthy pair; raises on failure
    target_a, sidecar_a = _cache_paths(src_a, srcdir=tmp_path, cache_root=cache_root, width=7)
    old_target_a = target_a.read_bytes()
    old_sidecar_a = sidecar_a.read_bytes()
    src_b = tmp_path / "fragile.png"
    Image.new("RGBA", (17, 9), (200, 30, 30, 255)).save(src_b)
    payload_b = _payload(src_b, tmp_path, cache_root, 7)
    target_b, _ = _cache_paths(src_b, srcdir=tmp_path, cache_root=cache_root, width=7)
    foreign_name = f".{target_b.name}.foreign-worker.tmp"
    sentinel = "foreign-worker-temp"
    ready = mp_manager.Event()
    discharge = mp_manager.Event()
    context = multiprocessing.get_context("spawn")
    holder = context.Process(
        target=worker.hold_temp_file, args=((str(cache_root), foreign_name, sentinel, ready, discharge),)
    )
    holder.start()
    try:
        assert ready.wait(timeout=30), "holder never created its temp"
        foreign = cache_root / foreign_name
        assert foreign.read_bytes() == sentinel.encode("utf-8")

        def failing_save(self: Any, fp: Any, format: Any = None, **params: Any) -> None:
            raise ValueError("simulated encoder failure")

        monkeypatch.setattr(Image.Image, "save", failing_save)
        request_b = make_request(src_b, srcdir=tmp_path, cache_root=cache_root, width=7)
        with pytest.raises(ImageProcessingError) as caught:
            PillowImageVariantGenerator().generate(request_b)
        assert caught.value.diagnostic.code == IMAGE_ENCODE_FAILED
        assert not target_b.exists()
        assert foreign.read_bytes() == sentinel.encode("utf-8")
        assert target_a.read_bytes() == old_target_a
        assert sidecar_a.read_bytes() == old_sidecar_a
        assert [item.name for item in cache_root.rglob("*.tmp")] == [foreign_name]
    finally:
        discharge.set()
        holder.join(timeout=30)
        if holder.is_alive():
            holder.terminate()
            holder.join(timeout=30)
    assert holder.exitcode == 0
    monkeypatch.undo()
    recovered = generate_once(payload_b)
    _assert_complete(target_b, sha=recovered[1], width=recovered[2], height=recovered[3])
    assert (cache_root / foreign_name).read_bytes() == sentinel.encode("utf-8")


def test_parallel_warm_hits_encode_zero_times(tmp_path: Path) -> None:
    src = _save_hero(tmp_path)
    cache_root = tmp_path / "cache"
    payload = _payload(src, tmp_path, cache_root, 24)
    serial = generate_once(payload)  # warms the cache; every later generate must hit
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=4, mp_context=context) as executor:
        results = list(executor.map(worker.generate_counting, [payload] * 4, timeout=30))
    assert [result[:4] for result in results] == [serial] * 4
    assert sum(result[4] for result in results) == 0
    assert not list(cache_root.rglob("*.tmp"))


def test_parallel_cold_miss_may_encode_more_than_once(tmp_path: Path) -> None:
    src = _save_hero(tmp_path)
    expected = generate_once(_payload(src, tmp_path, tmp_path / "serial", 24))
    payload = _payload(src, tmp_path, tmp_path / "parallel", 24)
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=4, mp_context=context) as executor:
        results = list(executor.map(worker.generate_counting, [payload] * 4, timeout=30))
    assert [result[:4] for result in results] == [expected] * 4
    # Deliberately no upper bound: duplicate encodes on a cold race are correct,
    # so asserting exactly-once would be wrong. Someone must have encoded, though.
    assert sum(result[4] for result in results) >= 1
    assert not list((tmp_path / "parallel").rglob("*.tmp"))
