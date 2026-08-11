"""Safe validation of MaatLog representative image URIs."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

IMAGE_INVALID = "maatlog.image.invalid"
IMAGE_MISSING = "maatlog.image.missing"

IMAGE_INVALID_EXPECTED = "a regular source-relative file without query, fragment, or symbolic links"
IMAGE_MISSING_EXPECTED = "an existing regular file"


class ImageValidationError(Exception):
    """Raised when a representative image URI fails validation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def validate_image_uri(uri: str, *, source: Path, srcdir: Path) -> Path:
    """Validate a source-relative local image URI and return the resolved file path.

    The URI must be non-empty and source-relative: no scheme, authority, query,
    or fragment. The resolved target must be an existing regular file under
    *srcdir* with no symbolic-link components on the path under the source root.

    Only call ``env.note_dependency`` and ``env.images.add_file`` after this
    function succeeds so invalid URIs never enter the Sphinx image pipeline.
    """
    try:
        parsed = urlsplit(uri)
    except ValueError as error:
        raise ImageValidationError(IMAGE_INVALID, "Invalid representative image URI") from error
    try:
        path = Path(unquote(parsed.path))
    except (OSError, ValueError) as error:
        raise ImageValidationError(IMAGE_INVALID, "Invalid representative image URI") from error
    if not uri or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or path.is_absolute():
        raise ImageValidationError(IMAGE_INVALID, "Invalid representative image URI")

    try:
        source_root = srcdir.resolve()
        source_parent = source.parent.resolve()
        lexical_candidate = Path(os.path.abspath(source_parent / path))
        if not lexical_candidate.is_relative_to(source_root):
            raise ImageValidationError(IMAGE_INVALID, "Representative image escapes the source directory")
        if _has_symlink_component(source_root, lexical_candidate):
            raise ImageValidationError(IMAGE_INVALID, "Representative image path contains a symbolic link")
        candidate = lexical_candidate.resolve()
        if not candidate.is_relative_to(source_root):
            raise ImageValidationError(IMAGE_INVALID, "Representative image escapes the source directory")
        is_regular_file = candidate.is_file()
    except ImageValidationError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise ImageValidationError(IMAGE_INVALID, "Invalid representative image path") from error

    if not is_regular_file:
        raise ImageValidationError(IMAGE_MISSING, "Representative image does not exist")
    return candidate


def _has_symlink_component(source_root: Path, candidate: Path) -> bool:
    current = source_root
    for component in candidate.relative_to(source_root).parts:
        current /= component
        if current.is_symlink():
            return True
    return False
