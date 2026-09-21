"""Shared acceptance-site lifecycle tests (Issue #314)."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from acceptance.built_sites import BuiltSite, BuiltSites, SiteKey
from acceptance.site import DEFAULT_SOURCE_DATE_EPOCH, PROJECT_ROOT, build_acceptance_site
from sphinx.application import Sphinx


def _write_site(root: Path, monkeypatch: pytest.MonkeyPatch, *, body: str = "ready") -> Path:
    monkeypatch.setenv("MAATLOG_BUILT_SITE_BUILD", "active")
    outdir = root / "output"
    outdir.mkdir(parents=True)
    (outdir / "index.html").write_text(body, encoding="utf-8")
    return outdir


def _key(**changes: object) -> SiteKey:
    values: dict[str, object] = {
        "fixture": "acceptance",
        "input_id": "fixed-project-v1",
        "builder": "html",
        "theme": "maatlog-default",
        "config": {"maatlog_page_size": 10, "nested": {"items": ["a", "b"]}},
        "source_date_epoch": "1786752000",
        "responsive_images": False,
        "warningiserror": True,
        "project_root": Path("/site-project"),
    }
    values.update(changes)
    return SiteKey(**values)  # type: ignore[arg-type]


def test_site_key_normalizes_equivalent_config() -> None:
    left = _key(config={"nested": {"items": ["a", "b"]}, "maatlog_page_size": 10})
    right = _key(config={"maatlog_page_size": 10, "nested": {"items": ("a", "b")}})

    assert left == right
    assert hash(left) == hash(right)


def test_site_key_distinguishes_config_scalar_types() -> None:
    keys = [
        _key(config={"x": True}),
        _key(config={"x": 1}),
        _key(config={"x": 1.0}),
        _key(config={"x": Path("x")}),
        _key(config={"x": "x"}),
    ]

    assert len(set(keys)) == len(keys)


def test_same_key_builds_and_serves_once(tmp_path: Path) -> None:
    calls: list[Path] = []

    def build(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        calls.append(root)
        return _write_site(root, monkeypatch)

    with BuiltSites(tmp_path) as sites:
        first = sites.get(_key(), build)
        second = sites.get(_key(), build)

        assert first is second
        assert calls == [tmp_path / "site-0001"]
        with urlopen(first.base_url, timeout=1) as response:  # noqa: S310 - loopback test server
            assert response.read() == b"ready"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fixture", "responsive-fake"),
        ("input_id", "fixed-project-v2"),
        ("builder", "dirhtml"),
        ("theme", "maatlog-base"),
        ("config", {"maatlog_page_size": 9}),
        ("source_date_epoch", "1786752001"),
        ("responsive_images", True),
        ("warningiserror", False),
        ("project_root", Path("/other-project")),
    ],
)
def test_each_key_element_selects_a_distinct_site(tmp_path: Path, field: str, value: object) -> None:
    calls = 0

    def build(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        nonlocal calls
        calls += 1
        return _write_site(root, monkeypatch, body=str(calls))

    with BuiltSites(tmp_path) as sites:
        original = sites.get(_key(), build)
        changed = sites.get(_key(**{field: value}), build)

        assert calls == 2
        assert original.outdir != changed.outdir
        assert original.base_url != changed.base_url


def test_unrequested_key_is_not_built(tmp_path: Path) -> None:
    with BuiltSites(tmp_path):
        assert list(tmp_path.iterdir()) == []

    assert list(tmp_path.iterdir()) == []


def test_failed_build_is_not_cached(tmp_path: Path) -> None:
    calls = 0

    def build(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        nonlocal calls
        calls += 1
        if calls == 1:
            (root / "partial").mkdir(parents=True)
            raise RuntimeError("build failed")
        return _write_site(root, monkeypatch)

    with BuiltSites(tmp_path) as sites:
        with pytest.raises(RuntimeError, match="build failed"):
            sites.get(_key(), build)

        built = sites.get(_key(), build)

    assert calls == 2
    assert built.outdir.name == "output"


def test_lenient_build_exception_is_not_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = SiteKey(
        fixture="acceptance",
        input_id="fixed-project-v1",
        builder="html",
        theme="maatlog-default",
        config={},
        source_date_epoch=DEFAULT_SOURCE_DATE_EPOCH,
        responsive_images=False,
        warningiserror=False,
        project_root=PROJECT_ROOT,
    )
    calls = 0
    real_build = Sphinx.build

    def flaky_build(self: Sphinx) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("build failed")
        real_build(self)

    monkeypatch.setattr(Sphinx, "build", flaky_build)
    build = build_acceptance_site(key)

    with BuiltSites(tmp_path) as sites:
        with pytest.raises(RuntimeError, match="build failed"):
            sites.get(key, build)

        built = sites.get(key, build)

    assert calls == 2
    assert (built.outdir / "index.html").is_file()


def test_build_environment_is_restored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAATLOG_BUILT_SITE_BUILD", "outside")

    with BuiltSites(tmp_path) as sites:
        sites.get(_key(), _write_site)

    assert os.environ["MAATLOG_BUILT_SITE_BUILD"] == "outside"


def test_close_stops_server(tmp_path: Path) -> None:
    sites = BuiltSites(tmp_path)
    built = sites.get(_key(), _write_site)
    assert isinstance(built, BuiltSite)
    with urlopen(built.base_url, timeout=1) as response:  # noqa: S310 - loopback test server
        assert response.status == 200

    sites.close()

    with pytest.raises(URLError):
        urlopen(built.base_url, timeout=1)  # noqa: S310 - loopback test server


def test_get_after_close_is_rejected(tmp_path: Path) -> None:
    sites = BuiltSites(tmp_path)
    sites.get(_key(), _write_site)
    sites.close()

    with pytest.raises(RuntimeError, match="closed"):
        sites.get(_key(), _write_site)


def test_each_key_gets_an_independent_root(tmp_path: Path) -> None:
    def build(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        del monkeypatch
        outdir = root / "output"
        outdir.mkdir(parents=True)
        (outdir / "index.html").write_text(root.name, encoding="utf-8")
        return outdir

    with BuiltSites(tmp_path) as sites:
        first = sites.get(_key(input_id="one"), build)
        second = sites.get(_key(input_id="two"), build)

        assert first.outdir.parent != second.outdir.parent
        with urlopen(first.base_url, timeout=1) as response:  # noqa: S310 - loopback test server
            assert response.read() == first.outdir.parent.name.encode()
        with urlopen(second.base_url, timeout=1) as response:  # noqa: S310 - loopback test server
            assert response.read() == second.outdir.parent.name.encode()


def test_acceptance_site_build_requires_project_root() -> None:
    with pytest.raises(ValueError, match="project_root"):
        build_acceptance_site(_key(project_root=None))


def test_acceptance_site_builder_uses_the_managed_root(tmp_path: Path) -> None:
    key = SiteKey(
        fixture="acceptance",
        input_id="fixed-project-v1",
        builder="html",
        theme="maatlog-default",
        config={},
        source_date_epoch=DEFAULT_SOURCE_DATE_EPOCH,
        responsive_images=False,
        project_root=PROJECT_ROOT,
    )

    with BuiltSites(tmp_path) as sites:
        built = sites.get(key, build_acceptance_site(key))

        assert built.outdir == (tmp_path / "site-0001" / "out-html-1").resolve()
        assert (built.outdir / "index.html").is_file()
        with urlopen(built.base_url, timeout=1) as response:  # noqa: S310 - loopback test server
            assert response.status == 200
