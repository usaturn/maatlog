"""Real transfer bytes, reserved image space and LCP observation (issue #217, task G/T5).

Everything is measured against real ``python -m sphinx`` ON/OFF builds served
over plain HTTP -- no network routes or candidate substitution during byte
measurement. ``requestfinished`` -> ``request.sizes()`` records the encoded
bytes Chromium actually received; ``hold_images`` routes appear only in the
reserved-box tests, which measure layout, not bytes. Observation JSON is
written to ``tmp_path`` before every assert so failures keep their evidence.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, TypedDict, cast
from urllib.parse import urljoin

import pytest
from acceptance.built_sites import BuiltSite
from acceptance.real_built_sites import RealSites
from acceptance.responsive_image_site import (
    MAIN_WIDTHS,
    decode_all_images,
    write_observations,
)
from acceptance.responsive_real_browser import (
    PERFORMANCE_OBSERVER_JS,
    Color,
    ImageState,
    ImageTransfer,
    RiEvents,
    TransferSamples,
    candidate_urls,
    decode_in_viewport,
    decode_managed,
    decode_target,
    hold_images,
    hold_variant_images,
    image_states,
    measure_reserved_boxes,
    new_context,
    observer_types,
    page_path,
    record_transfers,
    ri_events,
    served_file,
    settle_transfers,
    two_frames,
    wait_layout_stable,
)
from fixtures.responsive_real_project import image_cases
from playwright.sync_api import Browser
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

_REPO_ROOT: Final = Path(__file__).resolve().parents[2]

#: The featured lead card's image on the home page -- same markup in ON/OFF.
_LEAD_IMAGE: Final = '[data-maatlog-card-variant="lead"] .maatlog-post-card-image'
_CURRENT_SRC_JS: Final = (
    "(selector) => { const e = document.querySelector(selector); return e ? e.currentSrc : null; }"
)

#: Card branches pair the first image-bearing card's image with its title.
_CARD_IMAGE: Final = "article.maatlog-post-card:has(.maatlog-post-card-image) .maatlog-post-card-image"
_CARD_TITLE: Final = "article.maatlog-post-card:has(.maatlog-post-card-image) .maatlog-post-card-title"

#: Test-side overrides that remove the CSS half of the reservation (the
#: width/height attributes are removed by _STRIP_RESERVATION_JS).
_CARD_STRIP: Final = ".maatlog-post-card-image{aspect-ratio:auto!important;height:auto!important}"
_TOP_STRIP: Final = (
    ".maatlog-post-top-image{aspect-ratio:auto!important}.maatlog-post-top-image-img{height:auto!important}"
)
_HERO_STRIP: Final = ".maatlog-post-hero-image{aspect-ratio:auto!important;height:auto!important}"

_STRIP_RESERVATION_JS: Final = """(spec) => {
  const image = document.querySelector(spec.image);
  if (!image) throw new Error('not found: ' + spec.image);
  image.removeAttribute('width');
  image.removeAttribute('height');
  const style = document.createElement('style');
  style.textContent = spec.css;
  document.head.appendChild(style);
  return {stripped: true};
}"""

#: Wait until every non-variant image (unmanaged fallbacks such as posts/p01's
#: body image) has finished -- held managed-variant images stay pending.
_NON_VARIANT_SETTLED_JS: Final = (
    "() => [...document.images].every((img) => img.complete ||"
    " (img.currentSrc || img.src || '').includes('/_images/maatlog/'))"
)


class _Branch(TypedDict):
    """One reserved-space branch: target image + downstream in-flow marker."""

    name: str
    docname: str
    image: str
    marker: str
    strip_css: str
    width: int
    hold_variants_only: bool


_BRANCHES: Final = [
    _Branch(
        name="home-lead",
        docname="index",
        image='[data-maatlog-card-variant="lead"] .maatlog-post-card-image',
        marker='[data-maatlog-card-variant="lead"] .maatlog-post-card-title',
        strip_css=_CARD_STRIP,
        width=1280,
        hold_variants_only=False,
    ),
    _Branch(
        name="home-secondary",
        docname="index",
        image='[data-maatlog-card-variant="secondary"] .maatlog-post-card-image',
        marker='[data-maatlog-card-variant="secondary"] .maatlog-post-card-title',
        strip_css=_CARD_STRIP,
        width=1280,
        hold_variants_only=False,
    ),
    # Latest cards lay the title out beside the image (horizontal row), so the
    # card's own title is not below the image box. The archive link follows the
    # whole latest grid and is a genuine downstream in-flow element.
    _Branch(
        name="home-latest",
        docname="index",
        image='[data-maatlog-card-variant="latest"] .maatlog-post-card-image',
        marker=".maatlog-home-archive-link",
        strip_css=_CARD_STRIP,
        width=1280,
        hold_variants_only=False,
    ),
    _Branch(
        name="archive-card",
        docname="nested/blog",
        image=_CARD_IMAGE,
        marker=_CARD_TITLE,
        strip_css=_CARD_STRIP,
        width=1280,
        hold_variants_only=False,
    ),
    _Branch(
        name="listing-card",
        docname="listing",
        image=_CARD_IMAGE,
        marker=_CARD_TITLE,
        strip_css=_CARD_STRIP,
        width=1280,
        hold_variants_only=False,
    ),
    _Branch(
        name="profile-card",
        docname="nested/blog/author/alice",
        image=_CARD_IMAGE,
        marker=_CARD_TITLE,
        strip_css=_CARD_STRIP,
        width=1280,
        hold_variants_only=False,
    ),
    # article.maatlog-post is a grid with areas header/body/nav/pagination.
    # .maatlog-post-top-image has no grid-area, so it is auto-placed in an
    # implicit row below them all -- the post meta sits *above* the image.
    # The page footer is the true downstream in-flow element.
    _Branch(
        name="post-top",
        docname="top-only",
        image=".maatlog-post-top-image-img",
        marker="div.footer",
        strip_css=_TOP_STRIP,
        width=1280,
        hold_variants_only=False,
    ),
    _Branch(
        name="post-top-mobile",
        docname="top-only",
        image=".maatlog-post-top-image-img",
        marker="div.footer",
        strip_css=_TOP_STRIP,
        width=390,
        hold_variants_only=False,
    ),
    _Branch(
        name="post-hero",
        docname="representative-only",
        image=".maatlog-post-hero-image",
        marker=".maatlog-post-body",
        strip_css=_HERO_STRIP,
        width=1280,
        hold_variants_only=False,
    ),
    # posts/p01 also carries the pinned *unmanaged* body <img> (no width/height,
    # no aspect-ratio -- it has no reservation by design). Holding only the
    # managed-variant requests lets that fallback load during the initial phase
    # so the release interval measures the managed reservation alone.
    _Branch(
        name="post-p01-top",
        docname="posts/p01",
        image=".maatlog-post-top-image-img",
        marker="div.footer",
        strip_css=_TOP_STRIP,
        width=1280,
        hold_variants_only=True,
    ),
    _Branch(
        name="post-p01-hero",
        docname="posts/p01",
        image=".maatlog-post-hero-image",
        marker=".maatlog-post-body",
        strip_css=_HERO_STRIP,
        width=1280,
        hold_variants_only=True,
    ),
]

_LCP_PAGES: Final = ("index", "posts/p01", "representative-only")

#: (builder, dpr, width) for the initial-phase transfer observation.
#:
#: The matrix only opens ``index``, and ``page_path`` returns ``index.html``
#: for both builders there, so crossing every row with dirhtml would repeat
#: the same request set. dirhtml keeps two evidence rows; its nested-page
#: URL resolution is asserted by test_all_images_scrolled_decode and
#: test_top_roles_and_priority.
_TRANSFER_CASES: Final[list[tuple[str, int, int]]] = [
    *[("html", dpr, width) for dpr in (1, 2) for width in MAIN_WIDTHS],
    ("dirhtml", 1, 390),
    ("dirhtml", 1, 1280),
]

#: Sources exercised for the visual/format cases: JPEG blocks, RGBA PNG
#: (transparency), WebP and an EXIF-orientation JPEG.
_FORMAT_SOURCES: Final = ("photo.jpg", "rgba.png", "still.webp", "orientation-6.jpg")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _repo_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "unknown"


def _source_sha256(source_name: str) -> str:
    """SHA-256 of the image fixture payload behind *source_name*."""
    return hashlib.sha256(image_cases()[source_name].payload).hexdigest()


def _env_meta(browser: Browser, source_name: str = "photo.jpg") -> dict[str, object]:
    """Environment facts attached to every observation record."""
    meta: dict[str, object] = {
        "repo_sha": _repo_sha(),
        "chromium": browser.version,
        "os": platform.platform(),
        "source_sha256": _source_sha256(source_name),
    }
    try:
        import PIL
        from PIL import features

        meta["pillow"] = PIL.__version__
        meta["pillow_codecs"] = {name: features.check(name) for name in ("jpg", "zlib", "webp")}
    except ImportError:
        meta["pillow"] = None
    return meta


def _image_file_info(path: Path) -> dict[str, object]:
    """Format/mode/pixel size of a served file, read back from the outdir."""
    from PIL import Image

    with Image.open(path) as image:
        return {
            "path": str(path),
            "bytes": path.stat().st_size,
            "format": image.format,
            "mode": image.mode,
            "width": image.width,
            "height": image.height,
        }


def _num(value: object) -> float:
    assert isinstance(value, (int, float))
    return float(value)


def _initial_phase(
    browser: Browser,
    site: BuiltSite,
    docname: str,
    *,
    enabled: bool,
    width: int,
    height: int = 900,
    dpr: float = 1,
    color: Color = "light",
) -> dict[str, object]:
    """Measure the initial (no-scroll) image-transfer phase of one page.

    The wait ends when every in-viewport image has decoded, no image request
    is in flight and the sample list has been stable for 200ms (15s ceiling).
    The page is never scrolled while waiting.
    """
    url = site.base_url + page_path(site.builder, docname)
    context = new_context(browser, width=width, height=height, dpr=dpr, color=color)
    try:
        page = context.new_page()
        try:
            samples = TransferSamples()
            record_transfers(page, samples)
            start_utc = _utc_now()
            page.goto(url, wait_until="load")
            decoded = decode_in_viewport(page)
            settled = settle_transfers(page, samples)
            end_utc = _utc_now()
            images = image_states(page)
            candidates = sorted({urljoin(url, raw) for raw in candidate_urls(page)})
            lead_src = page.evaluate(_CURRENT_SRC_JS, _LEAD_IMAGE)
        finally:
            page.close()
    finally:
        context.close()
    lead_samples = [s for s in samples if s["url"] == lead_src]
    eager = [i for i in images if i["loading"] == "eager"]
    return {
        "url": url,
        "docname": docname,
        "builder": site.builder,
        "enabled": enabled,
        "viewport": {"width": width, "height": height},
        "dpr": dpr,
        "color_scheme": color,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "settled": settled,
        "decoded_in_viewport": decoded,
        "samples": list(samples),
        "failures": list(samples.failures),
        "record_errors": list(samples.record_errors),
        "images": list(images),
        "candidates": candidates,
        "lead_current_src": lead_src,
        "lead_request_count": len(lead_samples),
        "lead_samples": lead_samples,
        "lead_body_bytes": sum(s["body_bytes"] for s in lead_samples),
        "viewport_image_srcs": [i["current_src"] for i in images if i["in_viewport"]],
        "first_eager_src": eager[0]["current_src"] if eager else None,
        "transfer_urls": sorted({s["url"] for s in samples}),
        "total_body_bytes": sum(s["body_bytes"] for s in samples),
        "total_header_bytes": sum(s["header_bytes"] for s in samples),
        "total_decoded_bytes": sum(s["decoded_body_bytes"] for s in samples),
    }


def _assert_clean_phase(phase: Mapping[str, object]) -> None:
    """Settled, no failed requests, no record errors, all 200 with bytes."""
    assert phase["settled"], phase["url"]
    assert phase["failures"] == [], phase["failures"]
    assert phase["record_errors"] == [], phase["record_errors"]
    assert phase["samples"], phase["url"]
    for sample in cast(list[ImageTransfer], phase["samples"]):
        assert sample["status"] == 200, sample["url"]
        assert sample["body_bytes"] > 0, sample["url"]
    for entry in cast(list[dict[str, object]], phase["decoded_in_viewport"]):
        assert "error" not in entry, entry


@pytest.mark.browser
def test_mobile_transfer_savings_gate(
    real_sites: RealSites,
    tmp_path: Path,
    shared_browser: Browser,
) -> None:
    """390x900/DPR1/light: ON must beat OFF on lead-image and total bytes.

    Only ``index`` is opened, where page_path returns index.html for both
    builders, so dirhtml would repeat the same request set. dirhtml byte
    integrity is asserted by test_all_images_scrolled_decode.
    """
    builder = "html"
    out = tmp_path / "mobile-transfers.json"
    phases: dict[bool, dict[str, object]] = {}
    lead_files: dict[bool, dict[str, object]] = {}

    def _persist() -> None:
        records: list[dict[str, object]] = [{"kind": "env", "builder": builder, **_env_meta(shared_browser)}]
        for enabled in (True, False):
            if enabled in phases:
                records.append({"kind": "initial-phase", **phases[enabled]})
            if enabled in lead_files:
                records.append({"kind": "lead-file", "enabled": enabled, **lead_files[enabled]})
        write_observations(out, records)

    for enabled in (True, False):
        site = real_sites.standard(builder, enabled=enabled)
        phases[enabled] = _initial_phase(shared_browser, site, "index", enabled=enabled, width=390, height=900, dpr=1)
        _persist()
        lead_src = phases[enabled]["lead_current_src"]
        assert isinstance(lead_src, str) and lead_src, phases[enabled]["url"]
        lead_files[enabled] = _image_file_info(served_file(site.outdir, lead_src))
        _persist()

    on, off = phases[True], phases[False]
    _assert_clean_phase(on)
    _assert_clean_phase(off)
    on_total = cast(int, on["total_body_bytes"])
    off_total = cast(int, off["total_body_bytes"])
    on_lead = cast(int, on["lead_body_bytes"])
    off_lead = cast(int, off["lead_body_bytes"])
    assert 0 < on_total < off_total, (on["samples"], off["samples"])
    assert 0 < on_lead < off_lead
    assert cast(str, on["lead_current_src"]) in cast(list[str], on["candidates"])
    # The lead's chosen resource is a real smaller variant, not the original.
    assert cast(int, lead_files[True]["width"]) < cast(int, lead_files[False]["width"])


@pytest.mark.browser
@pytest.mark.parametrize(
    ("builder", "dpr", "width"),
    _TRANSFER_CASES,
    ids=[f"{builder}-dpr{dpr}-{width}" for builder, dpr, width in _TRANSFER_CASES],
)
def test_transfer_observation_matrix(
    real_sites: RealSites,
    tmp_path: Path,
    shared_browser: Browser,
    builder: str,
    dpr: int,
    width: int,
) -> None:
    """Record initial-phase ON/OFF transfers at each (builder, dpr, width) case.

    Only the mobile gate enforces byte reduction; here the requirement is a
    valid chosen candidate plus clean decode -- the numbers are evidence.
    The color scheme is fixed to light; dark screenshots and decoded
    served-file facts live in test_visual_format_cases.
    """
    out = tmp_path / "transfers.json"
    records: list[dict[str, object]] = [
        {
            "kind": "env",
            "builder": builder,
            "color_scheme": "light",
            "dpr": dpr,
            "viewport": {"width": width, "height": 900},
            **_env_meta(shared_browser),
        }
    ]
    phases: dict[bool, dict[str, object]] = {}
    for enabled in (True, False):
        site = real_sites.standard(builder, enabled=enabled)
        phases[enabled] = _initial_phase(
            shared_browser,
            site,
            "index",
            enabled=enabled,
            width=width,
            height=900,
            dpr=dpr,
            color="light",
        )
        records.append({"kind": "initial-phase", **phases[enabled]})
        write_observations(out, records)
    on, off = phases[True], phases[False]
    records.append(
        {
            "kind": "comparison",
            "on_total_body_bytes": on["total_body_bytes"],
            "off_total_body_bytes": off["total_body_bytes"],
            "on_lead_body_bytes": on["lead_body_bytes"],
            "off_lead_body_bytes": off["lead_body_bytes"],
            "on_transfer_urls": on["transfer_urls"],
            "off_transfer_urls": off["transfer_urls"],
        }
    )
    write_observations(out, records)
    for phase in (on, off):
        _assert_clean_phase(phase)
    candidates = cast(list[str], on["candidates"])
    assert candidates, "ON build emitted no srcset candidates"
    for state in cast(list[ImageState], on["images"]):
        if state["marker"] == "w-v1":
            assert state["current_src"] in candidates, state["current_src"]
        if state["in_viewport"]:
            assert state["complete"] and state["natural_width"] > 0, state["current_src"]
    if dpr == 2:
        lead_src = on["lead_current_src"]
        assert isinstance(lead_src, str) and lead_src, on["url"]
        lead_state = next(state for state in cast(list[ImageState], on["images"]) if state["current_src"] == lead_src)
        # naturalWidth is normalized by the srcset density back to the slot
        # width, so the candidate's real pixels come from the served file.
        on_site = real_sites.standard(builder, enabled=True)
        lead_file = _image_file_info(served_file(on_site.outdir, lead_src))
        # At DPR 2 the chosen candidate must carry roughly twice the CSS
        # pixels of the slot; a single-candidate srcset fails this.
        assert cast(int, lead_file["width"]) >= lead_state["width"] * 1.5, (
            lead_file["width"],
            lead_state["width"],
        )


@pytest.mark.browser
@pytest.mark.parametrize("builder", ["html", "dirhtml"])
def test_all_images_scrolled_decode(
    real_sites: RealSites,
    tmp_path: Path,
    shared_browser: Browser,
    builder: str,
) -> None:
    """All-images series: scroll every managed image, decode, all 200.

    A separate series from the initial phase -- its numbers never mix into
    the initial-phase totals.
    """
    site = real_sites.standard(builder, enabled=True)
    out = tmp_path / "all-images.json"
    records: list[dict[str, object]] = [{"kind": "env", "builder": builder, **_env_meta(shared_browser)}]
    for docname in ("index", "nested/blog"):
        # Fresh context per page: a shared HTTP cache serves the second
        # page's repeated candidates from cache, and request.sizes()
        # reports a negative responseBodySize for cache hits.
        context = new_context(shared_browser, width=390, height=900)
        try:
            page = context.new_page()
            try:
                samples = TransferSamples()
                record_transfers(page, samples)
                url = site.base_url + page_path(site.builder, docname)
                page.goto(url, wait_until="load")
                decode_managed(page)
                settled = settle_transfers(page, samples)
                images = image_states(page)
                allowed = sorted(
                    {urljoin(url, raw) for raw in candidate_urls(page)}
                    | {urljoin(url, str(state["src"])) for state in images if state["src"]}
                )
                records.append(
                    {
                        "kind": "all-images",
                        "docname": docname,
                        "url": url,
                        "settled": settled,
                        "managed_count": sum(1 for i in images if i["marker"] == "w-v1"),
                        "samples": [dict(s) for s in samples],
                        "failures": [dict(f) for f in samples.failures],
                        "record_errors": list(samples.record_errors),
                        "allowed_urls": allowed,
                        "images": [dict(i) for i in images],
                    }
                )
                write_observations(out, records)
            finally:
                page.close()
        finally:
            context.close()
    for record in records[1:]:
        assert record["settled"], record["url"]
        assert cast(int, record["managed_count"]) > 0
        assert record["failures"] == [], record["failures"]
        assert record["record_errors"] == [], record["record_errors"]
        for sample in cast(list[ImageTransfer], record["samples"]):
            assert sample["status"] == 200, sample["url"]
            assert sample["body_bytes"] > 0, sample["url"]
            assert sample["url"] in cast(list[str], record["allowed_urls"]), sample["url"]


def _observe_reservation(
    browser: Browser,
    base: str,
    rel_path: str,
    branch: _Branch,
    *,
    strip: bool,
    persist: Callable[[Mapping[str, object]], None],
) -> dict[str, object]:
    """Hold the target image, measure box/marker before and after release.

    ``persist`` is invoked after the pre-release snapshot and again after the
    post-release measurements, so a failure anywhere still leaves evidence.
    """
    url = base + rel_path
    record: dict[str, object] = {
        "branch": branch["name"],
        "docname": branch["docname"],
        "strip": strip,
        "url": url,
        "viewport_width": branch["width"],
    }
    context = new_context(browser, width=branch["width"], height=900, dpr=1, color="light")
    try:
        page = context.new_page()
        try:
            page.add_init_script(PERFORMANCE_OBSERVER_JS)
            release = hold_variant_images(page) if branch["hold_variants_only"] else hold_images(page)
            page.goto(url, wait_until="domcontentloaded")
            record["observer_types"] = observer_types(page)
            record["layout_stable"] = wait_layout_stable(page)
            if branch["hold_variants_only"]:
                try:
                    page.wait_for_function(_NON_VARIANT_SETTLED_JS, timeout=10000)
                    record["fallback_settled"] = True
                except PlaywrightTimeoutError:
                    record["fallback_settled"] = False
            if strip:
                page.evaluate(_STRIP_RESERVATION_JS, {"image": branch["image"], "css": branch["strip_css"]})
            page.locator(branch["image"]).first.evaluate("image => image.scrollIntoView({block: 'center'})")
            record["before"] = measure_reserved_boxes(page, branch["image"])
            record["marker_before"] = measure_reserved_boxes(page, branch["marker"])
            persist(record)
            page.evaluate("() => { window.__ri.release = performance.now(); }")
            release()
            record["decoded"] = decode_target(page, branch["image"])
            two_frames(page)
            record["after"] = measure_reserved_boxes(page, branch["image"])
            record["marker_after"] = measure_reserved_boxes(page, branch["marker"])
            events = ri_events(page)
            release_ts = events["release"]
            record["release_ts"] = release_ts
            post_shifts = [
                shift
                for shift in events["shifts"]
                if release_ts is not None and shift["time"] >= release_ts and not shift["recentInput"]
            ]
            record["post_release_shifts"] = post_shifts
            record["post_release_shift_sum"] = sum(shift["value"] for shift in post_shifts)
            record["all_shifts"] = events["shifts"]
            record["lcp"] = events["lcp"]
            before = record["before"]
            after = record["after"]
            marker_before = record["marker_before"]
            marker_after = record["marker_after"]
            record["box_drift"] = {
                "x": abs(_num(after["x"]) - _num(before["x"])),
                "y": abs(_num(after["y"]) - _num(before["y"])),
                "width": abs(_num(after["width"]) - _num(before["width"])),
                "height": abs(_num(after["height"]) - _num(before["height"])),
            }
            record["marker_y_drift"] = abs(_num(marker_after["y"]) - _num(marker_before["y"]))
            persist(record)
        finally:
            page.close()
    finally:
        context.close()
    return record


@pytest.mark.browser
@pytest.mark.parametrize("strip", [False, True], ids=["reserved", "control"])
@pytest.mark.parametrize("branch", _BRANCHES, ids=[branch["name"] for branch in _BRANCHES])
def test_reserved_space_and_shift(
    real_sites: RealSites,
    tmp_path: Path,
    shared_browser: Browser,
    branch: _Branch,
    strip: bool,
) -> None:
    """Reserved box stays put on release; the stripped control must move >1px.

    Reservation is a layout property of the same CSS and markup in both
    builders; only the image URL depth differs, and that is asserted
    elsewhere. The sweep runs on html only.
    """
    builder = "html"
    site = real_sites.standard(builder, enabled=True)
    out = tmp_path / "reservation.json"

    def _persist(record: Mapping[str, object]) -> None:
        write_observations(out, [{"kind": "env", "builder": builder, **_env_meta(shared_browser)}, dict(record)])

    record = _observe_reservation(
        shared_browser,
        site.base_url,
        page_path(site.builder, branch["docname"]),
        branch,
        strip=strip,
        persist=_persist,
    )
    record["builder"] = builder
    _persist(record)
    assert record["layout_stable"], record["url"]
    if branch["hold_variants_only"]:
        assert record["fallback_settled"], record["url"]
    assert {"layout-shift", "largest-contentful-paint"} <= set(cast(list[str], record["observer_types"]))
    assert record["release_ts"] is not None
    before = cast(dict[str, object], record["before"])
    marker_before = cast(dict[str, object], record["marker_before"])
    drift = cast(dict[str, float], record["box_drift"])
    decoded = cast(dict[str, object], record["decoded"])
    assert decoded["complete"] is True and cast(int, decoded["naturalWidth"]) > 0
    if strip:
        # The unreserved image must visibly move its box or the marker.
        assert drift["height"] > 1 or cast(float, record["marker_y_drift"]) > 1, record
        assert cast(float, record["post_release_shift_sum"]) > 0, record["all_shifts"]
        return
    assert _num(before["width"]) > 0 and _num(before["height"]) > 0
    assert before["complete"] is False, "target image loaded before release"
    marker_y = _num(marker_before["y"])
    image_bottom = _num(before["y"]) + _num(before["height"])
    assert marker_y >= image_bottom - 1, "downstream marker is not below the image box"
    assert drift["x"] <= 1 and drift["y"] <= 1
    assert drift["width"] <= 1 and drift["height"] <= 1
    assert cast(float, record["marker_y_drift"]) <= 1
    assert cast(float, record["post_release_shift_sum"]) <= 0.001, record["post_release_shifts"]


@pytest.mark.browser
@pytest.mark.parametrize("height", [720, 900])
@pytest.mark.parametrize("width", [390, 1280, 3840])
@pytest.mark.parametrize("docname", _LCP_PAGES)
def test_lcp_observation(
    real_sites: RealSites,
    tmp_path: Path,
    shared_browser: Browser,
    docname: str,
    width: int,
    height: int,
) -> None:
    """No-scroll/no-input LCP observation; viewport images must not be lazy.

    A text LCP is recorded, not treated as an image-LCP failure. No claim is
    made about field CWV from this synthetic, input-free observation.
    """
    builder = "html"
    site = real_sites.standard(builder, enabled=True)
    out = tmp_path / "lcp.json"
    url = ""
    supported: list[str] = []
    lcp_seen = False
    images: list[ImageState] = []
    events: RiEvents = {"shifts": [], "lcp": [], "release": None}
    record: dict[str, object] = {}
    url = site.base_url + page_path(site.builder, docname)
    context = new_context(shared_browser, width=width, height=height)
    try:
        page = context.new_page()
        try:
            page.add_init_script(PERFORMANCE_OBSERVER_JS)
            page.goto(url, wait_until="load")
            supported = observer_types(page)
            try:
                page.wait_for_function("() => window.__ri.lcp.length > 0", timeout=10000)
                lcp_seen = True
            except PlaywrightTimeoutError:
                lcp_seen = False
            events = ri_events(page)
            images = image_states(page)
        finally:
            page.close()
    finally:
        context.close()
    lazy_in_viewport = [dict(state) for state in images if state["in_viewport"] and state["loading"] == "lazy"]
    record = {
        "url": url,
        "docname": docname,
        "builder": builder,
        "viewport": {"width": width, "height": height},
        "observer_types": supported,
        "lcp_seen": lcp_seen,
        "lcp": events["lcp"],
        "shifts": events["shifts"],
        "lazy_in_viewport": lazy_in_viewport,
        "images": [dict(state) for state in images],
    }
    write_observations(out, [{"kind": "env", **_env_meta(shared_browser)}, record])
    assert {"layout-shift", "largest-contentful-paint"} <= set(supported)
    assert lcp_seen, url
    for state in cast(list[dict[str, object]], record["lazy_in_viewport"]):
        # The spec'd first-6-eager rule can place lazy grid cards inside wide
        # viewports (T4 ruling); those are recorded, everything else fails.
        assert cast(int, state["grid_index"]) >= 6, state
    for entry in cast(list[dict[str, object]], record["lcp"]):
        if entry.get("tag") == "IMG":
            assert entry.get("loading") != "lazy", entry


@pytest.mark.browser
def test_visual_format_cases(
    real_sites: RealSites,
    tmp_path: Path,
    shared_browser: Browser,
) -> None:
    """Light/dark screenshots + decoded file facts for each image format.

    ``posts/p01`` carries the top and hero images; the ON page serves the
    chosen variant, the OFF page the original. Screenshots land under
    ``tmp_path/screenshots`` for visual review; PIL readings record the
    before/after format, alpha and orientation handling.
    """
    shots_dir = tmp_path / "screenshots"
    shots_dir.mkdir()
    out = tmp_path / "visual-formats.json"
    env_records: list[dict[str, object]] = [
        {"kind": "env", "source": source_name, **_env_meta(shared_browser, source_name)}
        for source_name in _FORMAT_SOURCES
    ]
    records: list[dict[str, object]] = [env_records[0]]
    for source_index, source_name in enumerate(_FORMAT_SOURCES):
        records[0] = env_records[source_index]
        write_observations(out, records)
        case = image_cases()[source_name]
        for enabled in (True, False):
            site = (
                real_sites.standard("html", enabled=enabled)
                if source_name == "photo.jpg"
                else real_sites.format(source_name, enabled=enabled)
            )
            for color in ("light", "dark"):
                context = new_context(shared_browser, width=1280, height=900, color=color)
                try:
                    page = context.new_page()
                    try:
                        url = site.base_url + page_path(site.builder, "posts/p01")
                        page.goto(url, wait_until="load")
                        decode_all_images(page)
                        entry: dict[str, object] = {
                            "kind": "visual-format",
                            "source": source_name,
                            "enabled": enabled,
                            "color_scheme": color,
                            "url": url,
                            "expected_format": case.format,
                            "expected_size": [case.width, case.height],
                        }
                        stem = f"{Path(source_name).stem}-{'on' if enabled else 'off'}-{color}"
                        for label, selector in (
                            ("top", ".maatlog-post-top-image"),
                            ("hero", ".maatlog-post-hero-image"),
                        ):
                            locator = page.locator(selector)
                            if locator.count():
                                shot = shots_dir / f"{stem}-{label}.png"
                                locator.screenshot(path=str(shot))
                                entry[f"{label}_screenshot"] = str(shot)
                        served: list[dict[str, object]] = []
                        for state in image_states(page):
                            if not state["current_src"]:
                                continue
                            info = _image_file_info(served_file(site.outdir, state["current_src"]))
                            info["css_class"] = state["css_class"]
                            info["natural_width"] = state["natural_width"]
                            info["managed"] = state["marker"] == "w-v1"
                            served.append(info)
                        entry["served_files"] = served
                        records.append(entry)
                        write_observations(out, records)
                    finally:
                        page.close()
                finally:
                    context.close()
    for record in records[1:]:
        served = cast(list[dict[str, object]], record["served_files"])
        managed = [info for info in served if info["managed"]]
        assert served, record["url"]
        assert record.get("top_screenshot") and record.get("hero_screenshot"), record["url"]
        for info in served:
            assert info["format"] == record["expected_format"], info
        if record["enabled"]:
            expected_width = cast(list[int], record["expected_size"])[0]
            assert managed and all(cast(int, info["width"]) < expected_width for info in managed), managed
        if record["source"] == "rgba.png":
            # Transparency must survive conversion: originals and variants keep alpha.
            assert all("A" in str(info["mode"]) for info in served), served
        if record["source"] == "orientation-6.jpg" and record["enabled"]:
            # EXIF orientation 6: stored 1200x800 must be transposed before
            # scaling, so every managed variant keeps the displayed 800x1200
            # (portrait, 2:3) aspect instead of the stored landscape one.
            exp_w, exp_h = cast(list[int], record["expected_size"])
            assert all(
                cast(int, info["height"]) * exp_w == cast(int, info["width"]) * exp_h
                and cast(int, info["height"]) > cast(int, info["width"])
                for info in managed
            ), managed
