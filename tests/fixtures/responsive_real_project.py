"""Real-image sources and the all-consumer project layout (issue #217, task E).

Every payload is real encoded image bytes produced by Pillow inside the
fixture functions -- Pillow is imported only inside function bodies, so an
isolated Pillow-less environment can still consume prebuilt bytes. Nothing
here is a fake generator or a post-hoc candidate file: the tests that consume
these sources always drive a normal ``maatlog_responsive_images = True``
Sphinx build.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from functools import cache
from io import BytesIO
from re import compile as re_compile
from typing import TYPE_CHECKING, Final

from fixtures.responsive_image_fixtures import make_test_png

if TYPE_CHECKING:
    from PIL import Image


@dataclass(frozen=True)
class ImageCase:
    """One real image source plus what the pipeline is expected to produce.

    ``width``/``height`` are the displayed natural dimensions (EXIF orientation
    already applied); ``format`` is the Pillow format name every generated
    candidate must decode as. ``responsive=False`` marks sources a build must
    publish verbatim with no manifest entry; ``frames`` records the expected
    ``n_frames`` for animation fixtures.
    """

    payload: bytes
    width: int | None
    height: int | None
    format: str | None
    responsive: bool
    frames: int = 1


def photo_bytes() -> bytes:
    from PIL import Image

    payload = random.Random(217).randbytes(2400 * 1350 * 3)
    with Image.frombytes("RGB", (2400, 1350), payload) as image:
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=95, subsampling=0)
        return buffer.getvalue()


def _save(image: Image.Image, format_name: str, **options: object) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format=format_name, **options)  # pyright: ignore[reportUnknownArgumentType]
    image.close()
    return buffer.getvalue()


def _blocks(width: int, height: int) -> Image.Image:
    """Left-half red / right-half blue RGB image for lossy colour checks."""
    from PIL import Image

    image = Image.new("RGB", (width, height), (30, 30, 200))
    image.paste((200, 30, 30), (0, 0, width // 2, height))
    return image


def _rgba_png_bytes() -> bytes:
    """1600x900 RGBA: transparent red left half, opaque blue right half."""
    from PIL import Image

    image = Image.new("RGBA", (1600, 900), (30, 30, 200, 255))
    image.paste((200, 30, 30, 0), (0, 0, 800, 900))
    return _save(image, "PNG")


def _portrait_jpeg_bytes() -> bytes:
    """900x1600 portrait: red top half, blue bottom half."""
    from PIL import Image

    image = Image.new("RGB", (900, 1600), (30, 30, 200))
    image.paste((200, 30, 30), (0, 0, 900, 800))
    return _save(image, "JPEG")


def _orientation6_jpeg_bytes() -> bytes:
    """Stored 1200x800 (left red / right blue) tagged EXIF orientation 6.

    Displayed as 800x1200: the stored left half lands on top after the
    90-degree-clockwise transpose, so variants show red on top, blue below.
    """
    image = _blocks(1200, 800)
    exif = image.getexif()
    exif[274] = 6
    return _save(image, "JPEG", exif=exif)


def _icc_png_bytes() -> bytes:
    from maatlog._responsive_image_pixels import _srgb_profile_bytes

    return _save(_blocks(1600, 900), "PNG", icc_profile=_srgb_profile_bytes())


def _cmyk_jpeg_bytes() -> bytes:
    from PIL import Image

    image = Image.new("CMYK", (1600, 900), (128, 0, 128, 0))
    image.paste((0, 128, 128, 0), (0, 0, 800, 900))
    return _save(image, "JPEG")


def _palette_png_bytes() -> bytes:
    """Palette PNG whose index 0 is transparent via ``tRNS``."""
    from PIL import Image

    image = Image.new("P", (1600, 900))
    image.putpalette([255, 0, 0, 0, 255, 0, 0, 0, 255] + [0] * (768 - 9))
    image.paste(0, (0, 0, 800, 900))
    image.paste(1, (800, 0, 1600, 900))
    return _save(image, "PNG", transparency=bytes([0, 255]))


def _meta_jpeg_bytes() -> bytes:
    """JPEG carrying EXIF orientation/GPS plus comment and XMP payloads."""
    image = _blocks(1600, 900)
    exif = image.getexif()
    exif[274] = 1
    exif[271] = "Make"
    exif[34853] = {0: b"\x02\x03\x00\x00", 1: "N", 2: (35.0, 139.0)}
    return _save(image, "JPEG", exif=exif, comment=b"secret-comment", xmp=b"<x:xmp>data</x:xmp>")


def _meta_png_bytes() -> bytes:
    """PNG carrying EXIF plus tEXt and iTXt (XMP) chunks."""
    from PIL.PngImagePlugin import PngInfo

    image = _blocks(1600, 900)
    exif = image.getexif()
    exif[271] = "Make"
    info = PngInfo()
    info.add_text("Title", "secret-title")
    info.add_text("Description", "secret-desc")
    info.add_itxt("XML:com.adobe.xmp", "<x:xmp>data</x:xmp>")
    return _save(image, "PNG", exif=exif, pnginfo=info)


def _animated_bytes(format_name: str) -> bytes:
    """Two visibly different frames: 100ms each, looping forever."""
    from PIL import Image

    first = Image.new("RGB", (800, 450), (200, 30, 30))
    second = Image.new("RGB", (800, 450), (30, 30, 200))
    buffer = BytesIO()
    first.save(buffer, format=format_name, save_all=True, append_images=[second], duration=100, loop=0)
    first.close()
    second.close()
    return buffer.getvalue()


def _multipage_tiff_bytes() -> bytes:
    from PIL import Image

    first = Image.new("RGB", (800, 450), (200, 30, 30))
    second = Image.new("RGB", (800, 450), (30, 30, 200))
    buffer = BytesIO()
    first.save(buffer, format="TIFF", save_all=True, append_images=[second])
    first.close()
    second.close()
    return buffer.getvalue()


def _truncated(payload: bytes) -> bytes:
    """Keep the format signature, drop the second half -- decode must fail."""
    return payload[: len(payload) // 2]


def _broken_animated_webp_bytes() -> bytes:
    """An animated WebP whose header area is zeroed -- decode must fail."""
    data = bytearray(_animated_bytes("WEBP"))
    assert len(data) > 160
    data[32:160] = b"\x00" * 128
    return bytes(data)


_SVG_SOURCE: Final = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60">'
    '<rect width="120" height="60" fill="#336699"/></svg>'
)


@cache
def _cached_cases() -> dict[str, ImageCase]:
    still_jpeg = _save(_blocks(1600, 900), "JPEG")
    still_png = _save(_blocks(1600, 900), "PNG")
    still_webp = _save(_blocks(1600, 900), "WEBP")
    small_png = _save(_blocks(800, 450), "PNG")
    return {
        "photo.jpg": ImageCase(photo_bytes(), 2400, 1350, "JPEG", True),
        "rgba.png": ImageCase(_rgba_png_bytes(), 1600, 900, "PNG", True),
        "still.webp": ImageCase(still_webp, 1600, 900, "WEBP", True),
        "small.jpg": ImageCase(_save(_blocks(240, 135), "JPEG"), 240, 135, "JPEG", True),
        "portrait.jpg": ImageCase(_portrait_jpeg_bytes(), 900, 1600, "JPEG", True),
        # Stored 1200x800, EXIF orientation 6 -> displayed 800x1200.
        "orientation-6.jpg": ImageCase(_orientation6_jpeg_bytes(), 800, 1200, "JPEG", True),
        "icc.png": ImageCase(_icc_png_bytes(), 1600, 900, "PNG", True),
        "cmyk.jpg": ImageCase(_cmyk_jpeg_bytes(), 1600, 900, "JPEG", True),
        "palette.png": ImageCase(_palette_png_bytes(), 1600, 900, "PNG", True),
        "meta.jpg": ImageCase(_meta_jpeg_bytes(), 1600, 900, "JPEG", True),
        "meta.png": ImageCase(_meta_png_bytes(), 1600, 900, "PNG", True),
        # JPEG bytes behind a .png name: content, not extension, decides.
        "mislabeled.png": ImageCase(still_jpeg, 1600, 900, "JPEG", True),
        "my photo.png": ImageCase(small_png, 800, 450, "PNG", True),
        "a,b.png": ImageCase(small_png, 800, 450, "PNG", True),
        "日本語.png": ImageCase(small_png, 800, 450, "PNG", True),
        "100%.png": ImageCase(small_png, 800, 450, "PNG", True),
        "dup.png": ImageCase(small_png, 800, 450, "PNG", True),
        "vector.svg": ImageCase(_SVG_SOURCE.encode("utf-8"), None, None, None, False),
        "still.gif": ImageCase(_save(_blocks(800, 450), "GIF"), 800, 450, "GIF", False),
        "animated.gif": ImageCase(_animated_bytes("GIF"), 800, 450, "GIF", False, frames=2),
        "animated.png": ImageCase(_animated_bytes("PNG"), 800, 450, "PNG", False, frames=2),
        "animated.webp": ImageCase(_animated_bytes("WEBP"), 800, 450, "WEBP", False, frames=2),
        "multipage.tiff": ImageCase(_multipage_tiff_bytes(), 800, 450, "TIFF", False, frames=2),
        "truncated.jpg": ImageCase(_truncated(still_jpeg), None, None, "JPEG", False),
        "truncated.png": ImageCase(_truncated(still_png), None, None, "PNG", False),
        "truncated.webp": ImageCase(_truncated(still_webp), None, None, "WEBP", False),
        "broken-anim.webp": ImageCase(_broken_animated_webp_bytes(), None, None, "WEBP", False),
    }


def image_cases() -> dict[str, ImageCase]:
    """Return every spec section-5 image case keyed by its source file name."""
    return dict(_cached_cases())


def project_config(*, enabled: bool = True, page_size: int = 20) -> dict[str, object]:
    """Config the real project builds with -- normal opt-in, nothing injected."""
    return {
        "maatlog_responsive_images": enabled,
        "maatlog_responsive_image_widths": (480, 768, 960, 1200, 1600),
        "maatlog_home_docname": "index",
        "maatlog_archive_docname": "nested/blog",
        "maatlog_page_size": page_size,
        "maatlog_featured_posts": ["p01", "p02", "p03"],
        "maatlog_authors": {"alice": "Alice"},
        "maatlog_author_profiles": {"alice": {"role": "Editor", "featured_posts": ["p01"]}},
        "maatlog_default_author": "alice",
        "maatlog_generate_feeds": False,
        "html_baseurl": "https://example.test/docs/",
    }


_URI_SAFE_NAME: Final = re_compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def _myst_post(slug: str, day: int, image_uri: str, *, top: bool, body_image: bool) -> str:
    front = [
        "---",
        "maatlog-post: true",
        f"maatlog-slug: {slug}",
        f"maatlog-published-at: 2026-07-{day:02d}T09:00:00Z",
        f"maatlog-image: {image_uri}",
    ]
    if top:
        front.append(f"maatlog-top-image: {image_uri}")
    if day <= 6:
        front += [
            "maatlog-authors: [alice]",
            "maatlog-tags: [integration]",
            "maatlog-categories: [photos]",
        ]
    body = [f"![hero]({image_uri})", ""] if body_image else []
    return "\n".join([*front, "---", "", f"# {slug.upper()}", "", *body, "Body.", ""])


def _rst_post(slug: str, day: int, *, image: str | None = None, top: str | None = None) -> str:
    title = slug.replace("-", " ").title()
    lines = [
        ":maatlog-post: true",
        f":maatlog-slug: {slug}",
        f":maatlog-published-at: 2026-07-{day:02d}T09:00:00Z",
    ]
    if image is not None:
        lines.append(f":maatlog-image: {image}")
    lines += ["", title, "=" * len(title), ""]
    if top is not None:
        lines += [f".. maatlog:maattop:: {top}", "   :alt: Top image", ""]
    lines += ["Body.", ""]
    return "\n".join(lines)


def project_files(*, source_name: str = "photo.jpg", post_count: int = 15) -> dict[str, str | bytes]:
    """Every document the consumer tests need, plus the real source images.

    All posts point at the same managed source ``images/<source_name>`` so one
    manifest entry serves every consumer: p01 carries the representative image
    and the maattop hero, ``top-only``/``representative-only``/``no-image``
    cover the remaining post shapes, ``general.rst`` holds plain body images,
    and ``listing.rst`` embeds a normal ``post-list``.
    """
    if post_count < 3:
        raise ValueError("post_count must cover the featured posts p01..p03")
    cases = image_cases()
    if source_name not in cases:
        raise KeyError(f"unknown image case {source_name!r}")
    case = cases[source_name]
    image_uri = f"images/{source_name}"
    files: dict[str, str | bytes] = {
        image_uri: case.payload,
        "images/body.png": make_test_png(400, 225),
    }
    # A MyST link destination with spaces would need <...> quoting; the p01 body
    # image stays URI-safe while the managed URI itself always goes through the
    # front matter, which handles every source name.
    safe_uri = _URI_SAFE_NAME.fullmatch(source_name) is not None
    for index in range(1, post_count + 1):
        slug = f"p{index:02d}"
        files[f"posts/{slug}.md"] = _myst_post(
            slug,
            index,
            f"../{image_uri}",
            top=index == 1,
            body_image=index == 1 and case.responsive and safe_uri,
        )
    # The ``maatlog:maattop`` directive argument cannot carry a space; a spaced
    # source name still reaches the managed path through ``maatlog-image``.
    spaced_name = " " in source_name
    files["top-only.rst"] = _rst_post(
        "top-only",
        16,
        top=None if spaced_name else image_uri,
        image=image_uri if spaced_name else None,
    )
    files["representative-only.rst"] = _rst_post("representative-only", 17, image=image_uri)
    files["no-image.rst"] = _rst_post("no-image", 18)
    files["listing.rst"] = "Listing\n=======\n\n.. maatlog:post-list::\n"
    files["general.rst"] = (
        "General\n=======\n\nA normal page with body images.\n\n"
        ".. image:: images/body.png\n   :alt: Local body image\n\n"
        ".. image:: https://example.test/remote.png\n   :alt: Remote image\n"
    )
    docnames = sorted(name.rsplit(".", 1)[0] for name in files if name.endswith((".rst", ".md")))
    entries = "\n".join(f"   {docname}" for docname in docnames)
    files["index.rst"] = (
        f"Home\n====\n\nA short introduction to the test blog.\n\n.. toctree::\n   :hidden:\n\n{entries}\n"
    )
    return files
