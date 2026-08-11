"""Distribution gates: public API documentation coverage and isolated wheel/sdist install."""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from importlib.metadata import version as distribution_version
from pathlib import Path
from unittest.mock import create_autospec

import pytest
from sphinx.application import Sphinx

import maatlog
from maatlog.feeds import default_generator
from maatlog.version import PACKAGE_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE_SOURCE = REPO_ROOT / "tests" / "acceptance" / "project"
DIST_DIR = REPO_ROOT / "dist"

# Public authoring keys (Spec 01).
PUBLIC_METADATA_KEYS: tuple[str, ...] = (
    "maatlog-post",
    "maatlog-published-at",
    "maatlog-expires-at",
    "maatlog-slug",
    "maatlog-tags",
    "maatlog-categories",
    "maatlog-authors",
    "maatlog-excerpt",
    "maatlog-image",
    "maatlog-canonical-url",
    "maatlog-external-url",
)

# Public conf.py names (Spec 01).
PUBLIC_CONFIG_NAMES: tuple[str, ...] = (
    "maatlog_timezone",
    "maatlog_tags",
    "maatlog_categories",
    "maatlog_authors",
    "maatlog_archive_docname",
    "maatlog_page_size",
    "maatlog_generate_feeds",
    "maatlog_feed_taxonomies",
    "maatlog_feed_limit",
)

# Documented Sphinx role syntax (Spec 02).
PUBLIC_ROLE_NAMES: tuple[str, ...] = (
    ":maatlog:post:",
    ":maatlog:tag:",
    ":maatlog:category:",
    ":maatlog:author:",
    ":maatlog:month:",
)

# Expected package data inside the wheel.
_THEME_MARKERS: tuple[str, ...] = (
    "maatlog/themes/maatlog-base/maatlog-theme.toml",
    "maatlog/themes/maatlog-base/theme.conf",
    "maatlog/themes/maatlog-base/static/maatlog.css",
    "maatlog/themes/maatlog-base/maatlog/post.html",
    "maatlog/themes/maatlog-base/maatlog/archive.html",
    "maatlog/themes/maatlog-default/maatlog-theme.toml",
    "maatlog/themes/maatlog-default/theme.conf",
    "maatlog/themes/maatlog-default/static/maatlog.css",
    "maatlog/py.typed",
)

# Invoke sphinx.cmd.build.main with argv-style arguments.
_SPHINX_BUILD_SNIPPET = "import sys\nfrom sphinx.cmd.build import main\nsys.exit(main(sys.argv[1:]))\n"


@dataclass(frozen=True)
class IsolatedEnv:
    """Minimal venv helper for wheel-install acceptance."""

    root: Path
    python: Path

    def pip_install(self, *packages: str | Path) -> None:
        cmd = [
            "uv",
            "pip",
            "install",
            "--python",
            str(self.python),
            *[str(p) for p in packages],
        ]
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise AssertionError(f"uv pip install failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")


def create_isolated_venv(tmp_path: Path) -> IsolatedEnv:
    root = tmp_path / "venv"
    completed = subprocess.run(
        [
            "uv",
            "venv",
            str(root),
            "--python",
            f"{sys.version_info.major}.{sys.version_info.minor}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(f"uv venv failed: {completed.stderr}")
    python = root / "bin" / "python"
    if not python.is_file():
        python = root / "Scripts" / "python.exe"
    assert python.is_file(), f"venv python missing under {root}"
    return IsolatedEnv(root=root, python=python)


def _latest_wheel() -> Path:
    wheels = sorted(DIST_DIR.glob("maatlog-*.whl"))
    if not wheels:
        pytest.fail(f"No wheel in {DIST_DIR}; run `uv build` first")
    return wheels[-1]


def _latest_sdist() -> Path:
    sdists = sorted(DIST_DIR.glob("maatlog-*.tar.gz"))
    if not sdists:
        pytest.fail(f"No sdist in {DIST_DIR}; run `uv build` first")
    return sdists[-1]


@pytest.fixture(scope="module")
def built_wheel() -> Path:
    """Build a fresh wheel once per test module so package data matches HEAD."""
    completed = subprocess.run(
        ["uv", "build"],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        pytest.fail(f"uv build failed:\n{completed.stdout}\n{completed.stderr}")
    return _latest_wheel()


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


def test_public_interfaces_are_documented(repo_root: Path) -> None:
    docs_dir = repo_root / "docs"
    rst_files = sorted(docs_dir.glob("*.rst"))
    assert rst_files, f"expected user docs under {docs_dir}/*.rst"
    text = "\n".join(path.read_text(encoding="utf-8") for path in rst_files)
    missing = [name for name in (*PUBLIC_METADATA_KEYS, *PUBLIC_CONFIG_NAMES, *PUBLIC_ROLE_NAMES) if name not in text]
    assert not missing, f"public names missing from docs/*.rst: {missing}"


def test_authoring_documents_myst_yaml_string_quoting(repo_root: Path) -> None:
    authoring = (repo_root / "docs" / "authoring.rst").read_text(encoding="utf-8")
    assert 'maatlog-tags: ["on", "1.2"]' in authoring
    assert 'maatlog-published-at: "2026-07-01T00:00:00Z"' in authoring
    assert "YAML の暗黙の型付け" in authoring


def test_readme_covers_install_and_quickstart(repo_root: Path) -> None:
    readme = (repo_root / "README.rst").read_text(encoding="utf-8")
    for needle in (
        "pip install",
        "extensions",
        "maatlog",
        "html_theme",
        "maatlog-default",
        "sphinx-build",
        "maatlog-post",
        "html_baseurl",
    ):
        assert needle in readme, f"README.rst missing quickstart content: {needle!r}"


def test_wheel_contains_themes_and_package_data(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        names = set(archive.namelist())
        metadata_name = next(n for n in names if n.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
    missing = [marker for marker in _THEME_MARKERS if marker not in names]
    assert not missing, f"wheel missing package data: {missing}"
    assert "License-Expression: MIT\n" in metadata
    assert "License-File: LICENSE\n" in metadata


def test_sdist_exists_alongside_wheel(built_wheel: Path) -> None:
    del built_wheel
    sdist = _latest_sdist()
    assert sdist.is_file()
    assert sdist.stat().st_size > 0


_PRIVATE_DISTRIBUTION_PARTS = {
    ".agents",
    ".claude",
    ".codex",
    ".devcontainer",
    "devenv",
    "docs_draft",
    "reviews",
}


def _assert_public_distribution_members(names: set[str]) -> None:
    parts = {part for name in names for part in Path(name).parts}
    assert not parts.intersection(_PRIVATE_DISTRIBUTION_PARTS)
    assert not any("tools/public_sync" in name for name in names)
    assert any(name.endswith(("/LICENSE", "/licenses/LICENSE")) for name in names)


def test_wheel_has_license_and_no_private_paths(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        _assert_public_distribution_members(set(archive.namelist()))
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
        assert "License-Expression: MIT\n" in metadata
        assert "License-File: LICENSE\n" in metadata


def test_sdist_has_license_and_no_private_paths(built_wheel: Path) -> None:
    del built_wheel
    with tarfile.open(_latest_sdist(), "r:gz") as archive:
        _assert_public_distribution_members(set(archive.getnames()))


def _isolated_install_builds_acceptance_site(tmp_path: Path, package: Path) -> None:
    """Install *package* (wheel or sdist) into a fresh venv and build the acceptance site."""
    env = create_isolated_venv(tmp_path)
    env.pip_install(package)

    outdir = tmp_path / "html"
    doctreedir = tmp_path / "doctrees"
    outdir.mkdir()
    doctreedir.mkdir()

    # Match acceptance suite clock so draft/scheduled/expired stay non-public.
    completed = subprocess.run(
        [
            str(env.python),
            "-c",
            _SPHINX_BUILD_SNIPPET,
            "-W",
            "-b",
            "html",
            "-d",
            str(doctreedir),
            str(ACCEPTANCE_SOURCE),
            str(outdir),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "SOURCE_DATE_EPOCH": "1786752000"},
    )
    assert completed.returncode == 0, (
        f"sphinx-build failed ({completed.returncode})\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert (outdir / "index.html").is_file()
    assert (outdir / "blog.html").is_file() or (outdir / "blog" / "index.html").is_file()
    assert (outdir / "blog" / "atom.xml").is_file()


def test_wheel_builds_acceptance_site(tmp_path: Path, built_wheel: Path) -> None:
    _isolated_install_builds_acceptance_site(tmp_path, built_wheel)


def test_sdist_builds_acceptance_site(tmp_path: Path, built_wheel: Path) -> None:
    """Spec §7: isolated install from sdist must build the same acceptance project."""
    del built_wheel  # ensures uv build ran; install from sdist, not the wheel
    _isolated_install_builds_acceptance_site(tmp_path, _latest_sdist())


def test_setup_metadata_declares_parallel_write_safe() -> None:
    """Release gate: archives via main-process html-collect-pages; feeds/manifests via build-finished."""
    app = create_autospec(Sphinx, instance=True)
    metadata = maatlog.setup(app)
    assert metadata.get("parallel_read_safe") is True
    assert metadata.get("parallel_write_safe") is True


def test_extension_and_atom_share_distribution_version() -> None:
    app = create_autospec(Sphinx, instance=True)
    metadata = maatlog.setup(app)
    expected = distribution_version("maatlog")
    assert PACKAGE_VERSION == expected
    assert metadata.get("version") == expected
    assert default_generator() == f"MaatLog {expected}"
