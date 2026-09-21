"""Shared pytest plugin supplying built distribution artifacts (issue #318).

One wheel + one sdist per pytest process, together with the provenance
manifest recorded at build time.

Modes:
- explicit: ``--distribution-artifacts-dir <dir>`` or
  ``MAATLOG_DIST_ARTIFACTS_DIR`` names a directory that already contains
  the pair and the manifest written at build time. A missing manifest,
  missing file, or hash mismatch fails the run immediately.
- standalone: with no directory configured, the session fixture builds
  once into a run-private dir under the pytest basetemp (per worker under
  pytest-xdist), so an arbitrary ``pytest -n`` never writes to the shared
  repo-root ``dist/``.

Any item requesting ``distribution_artifacts`` is auto-marked
``distribution`` (used by verify.sh selection) and
``xdist_group("distribution")`` (single worker under ``--dist loadgroup``)
at collection time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

MANIFEST_NAME = "distribution-manifest.json"
MANIFEST_VERSION = 1
ENV_VAR = "MAATLOG_DIST_ARTIFACTS_DIR"
REPO_ROOT = Path(__file__).resolve().parents[2]


class DistributionArtifactsError(RuntimeError):
    """Raised when the configured artifacts directory is unusable."""


@dataclass(frozen=True)
class DistributionArtifacts:
    """Built wheel/sdist pair plus provenance recorded at build time."""

    directory: Path
    wheel: Path
    sdist: Path
    source_sha: str
    package_version: str
    input_sha256: str
    hashes: dict[str, str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _single_artifact(directory: Path, pattern: str) -> Path:
    matches = sorted(path for path in directory.glob(pattern) if path.is_file())
    if len(matches) == 1:
        return matches[0]
    names = ", ".join(path.name for path in matches) or "<none>"
    raise DistributionArtifactsError(
        f"expected exactly one {pattern} file in {directory}, found {len(matches)}: {names}"
    )


def _source_sha(repo_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return "unknown"
    if completed.returncode != 0:
        return "unknown"
    sha = completed.stdout.strip()
    return sha if sha else "unknown"


def _package_info(repo_root: Path) -> tuple[str, str]:
    """Return ``([project].version, sha256 of pyproject.toml)``."""
    pyproject_path = repo_root / "pyproject.toml"
    try:
        raw = pyproject_path.read_bytes()
    except OSError as exc:
        raise DistributionArtifactsError(f"cannot read {pyproject_path}: {exc}") from exc
    try:
        document = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise DistributionArtifactsError(f"cannot parse {pyproject_path}: {exc}") from exc
    project = document.get("project")
    if not isinstance(project, dict):
        raise DistributionArtifactsError(f"{pyproject_path}: [project] table is missing")
    version = cast(dict[str, Any], project).get("version")
    if not isinstance(version, str) or not version:
        raise DistributionArtifactsError(f"{pyproject_path}: [project].version is missing")
    return version, hashlib.sha256(raw).hexdigest()


def write_manifest(directory: Path, repo_root: Path) -> Path:
    """Write the provenance manifest for an existing wheel/sdist pair.

    The directory must contain exactly one ``*.whl`` and one ``*.tar.gz``.
    """
    wheel = _single_artifact(directory, "*.whl")
    sdist = _single_artifact(directory, "*.tar.gz")
    package_version, input_sha256 = _package_info(repo_root)
    payload = {
        "version": MANIFEST_VERSION,
        "source_sha": _source_sha(repo_root),
        "package_version": package_version,
        "input_sha256": input_sha256,
        "wheel": wheel.name,
        "sdist": sdist.name,
        "hashes": {wheel.name: _sha256(wheel), sdist.name: _sha256(sdist)},
    }
    manifest_path = directory / MANIFEST_NAME
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def _manifest_str(manifest_path: Path, payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise DistributionArtifactsError(f"{manifest_path}: {key!r} must be a non-empty string")
    return value


def _manifest_provenance(
    manifest_path: Path,
    payload: dict[str, Any],
    repo_root: Path,
) -> tuple[str, str, str]:
    version = payload.get("version")
    if type(version) is not int or version != MANIFEST_VERSION:
        raise DistributionArtifactsError(
            f"{manifest_path}: unsupported 'version' {version!r}; expected {MANIFEST_VERSION}"
        )

    source_sha = _manifest_str(manifest_path, payload, "source_sha")
    package_version = _manifest_str(manifest_path, payload, "package_version")
    input_sha256 = _manifest_str(manifest_path, payload, "input_sha256")
    expected_package_version, expected_input_sha256 = _package_info(repo_root)
    expected = {
        "source_sha": _source_sha(repo_root),
        "package_version": expected_package_version,
        "input_sha256": expected_input_sha256,
    }
    recorded = {
        "source_sha": source_sha,
        "package_version": package_version,
        "input_sha256": input_sha256,
    }
    for key, expected_value in expected.items():
        recorded_value = recorded[key]
        if recorded_value != expected_value:
            raise DistributionArtifactsError(
                f"{manifest_path}: stale {key!r}: manifest records {recorded_value!r}, "
                f"current checkout expects {expected_value!r}"
            )
    return source_sha, package_version, input_sha256


def _artifact_path(directory: Path, manifest_path: Path, payload: dict[str, Any], key: str) -> Path:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise DistributionArtifactsError(f"{manifest_path}: {key!r} must be a file name string")
    if Path(value).name != value or "\\" in value:
        raise DistributionArtifactsError(f"{manifest_path}: {key!r} must be a bare file name, got {value!r}")
    return directory / value


def _manifest_hashes(manifest_path: Path, payload: dict[str, Any]) -> dict[str, str]:
    value = payload.get("hashes")
    if not isinstance(value, dict):
        raise DistributionArtifactsError(f"{manifest_path}: 'hashes' must be an object")
    hashes: dict[str, str] = {}
    for key, item in cast(dict[object, object], value).items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise DistributionArtifactsError(f"{manifest_path}: 'hashes' must map file names to sha256 hex")
        hashes[key] = item
    return hashes


def load_artifacts(directory: Path, repo_root: Path = REPO_ROOT) -> DistributionArtifacts:
    """Load and verify the wheel/sdist pair recorded by the manifest.

    The manifest is mandatory, both artifacts must exist, and their sha256
    must match the recorded hashes. Any inconsistency raises
    :class:`DistributionArtifactsError` naming what failed and where.
    """
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.is_file():
        raise DistributionArtifactsError(
            f"{MANIFEST_NAME} is missing from {directory}: "
            "build the artifacts first or write the manifest with this module's CLI"
        )
    try:
        parsed: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DistributionArtifactsError(f"cannot read {manifest_path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise DistributionArtifactsError(f"{manifest_path}: expected a JSON object")
    payload = cast(dict[str, Any], parsed)
    source_sha, package_version, input_sha256 = _manifest_provenance(manifest_path, payload, repo_root)

    wheel = _artifact_path(directory, manifest_path, payload, "wheel")
    sdist = _artifact_path(directory, manifest_path, payload, "sdist")
    hashes = _manifest_hashes(manifest_path, payload)
    for path in (wheel, sdist):
        if not path.is_file():
            raise DistributionArtifactsError(f"{manifest_path} lists {path.name} but it is missing from {directory}")
        expected = hashes.get(path.name)
        if expected is None:
            raise DistributionArtifactsError(f"{manifest_path} has no sha256 hash recorded for {path.name}")
        actual = _sha256(path)
        if actual != expected:
            raise DistributionArtifactsError(
                f"{path} sha256 mismatch: manifest records {expected}, file hashes to {actual}"
            )
    return DistributionArtifacts(
        directory=directory,
        wheel=wheel,
        sdist=sdist,
        source_sha=source_sha,
        package_version=package_version,
        input_sha256=input_sha256,
        hashes=hashes,
    )


def build_artifacts(directory: Path, repo_root: Path) -> DistributionArtifacts:
    """Run ``uv build --out-dir <directory> --clear`` and return verified artifacts."""
    directory.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            ["uv", "build", "--out-dir", str(directory), "--clear"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise DistributionArtifactsError(f"failed to run uv build in {repo_root}: {exc}") from exc
    if completed.returncode != 0:
        raise DistributionArtifactsError(
            f"uv build failed with exit code {completed.returncode} (out-dir {directory}, cwd {repo_root})\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    write_manifest(directory, repo_root)
    return load_artifacts(directory, repo_root)


def _configured_directory(config: pytest.Config) -> Path | None:
    option: object = config.getoption("--distribution-artifacts-dir")
    raw = option if isinstance(option, str) and option else os.environ.get(ENV_VAR)
    if raw is None or not raw.strip():
        return None
    return Path(raw).expanduser().resolve()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--distribution-artifacts-dir",
        action="store",
        default=None,
        metavar="DIR",
        help=(f"load the wheel/sdist pair and {MANIFEST_NAME} from DIR instead of building; overrides ${ENV_VAR}"),
    )


def pytest_itemcollected(item: pytest.Item) -> None:
    fixturenames = getattr(item, "fixturenames", ())
    if "distribution_artifacts" not in fixturenames:
        return
    item.add_marker("distribution")
    item.add_marker(pytest.mark.xdist_group("distribution"))


@pytest.fixture(scope="session")
def distribution_artifacts(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> DistributionArtifacts:
    """One wheel+sdist pair per pytest process (per worker under pytest-xdist)."""
    configured = _configured_directory(request.config)
    try:
        if configured is not None:
            return load_artifacts(configured)
        build_dir = tmp_path_factory.mktemp("distribution-artifacts")
        return build_artifacts(build_dir, REPO_ROOT)
    except DistributionArtifactsError as exc:
        pytest.fail(str(exc))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: write the manifest for an existing wheel/sdist pair."""
    parser = argparse.ArgumentParser(
        description=f"Write {MANIFEST_NAME} into DIR for the wheel/sdist pair it already contains."
    )
    parser.add_argument("directory", metavar="DIR", help="directory holding one wheel and one sdist")
    args = parser.parse_args(argv)
    directory = Path(str(args.directory)).expanduser().resolve()
    try:
        write_manifest(directory, REPO_ROOT)
        artifacts = load_artifacts(directory)
    except DistributionArtifactsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{artifacts.wheel.name} {artifacts.sdist.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
