"""Pillow module guard for the responsive-image unit suites (issue #214).

``tests/integration/test_responsive_image_contracts.py::test_disabled_build_never_imports_pillow``
pops every ``PIL``/``PIL.*`` entry from ``sys.modules`` and never restores it. Unit
suites bind Pillow objects at collection time (``from PIL import ...``) while
production imports Pillow lazily at call time, so after an eviction the two sides
hold distinct module objects and monkeypatched codec probes silently miss. This
helper snapshots the collection-time objects and re-registers the identical
objects before each test in every importing module.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest

# Collection-time bindings used across the responsive-image unit suites. Ensured
# present (rather than merely snapshotted) so the guard holds no matter which
# consumer module is collected first.
for _module_name in ("PIL", "PIL.Image", "PIL.ImageCms", "PIL.features"):
    importlib.import_module(_module_name)

_PIL_MODULES: dict[str, ModuleType] = {
    name: module for name, module in sys.modules.items() if name == "PIL" or name.startswith("PIL.")
}


def restore_pillow_modules() -> None:
    """Re-register evicted PIL modules with their collection-time objects.

    Only fills gaps (``setdefault``): entries still present — including ones a
    test deliberately replaced — are never clobbered.
    """
    for name, module in _PIL_MODULES.items():
        sys.modules.setdefault(name, module)


@pytest.fixture(autouse=True)
def restored_pillow_modules() -> None:
    """Run :func:`restore_pillow_modules` before each test in importing modules."""
    restore_pillow_modules()
