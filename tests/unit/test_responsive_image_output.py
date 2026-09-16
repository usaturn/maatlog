"""Unit tests for responsive variant publication and ownership."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fixtures.responsive_build_fixtures import PROBE, RecordingGenerator
from fixtures.responsive_image_fixtures import make_test_png

from maatlog.errors import MaatlogBuildError
from maatlog.image_contracts import GeneratedVariant, VariantRequest, build_source_identity
from maatlog.responsive_image_output import (
    IMAGE_INVALID_VARIANT,
    IMAGE_OUTPUT_UNWRITABLE,
    commit_owned_variants,
    publish_variants,
)


def _make_variant(tmp_path: Path, cache: Path, width: int = 480) -> GeneratedVariant:
    source = tmp_path / "hero.png"
    if not source.is_file():
        source.write_bytes(make_test_png(1600, 900))
    generator = RecordingGenerator()
    request = VariantRequest(source, build_source_identity(source, srcdir=tmp_path), PROBE, width, cache)
    return generator.generate(request)


def test_cache_hit_republishes_missing_output(tmp_path: Path) -> None:
    source = tmp_path / "hero.png"
    source.write_bytes(make_test_png(1600, 900))
    generator = RecordingGenerator()
    cache = tmp_path / "cache"
    request = VariantRequest(source, build_source_identity(source, srcdir=tmp_path), PROBE, 480, cache)
    variant = generator.generate(request)
    output = tmp_path / "out" / "_images" / "maatlog"
    first = publish_variants((variant,), cache_root=cache, output_root=output)
    destination = output / variant.public_basename
    assert destination.read_bytes() == variant.cache_path.read_bytes()
    destination.unlink()
    hit = generator.generate(request)
    second = publish_variants((hit,), cache_root=cache, output_root=output)
    assert first == second
    assert destination.is_file()
    assert generator.encode_count == 1
    assert destination.stat().st_ino != variant.cache_path.stat().st_ino


def test_cleanup_removes_only_previous_owned_bytes(tmp_path: Path) -> None:
    root = tmp_path / "maatlog"
    root.mkdir()
    old = root / "old.png"
    keep = root / "unknown.png"
    old.write_bytes(b"old")
    keep.write_bytes(b"foreign")
    commit_owned_variants(
        output_root=root, builder_name="html", current={"old.png": hashlib.sha256(b"old").hexdigest()}
    )
    commit_owned_variants(output_root=root, builder_name="html", current={})
    assert not old.exists()
    assert keep.read_bytes() == b"foreign"


def test_publish_empty_creates_nothing(tmp_path: Path) -> None:
    output = tmp_path / "out" / "maatlog"
    assert publish_variants((), cache_root=tmp_path / "cache", output_root=output) == {}
    assert not output.exists()


def test_commit_without_manifest_and_empty_current_creates_nothing(tmp_path: Path) -> None:
    output = tmp_path / "out" / "maatlog"
    commit_owned_variants(output_root=output, builder_name="html", current={})
    assert not output.exists()
    assert not (tmp_path / "out").exists()


def test_publish_rejects_unsafe_basename(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    variant = _make_variant(tmp_path, cache)
    for bad in ("../outside.png", "/absolute.png", "a/b.png", ".", "..", "bad name!.png"):
        with pytest.raises(MaatlogBuildError) as error:
            publish_variants(
                (replace(variant, public_basename=bad),),
                cache_root=cache,
                output_root=tmp_path / "out",
            )
        assert error.value.diagnostics[0].code == IMAGE_INVALID_VARIANT


def test_publish_rejects_cache_escape(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    variant = _make_variant(tmp_path, cache)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"evil")
    with pytest.raises(MaatlogBuildError) as error:
        publish_variants(
            (replace(variant, cache_path=outside, byte_size=outside.stat().st_size),),
            cache_root=cache,
            output_root=tmp_path / "out",
        )
    assert error.value.diagnostics[0].code == IMAGE_INVALID_VARIANT
    assert not (tmp_path / "out").exists()


def test_publish_rejects_symlink_cache(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    variant = _make_variant(tmp_path, cache)
    link = tmp_path / "link.bin"
    link.symlink_to(variant.cache_path)
    with pytest.raises(MaatlogBuildError) as error:
        publish_variants(
            (replace(variant, cache_path=link, byte_size=variant.byte_size),),
            cache_root=cache,
            output_root=tmp_path / "out",
        )
    assert error.value.diagnostics[0].code == IMAGE_INVALID_VARIANT


def test_publish_rejects_byte_size_mismatch(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    variant = _make_variant(tmp_path, cache)
    with pytest.raises(MaatlogBuildError) as error:
        publish_variants(
            (replace(variant, byte_size=variant.byte_size + 1),),
            cache_root=cache,
            output_root=tmp_path / "out",
        )
    assert error.value.diagnostics[0].code == IMAGE_INVALID_VARIANT


def test_publish_rejects_basename_collision_with_different_bytes(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    first = _make_variant(tmp_path, cache, width=480)
    second = _make_variant(tmp_path, cache, width=768)
    clashing = replace(second, public_basename=first.public_basename)
    with pytest.raises(MaatlogBuildError) as error:
        publish_variants((first, clashing), cache_root=cache, output_root=tmp_path / "out")
    assert error.value.diagnostics[0].code == IMAGE_INVALID_VARIANT


def test_publish_rejects_symlink_output_root(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    variant = _make_variant(tmp_path, cache)
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(MaatlogBuildError) as error:
        publish_variants((variant,), cache_root=cache, output_root=link)
    assert error.value.diagnostics[0].code == IMAGE_INVALID_VARIANT


def test_publish_skips_identical_existing_file(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    variant = _make_variant(tmp_path, cache)
    output = tmp_path / "out"
    first = publish_variants((variant,), cache_root=cache, output_root=output)
    destination = output / variant.public_basename
    mtime = destination.stat().st_mtime_ns
    second = publish_variants((variant,), cache_root=cache, output_root=output)
    assert first == second
    assert destination.stat().st_mtime_ns == mtime


def test_cleanup_keeps_modified_owned_file(tmp_path: Path) -> None:
    root = tmp_path / "maatlog"
    root.mkdir()
    target = root / "old.png"
    target.write_bytes(b"old")
    commit_owned_variants(
        output_root=root, builder_name="html", current={"old.png": hashlib.sha256(b"old").hexdigest()}
    )
    target.write_bytes(b"tampered")
    commit_owned_variants(output_root=root, builder_name="html", current={})
    assert target.read_bytes() == b"tampered"


def test_cleanup_keeps_symlink_owned_file(tmp_path: Path) -> None:
    root = tmp_path / "maatlog"
    root.mkdir()
    real = root / "real.png"
    real.write_bytes(b"real")
    link = root / "old.png"
    link.symlink_to(real)
    commit_owned_variants(
        output_root=root, builder_name="html", current={"old.png": hashlib.sha256(b"real").hexdigest()}
    )
    commit_owned_variants(output_root=root, builder_name="html", current={})
    assert link.is_symlink()


def test_cleanup_ignores_escape_entries_without_deleting(tmp_path: Path) -> None:
    root = tmp_path / "maatlog"
    root.mkdir()
    victim = tmp_path / "victim.png"
    victim.write_bytes(b"victim")
    (root / ".manifest.json").write_text(
        json.dumps({"schema": 1, "builder": "html", "files": {"../victim.png": "0" * 64}}),
        encoding="utf-8",
    )
    commit_owned_variants(output_root=root, builder_name="html", current={})
    assert victim.read_bytes() == b"victim"


def test_cleanup_ignores_absolute_entries_without_deleting(tmp_path: Path) -> None:
    root = tmp_path / "maatlog"
    root.mkdir()
    (root / ".manifest.json").write_text(
        json.dumps({"schema": 1, "builder": "html", "files": {"/etc/passwd": "0" * 64}}),
        encoding="utf-8",
    )
    commit_owned_variants(output_root=root, builder_name="html", current={})
    assert (root / ".manifest.json").is_file()


@pytest.mark.parametrize(
    "payload",
    [
        {"schema": 2, "builder": "html", "files": {}},
        {"schema": 1, "builder": "html", "files": {"old.png": "not-a-digest"}},
        {"schema": 1, "builder": "html", "files": {"../evil.png": "0" * 64}},
        {"schema": 1, "builder": "html", "files": {}, "extra": True},
        {"builder": "html", "files": {}},
    ],
)
def test_cleanup_ignores_invalid_manifest_without_deleting(tmp_path: Path, payload: object) -> None:
    root = tmp_path / "maatlog"
    root.mkdir()
    old = root / "old.png"
    old.write_bytes(b"old")
    (root / ".manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    commit_owned_variants(output_root=root, builder_name="html", current={})
    assert old.is_file()


def test_cleanup_ignores_broken_json_without_deleting(tmp_path: Path) -> None:
    root = tmp_path / "maatlog"
    root.mkdir()
    old = root / "old.png"
    old.write_bytes(b"old")
    (root / ".manifest.json").write_bytes(b"{not json")
    commit_owned_variants(output_root=root, builder_name="html", current={})
    assert old.is_file()


def test_cleanup_keeps_foreign_builder_files(tmp_path: Path) -> None:
    root = tmp_path / "maatlog"
    root.mkdir()
    old = root / "old.png"
    old.write_bytes(b"old")
    digest = hashlib.sha256(b"old").hexdigest()
    (root / ".manifest.json").write_text(
        json.dumps({"schema": 1, "builder": "dirhtml", "files": {"old.png": digest}}),
        encoding="utf-8",
    )
    commit_owned_variants(output_root=root, builder_name="html", current={})
    assert old.is_file()


def test_outputs_are_isolated_per_outdir(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    variant = _make_variant(tmp_path, cache)
    first_root = tmp_path / "out1" / "maatlog"
    second_root = tmp_path / "out2" / "maatlog"
    first = publish_variants((variant,), cache_root=cache, output_root=first_root)
    second = publish_variants((variant,), cache_root=cache, output_root=second_root)
    assert first == second
    commit_owned_variants(output_root=first_root, builder_name="html", current=first)
    commit_owned_variants(output_root=second_root, builder_name="html", current=second)
    commit_owned_variants(output_root=first_root, builder_name="html", current={})
    assert not (first_root / variant.public_basename).exists()
    assert (second_root / variant.public_basename).is_file()


def test_cleanup_failure_keeps_old_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "maatlog"
    root.mkdir()
    old = root / "old.png"
    old.write_bytes(b"old")
    commit_owned_variants(
        output_root=root, builder_name="html", current={"old.png": hashlib.sha256(b"old").hexdigest()}
    )
    manifest_bytes = (root / ".manifest.json").read_bytes()
    original_unlink = Path.unlink

    def failing_unlink(self: Path, *args: Any, **kwargs: Any) -> None:
        if self == old:
            raise OSError("cannot delete")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    commit_owned_variants(output_root=root, builder_name="html", current={})
    assert old.is_file()
    assert (root / ".manifest.json").read_bytes() == manifest_bytes


def test_manifest_write_failure_is_build_error(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"blocker")
    with pytest.raises(MaatlogBuildError) as error:
        commit_owned_variants(output_root=blocker, builder_name="html", current={"a.png": "0" * 64})
    assert error.value.diagnostics[0].code == IMAGE_OUTPUT_UNWRITABLE


def test_commit_rejects_manifest_basename_as_owned_file(tmp_path: Path) -> None:
    root = tmp_path / "maatlog"
    with pytest.raises(MaatlogBuildError) as error:
        commit_owned_variants(output_root=root, builder_name="html", current={".manifest.json": "0" * 64})
    assert error.value.diagnostics[0].code == IMAGE_INVALID_VARIANT
    assert not root.exists()


def test_commit_writes_sorted_manifest(tmp_path: Path) -> None:
    root = tmp_path / "maatlog"
    cache = tmp_path / "cache"
    first = _make_variant(tmp_path, cache, width=480)
    published = publish_variants((first,), cache_root=cache, output_root=root)
    commit_owned_variants(output_root=root, builder_name="html", current=published)
    data = json.loads((root / ".manifest.json").read_text(encoding="utf-8"))
    assert data == {"schema": 1, "builder": "html", "files": published}
    assert list(data["files"]) == sorted(data["files"])


def test_commit_refuses_symlink_output_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(MaatlogBuildError) as error:
        commit_owned_variants(output_root=link, builder_name="html", current={"a.png": "0" * 64})
    assert error.value.diagnostics[0].code == IMAGE_INVALID_VARIANT
    assert not (real / ".manifest.json").exists()


def test_commit_refuses_symlink_parent_directory(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(MaatlogBuildError) as error:
        commit_owned_variants(output_root=link / "maatlog", builder_name="html", current={"a.png": "0" * 64})
    assert error.value.diagnostics[0].code == IMAGE_INVALID_VARIANT
    assert not (real / "maatlog").exists()


def test_cleanup_does_not_delete_through_symlink_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    old = real / "old.png"
    old.write_bytes(b"old")
    digest = hashlib.sha256(b"old").hexdigest()
    manifest = real / ".manifest.json"
    manifest.write_text(json.dumps({"schema": 1, "builder": "html", "files": {"old.png": digest}}), encoding="utf-8")
    manifest_bytes = manifest.read_bytes()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(MaatlogBuildError) as error:
        commit_owned_variants(output_root=link, builder_name="html", current={})
    assert error.value.diagnostics[0].code == IMAGE_INVALID_VARIANT
    assert old.read_bytes() == b"old"
    assert manifest.read_bytes() == manifest_bytes


def test_commit_with_symlinked_grandparent_and_nothing_to_do_creates_nothing(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    keep = real / "keep.png"
    keep.write_bytes(b"keep")
    link = tmp_path / "outlink"
    link.symlink_to(real, target_is_directory=True)
    output_root = link / "_images" / "maatlog"
    commit_owned_variants(output_root=output_root, builder_name="html", current={})
    assert keep.read_bytes() == b"keep"
    assert sorted(child.name for child in real.iterdir()) == ["keep.png"]
    assert not output_root.exists()


def test_publish_rejects_symlink_grandparent_directory(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    variant = _make_variant(tmp_path, cache)
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "outlink"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(MaatlogBuildError) as error:
        publish_variants((variant,), cache_root=cache, output_root=link / "_images" / "maatlog")
    assert error.value.diagnostics[0].code == IMAGE_INVALID_VARIANT
    assert list(real.iterdir()) == []
