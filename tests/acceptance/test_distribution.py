"""Distribution gates: public API documentation coverage and isolated wheel/sdist install."""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tomllib
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

# This module and tools/public_sync/tests/test_distribution_gate.py both run
# `uv build --out-dir dist --clear` against the same repo-root dist/ from a
# module-scoped fixture. Under `quick`'s `--dist loadgroup` (issue #263) this
# keeps them on one worker, so the builds are serial instead of concurrent.
pytestmark = pytest.mark.xdist_group("distribution")

REPO_ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE_SOURCE = REPO_ROOT / "tests" / "acceptance" / "project"
DIST_DIR = REPO_ROOT / "dist"
WHEEL_NAME = "maatlog-0.6.0-py3-none-any.whl"
SDIST_NAME = "maatlog-0.6.0.tar.gz"
EXPECTED_DESCRIPTION = "A Sphinx extension that turns documentation projects into static blogs."
EXPECTED_CLASSIFIERS = (
    "Development Status :: 3 - Alpha",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.14",
    "Framework :: Sphinx :: Extension",
)

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
    "maatlog_author_profiles",
    "maatlog_archive_docname",
    "maatlog_page_size",
    "maatlog_generate_feeds",
    "maatlog_feed_taxonomies",
    "maatlog_feed_limit",
    "maatlog_palette",
    "maatlog_responsive_images",
    "maatlog_responsive_image_widths",
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
    "maatlog/themes/maatlog-base/static/maatlog.js",
    "maatlog/themes/maatlog-base/static/palettes/github.css",
    "maatlog/themes/maatlog-base/static/palettes/neon.css",
    "maatlog/themes/maatlog-base/static/palettes/nord.css",
    "maatlog/themes/maatlog-base/static/palettes/solarized.css",
    "maatlog/themes/maatlog-base/maatlog/post.html",
    "maatlog/themes/maatlog-base/maatlog/archive.html",
    "maatlog/themes/maatlog-base/maatlog/home.html",
    "maatlog/themes/maatlog-base/maatlog/components/post-grid.html",
    "maatlog/themes/maatlog-base/maatlog/components/image.html",
    "maatlog/themes/maatlog-base/maatlog/components/image-policy.html",
    "maatlog/themes/maatlog-default/maatlog-theme.toml",
    "maatlog/themes/maatlog-default/theme.conf",
    "maatlog/themes/maatlog-default/static/maatlog.css",
    "maatlog/themes/maatlog-default/maatlog/components/image-policy.html",
    "maatlog/py.typed",
)

# Responsive-image modules the wheel must ship (Theme API 1.23, issue #217).
_MODULE_MARKERS: tuple[str, ...] = (
    "maatlog/responsive_images.py",
    "maatlog/_responsive_image_cache.py",
    "maatlog/_responsive_image_pixels.py",
    "maatlog/responsive_image_build.py",
    "maatlog/responsive_image_output.py",
    "maatlog/image_contracts.py",
)

FRONTEND_TOOLING_BASENAMES = frozenset(
    {
        ".nvmrc",
        ".prettierignore",
        ".eslintcache",
        ".stylelintcache",
        "eslint.config.mjs",
        "package-lock.json",
        "package.json",
        "prettier.config.mjs",
        "stylelint.config.mjs",
        "tsconfig.json",
    }
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
    tmp_path.mkdir(parents=True, exist_ok=True)
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


def _wheel() -> Path:
    path = DIST_DIR / WHEEL_NAME
    if not path.is_file():
        pytest.fail(f"missing {path}; run `uv build --out-dir dist --clear` first")
    return path


def _sdist() -> Path:
    path = DIST_DIR / SDIST_NAME
    if not path.is_file():
        pytest.fail(f"missing {path}; run `uv build --out-dir dist --clear` first")
    return path


@pytest.fixture(scope="module")
def built_wheel() -> Path:
    completed = subprocess.run(
        ["uv", "build", "--out-dir", "dist", "--clear"],
        cwd=str(REPO_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        pytest.fail(f"uv build failed:\n{completed.stdout}\n{completed.stderr}")
    return _wheel()


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


def test_notice_records_bundled_icon_attribution(repo_root: Path) -> None:
    """同梱するブランドアイコンの出所・ライセンス・商標の扱いを NOTICE に残す。"""
    notice = (repo_root / "NOTICE").read_text(encoding="utf-8")

    assert "Simple Icons" in notice
    assert "CC0 1.0" in notice
    assert "https://github.com/logos" in notice
    assert "https://about.x.com/en/who-we-are/brand-toolkit" in notice
    assert "https://bsky.social/about/blog/press-faq" in notice
    # LinkedIn のロゴは同梱しない。理由を残しておかないと再導入されうる。
    assert "LinkedIn" in notice


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


def test_readmes_document_frontend_quality_without_runtime_node_requirement() -> None:
    for name in ("README.rst", "README.ja.rst"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        for command in (
            "npm ci",
            "npm run check",
            "npm run lint:js",
            "npm run format:check",
            "npm run typecheck:js",
            "npm run lint:css",
            "npm run format",
            # verify.sh full は @pytest.mark.browser のテストを実行するため、
            # Chromium の導入手順が README から消えると手順どおりに検証できない。
            "uv run playwright install chromium",
            "./scripts/ci/verify.sh full",
        ):
            assert command in text, f"{name} missing {command!r}"
        assert "Node.js 24" in text
        assert "browserslist" in text
    assert "Long-tail browsers" in (REPO_ROOT / "README.rst").read_text(encoding="utf-8")
    assert "長尾ブラウザ" in (REPO_ROOT / "README.ja.rst").read_text(encoding="utf-8")


def test_pyproject_declares_pypi_release_metadata() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    assert project["name"] == "maatlog"
    assert project["version"] == "0.6.0"
    assert project["description"] == EXPECTED_DESCRIPTION
    assert project["authors"] == [{"name": "usaturn"}]
    assert project["classifiers"] == list(EXPECTED_CLASSIFIERS)
    assert project["urls"]["Homepage"] == "https://github.com/usaturn/maatlog"
    assert project["readme"] == "README.rst"
    assert project["requires-python"] == ">=3.14"
    assert project["license"] == "MIT"
    assert project["license-files"] == ["LICENSE", "NOTICE"]
    assert project["dependencies"] == ["Sphinx>=9.1", "myst-parser>=5.1", "pydantic>=2"]
    assert data["build-system"]["build-backend"] == "uv_build"
    assert data["build-system"]["requires"] == ["uv_build>=0.12.0,<0.13.0"]


def test_uv_lock_root_package_version_is_0_6_0() -> None:
    data = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    package = next(item for item in data["package"] if item["name"] == "maatlog")
    assert package["version"] == "0.6.0"
    assert package["source"] == {"editable": "."}


def test_docs_release_matches_distribution_version() -> None:
    text = (REPO_ROOT / "docs" / "conf.py").read_text(encoding="utf-8")
    assert 'release = "0.6.0"' in text
    assert 'release = "0.7.0"' not in text


def test_clean_dist_contains_exactly_one_wheel_and_sdist(built_wheel: Path) -> None:
    assert built_wheel.name == WHEEL_NAME
    wheels = sorted(path.name for path in DIST_DIR.glob("*.whl"))
    sdists = sorted(path.name for path in DIST_DIR.glob("*.tar.gz"))
    assert wheels == [WHEEL_NAME]
    assert sdists == [SDIST_NAME]


def test_twine_check_strict_passes(built_wheel: Path) -> None:
    completed = subprocess.run(
        ["uvx", "twine", "check", "--strict", str(built_wheel), str(_sdist())],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"


def test_wheel_core_metadata_is_0_6_0(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
    assert "Name: maatlog\n" in metadata
    assert "Version: 0.6.0\n" in metadata
    assert f"Summary: {EXPECTED_DESCRIPTION}\n" in metadata
    assert "Author: usaturn\n" in metadata
    assert "Project-URL: Homepage, https://github.com/usaturn/maatlog\n" in metadata
    for classifier in EXPECTED_CLASSIFIERS:
        assert f"Classifier: {classifier}\n" in metadata


def test_sdist_core_metadata_is_0_6_0(built_wheel: Path) -> None:
    del built_wheel
    with tarfile.open(_sdist(), "r:gz") as archive:
        pkg_info = archive.extractfile("maatlog-0.6.0/PKG-INFO")
        assert pkg_info is not None
        metadata = pkg_info.read().decode("utf-8")
    assert "Name: maatlog\n" in metadata
    assert "Version: 0.6.0\n" in metadata
    assert f"Summary: {EXPECTED_DESCRIPTION}\n" in metadata


def _isolated_version(tmp_path: Path, package: Path) -> str:
    env = create_isolated_venv(tmp_path)
    env.pip_install(package)
    completed = subprocess.run(
        [
            str(env.python),
            "-c",
            "from importlib.metadata import version; print(version('maatlog'))",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def test_wheel_isolated_install_reports_version_0_6_0(tmp_path: Path, built_wheel: Path) -> None:
    assert _isolated_version(tmp_path, built_wheel) == "0.6.0"


def test_sdist_isolated_install_reports_version_0_6_0(tmp_path: Path, built_wheel: Path) -> None:
    del built_wheel
    assert _isolated_version(tmp_path, _sdist()) == "0.6.0"


def test_wheel_contains_themes_and_package_data(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        names = set(archive.namelist())
        metadata_name = next(n for n in names if n.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
    missing = [marker for marker in (*_THEME_MARKERS, *_MODULE_MARKERS) if marker not in names]
    assert not missing, f"wheel missing package data: {missing}"
    assert "License-Expression: MIT\n" in metadata
    assert "License-File: LICENSE\n" in metadata


def test_wheel_bundled_themes_declare_theme_api_1_23(built_wheel: Path) -> None:
    """Both bundled manifests declare the current Theme API version."""
    with zipfile.ZipFile(built_wheel) as archive:
        manifests = {
            name: tomllib.loads(archive.read(name).decode("utf-8"))
            for name in archive.namelist()
            if name.endswith("maatlog-theme.toml")
        }
    assert len(manifests) == 2
    for name, data in manifests.items():
        assert data["maatlog"]["api"] == "1.23", name


def _assert_no_frontend_dev_tooling(names: set[str]) -> None:
    leaked = sorted(
        name for name in names if "node_modules" in Path(name).parts or Path(name).name in FRONTEND_TOOLING_BASENAMES
    )
    assert not leaked, f"frontend developer tooling leaked into distribution: {leaked}"


def test_wheel_excludes_frontend_dev_tooling(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        _assert_no_frontend_dev_tooling(set(archive.namelist()))


def test_sdist_excludes_frontend_dev_tooling(built_wheel: Path) -> None:
    del built_wheel
    with tarfile.open(_sdist(), "r:gz") as archive:
        _assert_no_frontend_dev_tooling(set(archive.getnames()))


def test_sdist_exists_alongside_wheel(built_wheel: Path) -> None:
    del built_wheel
    sdist = _sdist()
    assert sdist.is_file()
    assert sdist.stat().st_size > 0


def _assert_license_included(names: set[str]) -> None:
    assert any(name.endswith(("/LICENSE", "/licenses/LICENSE")) for name in names), (
        "distribution archive is missing a LICENSE member"
    )


def test_wheel_contains_license(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        _assert_license_included(set(archive.namelist()))
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
        assert "License-Expression: MIT\n" in metadata
        assert "License-File: LICENSE\n" in metadata


def test_sdist_contains_license(built_wheel: Path) -> None:
    del built_wheel
    with tarfile.open(_sdist(), "r:gz") as archive:
        _assert_license_included(set(archive.getnames()))


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
    _isolated_install_builds_acceptance_site(tmp_path, _sdist())


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


# --- Isolated responsive-image verification (Theme API 1.23, issue #217) ---
#
# These tests install the built wheel into fresh venvs and drive real
# ``python -m sphinx`` builds there. No shared PYTHONPATH and no repository
# ``src`` on ``sys.path``: the only maatlog the subprocess sees comes from the
# wheel. Image bytes are generated with Pillow in the parent test process and
# passed to the isolated project as files, so the Pillow-less environment never
# imports Pillow.

# Replace the registered variant-generator factory with a sentinel that fails
# the build if the responsive path ever resolves a generator.
_GUARD_FACTORY_SNIPPET = """
def setup(app):
    from maatlog.image_contracts import register_variant_generator_factory

    def _must_not_run():
        raise AssertionError("variant generator factory must not run")

    register_variant_generator_factory(app, _must_not_run)
"""

# Decode every published variant inside the isolated environment and print the
# distinct Pillow formats found.
_DECODE_VARIANTS_SNIPPET = """\
import sys
from pathlib import Path
from PIL import Image

root = Path(sys.argv[1])
seen = set()
for path in sorted(root.iterdir()):
    if path.name.startswith(".") or path.is_dir():
        continue
    with Image.open(path) as image:
        image.load()
        seen.add(image.format)
assert seen, f"no variants under {root}"
for name in sorted(seen):
    print(name)
"""

# Decode the orientation/alpha/ICC variants inside the minimum-Pillow
# environment and verify the pipeline effects survive.
_VERIFY_MINIMUM_SNIPPET = """\
import re
import sys
from pathlib import Path

import PIL
from PIL import Image

assert PIL.__version__ == "11.3.0", PIL.__version__

root = Path(sys.argv[1])
name_pattern = re.compile(r"(?P<stem>.+)-(?P<width>[0-9]+)w-[0-9a-f]+\\.(?P<ext>jpg|png|webp)\\Z")
stems = set()
for path in sorted(root.iterdir()):
    match = name_pattern.match(path.name)
    if match is None:
        continue
    stem = match.group("stem")
    stems.add(stem)
    with Image.open(path) as image:
        image.load()
        if stem == "orientation-6":
            # Stored 1200x800 with EXIF orientation 6: displayed 800x1200.
            assert image.height == round(1200 * image.width / 800)
            assert not image.getexif()
        elif stem == "rgba":
            assert "A" in image.mode, image.mode
        elif stem == "icc":
            assert image.info.get("icc_profile")
assert stems == {"orientation-6", "rgba", "icc"}, stems
print("ok")
"""


def _isolated_python(env: IsolatedEnv, code: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run *code* with the isolated interpreter; keep stdout/stderr for failures."""
    isolated = dict(os.environ)
    isolated.pop("PYTHONPATH", None)
    return subprocess.run(
        [str(env.python), "-c", code, *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(env.root.parent),
        env=isolated,
    )


def _post_markdown(slug: str, day: int, image_uri: str) -> str:
    return (
        "---\n"
        "maatlog-post: true\n"
        f"maatlog-slug: {slug}\n"
        f"maatlog-published-at: 2026-07-{day:02d}T09:00:00Z\n"
        f"maatlog-image: {image_uri}\n"
        "---\n\n"
        f"# {slug}\n\nBody.\n"
    )


def _multi_format_files(source_names: tuple[str, ...]) -> dict[str, str | bytes]:
    """One featured post per image source, so each stem produces its own variants."""
    from fixtures.responsive_real_project import image_cases, project_files

    cases = image_cases()
    files = project_files(source_name=source_names[0], post_count=len(source_names))
    for index, name in enumerate(source_names[1:], start=2):
        files[f"images/{name}"] = cases[name].payload
        files[f"posts/p{index:02d}.md"] = _post_markdown(f"p{index:02d}", index, f"../images/{name}")
    docnames = sorted(
        name.rsplit(".", 1)[0] for name in files if name != "index.rst" and name.endswith((".rst", ".md"))
    )
    entries = "\n".join(f"   {docname}" for docname in docnames)
    files["index.rst"] = f"Home\n====\n\n.. toctree::\n   :hidden:\n\n{entries}\n"
    return files


def _no_image_files() -> dict[str, str]:
    """A minimal published site with no images at all."""
    files: dict[str, str] = {
        f"posts/p{index:02d}.rst": (
            f"P{index:02d}\n===\n\n"
            ":maatlog-post: true\n"
            f":maatlog-slug: p{index:02d}\n"
            f":maatlog-published-at: 2026-07-{index:02d}T09:00:00Z\n\n"
            "Body.\n"
        )
        for index in range(1, 4)
    }
    entries = "\n".join(f"   posts/p{index:02d}" for index in range(1, 4))
    files["index.rst"] = f"Home\n====\n\n.. toctree::\n   :hidden:\n\n{entries}\n"
    return files


def _guard_factory(srcdir: Path) -> None:
    conf = srcdir / "conf.py"
    conf.write_text(conf.read_text(encoding="utf-8") + _GUARD_FACTORY_SNIPPET, encoding="utf-8")


def _variant_output_root(outdir: Path) -> Path:
    return outdir / "_images" / "maatlog"


# Matrix logs land under the test's own tmp_path so a read-only checkout still
# runs the wheel matrix. Set MAATLOG_MATRIX_LOG_DIR to keep them after the run.
_MATRIX_LOG_DIR_ENV = "MAATLOG_MATRIX_LOG_DIR"


def _matrix_log_dir(root: Path) -> Path:
    override = os.environ.get(_MATRIX_LOG_DIR_ENV)
    return Path(override) if override else root / "matrix-logs"


def _save_matrix_log(root: Path, name: str, completed: subprocess.CompletedProcess[str]) -> Path:
    """Persist one matrix run's stdout/stderr below *root* and return the path."""
    target = _matrix_log_dir(root)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{name}.log"
    path.write_text(
        f"$ exit={completed.returncode}\n--- stdout ---\n{completed.stdout}--- stderr ---\n{completed.stderr}",
        encoding="utf-8",
    )
    return path


_PARTIAL_SUPPORT_CODE = "maatlog.builder.partial-support"
# singlehtml renders post-list cards through the base post-card template, but the
# maatlog_json filter only exists on full-HTML builders, so the minimal-markup
# fallback warning below fires there too. That one is pre-existing and unrelated
# to responsive images, so it is only tolerated, never required: fixing it must
# not break this cell. RealProject.build forces -W, so partial-support alone
# already makes the run exit non-zero.
_POST_CARD_FALLBACK_CODE = "maatlog.theme.post-card-render-failed"
_TOLERATED_SINGLEHTML_WARNINGS = frozenset({_PARTIAL_SUPPORT_CODE, _POST_CARD_FALLBACK_CODE})


def _assert_singlehtml_single_source(
    completed: subprocess.CompletedProcess[str], outdir: Path, *, context: str, log_root: Path
) -> None:
    """singlehtml stays on the single-source path; only pre-existing warnings may fire."""
    log = _save_matrix_log(log_root, context, completed)
    assert completed.returncode != 0, f"{context}: singlehtml -W build should warn; see {log}"
    output = completed.stderr + completed.stdout
    assert _PARTIAL_SUPPORT_CODE in output, f"{context}: partial-support warning missing; see {log}"
    for line in output.splitlines():
        if "WARNING" not in line:
            continue
        assert any(code in line for code in _TOLERATED_SINGLEHTML_WARNINGS), (
            f"{context}: unexpected warning; see {log}\n{line}"
        )
    page = (outdir / "index.html").read_text(encoding="utf-8")
    assert "srcset" not in page, f"{context}: singlehtml must not emit candidates; see {log}"
    assert not _variant_output_root(outdir).exists(), f"{context}: no variant output expected; see {log}"


def _assert_singlehtml_cell(tmp_path: Path, python: Path, *, context: str) -> None:
    """Enabled singlehtml build: no candidates, only pre-existing warnings."""
    from fixtures.responsive_real_build import create_project

    project = create_project(tmp_path / "singlehtml", builder="singlehtml", enabled=True, post_count=3)
    _guard_factory(project.srcdir)
    _assert_singlehtml_single_source(project.build(python=python), project.outdir, context=context, log_root=tmp_path)


def _assert_single_source_output(outdir: Path) -> None:
    """The published page keeps the verbatim source image and no candidates."""
    page = (outdir / "posts" / "p01.html").read_text(encoding="utf-8")
    assert "srcset" not in page
    assert not _variant_output_root(outdir).exists()
    assert list((outdir / "_images").glob("*.jpg")), "expected the verbatim source image"


def _assert_backend_missing(completed: subprocess.CompletedProcess[str]) -> None:
    output = completed.stderr + completed.stdout
    assert completed.returncode != 0, output
    assert "maatlog.image.backend-missing" in output
    assert "maatlog[images]" in output


def test_wheel_metadata_scopes_pillow_to_images_extra(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
    assert "Provides-Extra: images\n" in metadata
    pillow_lines = [
        line for line in metadata.splitlines() if line.startswith("Requires-Dist:") and "pillow" in line.lower()
    ]
    assert pillow_lines, "wheel metadata must declare the optional Pillow dependency"
    for line in pillow_lines:
        assert 'extra == "images"' in line.replace("'", '"')


def test_wheel_without_images_extra(built_wheel: Path, tmp_path: Path) -> None:
    """Wheel alone: PIL absent, OFF stays single-source, ON fails cleanly."""
    from fixtures.responsive_real_build import create_project

    no_images = create_isolated_venv(tmp_path / "without-images")
    no_images.pip_install(built_wheel)

    completed = _isolated_python(
        no_images,
        "import importlib.util, sys; sys.exit(importlib.util.find_spec('PIL') is not None)",
    )
    assert completed.returncode == 0, completed.stderr

    # Disabled html build: exit 0, one source image, no candidates, and the
    # sentinel factory proves the generator path is never resolved.
    off = create_project(tmp_path / "off", enabled=False)
    _guard_factory(off.srcdir)
    result = off.build(python=no_images.python)
    _save_matrix_log(tmp_path, "without-images-off-html", result)
    assert result.returncode == 0, result.stderr + result.stdout
    _assert_single_source_output(off.outdir)

    # Enabled on full-HTML builders fails with the backend-missing diagnostic,
    # whether or not the project carries any images.
    for builder in ("html", "dirhtml"):
        project = create_project(tmp_path / builder, builder=builder, enabled=True, post_count=3)
        result = project.build(python=no_images.python)
        _save_matrix_log(tmp_path, f"without-images-on-{builder}", result)
        _assert_backend_missing(result)
    no_image_project = create_project(
        tmp_path / "no-image-sources",
        enabled=True,
        files=_no_image_files(),
        config={
            "maatlog_featured_posts": [],
            "maatlog_authors": None,
            "maatlog_author_profiles": None,
            "maatlog_default_author": None,
        },
    )
    result = no_image_project.build(python=no_images.python)
    _save_matrix_log(tmp_path, "without-images-on-html-no-sources", result)
    _assert_backend_missing(result)

    # Enabled on non-full-HTML builders keeps single-source behaviour.
    for builder in ("text",):
        project = create_project(tmp_path / builder, builder=builder, enabled=True, post_count=3)
        _guard_factory(project.srcdir)
        result = project.build(python=no_images.python)
        _save_matrix_log(tmp_path, f"without-images-on-{builder}", result)
        assert result.returncode == 0, result.stderr + result.stdout
    _assert_singlehtml_cell(tmp_path, no_images.python, context="without-images-on-singlehtml")


def test_wheel_with_images_extra(built_wheel: Path, tmp_path: Path) -> None:
    """Wheel + [images]: OFF never runs a generator, ON publishes real variants."""
    from fixtures.responsive_real_build import create_project

    with_images = create_isolated_venv(tmp_path / "with-images")
    with_images.pip_install(f"{built_wheel}[images]")

    completed = _isolated_python(
        with_images,
        "import importlib.util, sys; sys.exit(importlib.util.find_spec('PIL') is None)",
    )
    assert completed.returncode == 0, completed.stderr

    # Disabled build: the sentinel factory proves no generator resolution even
    # though Pillow is importable in this environment.
    off = create_project(tmp_path / "off", enabled=False)
    _guard_factory(off.srcdir)
    result = off.build(python=with_images.python)
    _save_matrix_log(tmp_path, "with-images-off-html", result)
    assert result.returncode == 0, result.stderr + result.stdout
    _assert_single_source_output(off.outdir)

    # Enabled html build publishes JPEG/PNG/WebP variants that decode in the
    # isolated environment.
    on = create_project(
        tmp_path / "on",
        enabled=True,
        files=_multi_format_files(("photo.jpg", "rgba.png", "still.webp")),
    )
    result = on.build(python=with_images.python)
    _save_matrix_log(tmp_path, "with-images-on-html", result)
    assert result.returncode == 0, result.stderr + result.stdout
    page = (on.outdir / "posts" / "p01.html").read_text(encoding="utf-8")
    assert "srcset" in page
    completed = _isolated_python(with_images, _DECODE_VARIANTS_SNIPPET, str(_variant_output_root(on.outdir)))
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.split() == ["JPEG", "PNG", "WEBP"]

    # Enabled on non-full-HTML builders produces no candidates.
    for builder in ("text",):
        project = create_project(tmp_path / builder, builder=builder, enabled=True, post_count=3)
        _guard_factory(project.srcdir)
        result = project.build(python=with_images.python)
        _save_matrix_log(tmp_path, f"with-images-on-{builder}", result)
        assert result.returncode == 0, result.stderr + result.stdout
    _assert_singlehtml_cell(tmp_path, with_images.python, context="with-images-on-singlehtml")


def test_wheel_with_minimum_pillow(built_wheel: Path, tmp_path: Path) -> None:
    """Wheel + [images] pinned to Pillow 11.3.0 keeps the full pipeline."""
    from fixtures.responsive_real_build import create_project

    minimum = create_isolated_venv(tmp_path / "minimum-images")
    minimum.pip_install(f"{built_wheel}[images]", "Pillow==11.3.0")

    completed = _isolated_python(
        minimum,
        "import PIL, sys; sys.exit(PIL.__version__ != '11.3.0')",
    )
    assert completed.returncode == 0, completed.stderr

    # Disabled behaviour is unchanged at the floor version.
    off = create_project(tmp_path / "off", enabled=False)
    _guard_factory(off.srcdir)
    result = off.build(python=minimum.python)
    _save_matrix_log(tmp_path, "minimum-pillow-off-html", result)
    assert result.returncode == 0, result.stderr + result.stdout
    _assert_single_source_output(off.outdir)

    # Enabled html build covers all three formats plus EXIF, alpha, and ICC.
    on = create_project(
        tmp_path / "on",
        enabled=True,
        files=_multi_format_files(("orientation-6.jpg", "rgba.png", "icc.png")),
    )
    result = on.build(python=minimum.python)
    _save_matrix_log(tmp_path, "minimum-pillow-on-html", result)
    assert result.returncode == 0, result.stderr + result.stdout
    completed = _isolated_python(minimum, _VERIFY_MINIMUM_SNIPPET, str(_variant_output_root(on.outdir)))
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"

    # Non-HTML builders stay on the single-source path.
    text_project = create_project(tmp_path / "text", builder="text", enabled=True, post_count=3)
    _guard_factory(text_project.srcdir)
    result = text_project.build(python=minimum.python)
    _save_matrix_log(tmp_path, "minimum-pillow-on-text", result)
    assert result.returncode == 0, result.stderr + result.stdout
    _assert_singlehtml_cell(tmp_path, minimum.python, context="minimum-pillow-on-singlehtml")
