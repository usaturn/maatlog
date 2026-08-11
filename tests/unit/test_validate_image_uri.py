"""Unit coverage for pure representative image URI validation."""

from pathlib import Path

import pytest

from maatlog.images import IMAGE_INVALID, IMAGE_MISSING, ImageValidationError, validate_image_uri


def test_validate_image_uri_accepts_existing_regular_file(tmp_path: Path) -> None:
    source = tmp_path / "post.rst"
    source.write_text("placeholder", encoding="utf-8")
    image = tmp_path / "images" / "cover.png"
    image.parent.mkdir()
    image.write_bytes(b"png")

    resolved = validate_image_uri("images/cover.png", source=source, srcdir=tmp_path)

    assert resolved == image.resolve()


@pytest.mark.parametrize(
    ("uri", "code"),
    [
        ("missing.png", IMAGE_MISSING),
        ("https://example.com/cover.png", IMAGE_INVALID),
        ("https://[", IMAGE_INVALID),
        ("bad%00.png", IMAGE_INVALID),
        ("images/cover.png?size=large", IMAGE_INVALID),
        ("images/cover.png#hero", IMAGE_INVALID),
        ("/absolute.png", IMAGE_INVALID),
        ("../../outside.png", IMAGE_INVALID),
        ("images", IMAGE_MISSING),
        ("", IMAGE_INVALID),
    ],
)
def test_validate_image_uri_rejects_invalid_inputs(tmp_path: Path, uri: str, code: str) -> None:
    source = tmp_path / "post.rst"
    source.write_text("placeholder", encoding="utf-8")
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "placeholder.txt").write_text("placeholder", encoding="utf-8")

    with pytest.raises(ImageValidationError) as error:
        validate_image_uri(uri, source=source, srcdir=tmp_path)

    assert error.value.code == code


def test_validate_image_uri_rejects_escape_symlink(tmp_path: Path) -> None:
    source = tmp_path / "src" / "post.rst"
    source.parent.mkdir()
    source.write_text("placeholder", encoding="utf-8")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"png")
    (tmp_path / "src" / "cover.png").symlink_to(outside)

    with pytest.raises(ImageValidationError) as error:
        validate_image_uri("cover.png", source=source, srcdir=tmp_path / "src")

    assert error.value.code == IMAGE_INVALID


@pytest.mark.parametrize("symlink_component", ["file", "directory"])
def test_validate_image_uri_rejects_internal_symlinks(tmp_path: Path, symlink_component: str) -> None:
    source = tmp_path / "post.rst"
    source.write_text("placeholder", encoding="utf-8")
    if symlink_component == "file":
        target = tmp_path / "actual.png"
        target.write_bytes(b"png")
        (tmp_path / "cover.png").symlink_to(target)
        uri = "cover.png"
    else:
        target = tmp_path / "actual-images"
        target.mkdir()
        (target / "cover.png").write_bytes(b"png")
        (tmp_path / "images").symlink_to(target, target_is_directory=True)
        uri = "images/cover.png"

    with pytest.raises(ImageValidationError) as error:
        validate_image_uri(uri, source=source, srcdir=tmp_path)

    assert error.value.code == IMAGE_INVALID
