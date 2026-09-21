"""Browser regression for docutils image height hints (Issue #308)."""

from __future__ import annotations

from io import BytesIO

import pytest
from conftest import ProjectFactory
from PIL import Image
from playwright.sync_api import Browser


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_unitless_image_height_hint_is_respected(
    make_project: ProjectFactory, shared_browser: Browser, theme: str
) -> None:
    """The rendered height comes from ``:height: 100``, not the PNG's 225px height."""
    buffer = BytesIO()
    with Image.new("RGB", (400, 225), "#336699") as image:
        image.save(buffer, format="PNG")
    result = make_project(
        files={
            "about.rst": "About\n=====\n\n.. image:: body.png\n   :alt: probe\n   :height: 100\n",
            "body.png": buffer.getvalue(),
        },
        theme=theme,
    ).build()

    page = shared_browser.new_page(viewport={"width": 1280, "height": 900})
    try:
        page.goto(result.path("about.html").resolve().as_uri(), wait_until="load")
        image = page.locator('img[alt="probe"][height="100"]')
        assert image.count() == 1
        metrics = image.evaluate("(img) => ({height: getComputedStyle(img).height, naturalHeight: img.naturalHeight})")
        assert metrics == {"height": "100px", "naturalHeight": 225}
    finally:
        page.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_scaled_image_keeps_ratio_in_narrow_container(
    make_project: ProjectFactory, shared_browser: Browser, theme: str
) -> None:
    """A scaled body image shrinks without keeping its original height."""
    buffer = BytesIO()
    with Image.new("RGB", (400, 225), "#336699") as image:
        image.save(buffer, format="PNG")
    result = make_project(
        files={
            "about.rst": "About\n=====\n\n.. image:: body.png\n   :alt: scaled\n   :scale: 200%\n",
            "body.png": buffer.getvalue(),
        },
        theme=theme,
    ).build()

    page = shared_browser.new_page(viewport={"width": 390, "height": 900})
    try:
        page.goto(result.path("about.html").resolve().as_uri(), wait_until="load")
        image = page.locator('img[alt="scaled"][width="800"][height="450"]')
        assert image.count() == 1
        size = image.evaluate(
            "(img) => ({width: img.getBoundingClientRect().width, height: img.getBoundingClientRect().height})"
        )
        assert 0 < size["width"] < 800, size
        assert abs(size["height"] - size["width"] * 9 / 16) <= 1, size
    finally:
        page.close()
