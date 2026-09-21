"""Unit tests for the shared ``distribution_artifacts`` plugin (issue #318).

Manifest write/load and ``uv build`` invocation are covered in-process.
Plugin wiring (option precedence, marker auto-assignment, per-worker
standalone builds) is exercised in subprocess pytest runs that load
``fixtures.distribution`` via ``-p`` — the same mechanism ``addopts`` uses.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

import pytest
from fixtures import distribution

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
PLUGIN_PATH = TESTS_DIR / "fixtures" / "distribution.py"
WHEEL_NAME = "maatlog-0.6.0-py3-none-any.whl"
SDIST_NAME = "maatlog-0.6.0.tar.gz"

_FAKE_WHEEL = b"stub wheel payload\n"
_FAKE_SDIST = b"stub sdist payload\n"

# A fake ``uv`` that mimics ``uv build --out-dir DIR --clear``: writes one wheel
# and one sdist into DIR and appends its argv to $FAKE_UV_LOG so tests can
# assert how it was invoked (or, for the failing variant, that it never ran).
_UV_BUILD_STUB = """\
#!/usr/bin/env bash
set -euo pipefail
out_dir=""
prev=""
for arg in "$@"; do
  if [[ "$prev" == "--out-dir" ]]; then
    out_dir="$arg"
  fi
  prev="$arg"
done
printf '%s\\n' "$*" >> "${FAKE_UV_LOG:?FAKE_UV_LOG is not set}"
if [[ -z "$out_dir" ]]; then
  echo "uv stub: missing --out-dir" >&2
  exit 2
fi
mkdir -p "$out_dir"
printf 'stub wheel payload\\n' > "$out_dir/maatlog-0.6.0-py3-none-any.whl"
printf 'stub sdist payload\\n' > "$out_dir/maatlog-0.6.0.tar.gz"
"""

_UV_FAIL_STUB = """\
#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${FAKE_UV_LOG:?FAKE_UV_LOG is not set}"
echo "uv stub: stdout marker"
echo "uv stub: stderr marker" >&2
exit 7
"""

# Dumps each collected item's own marker names as JSON so the test can assert
# which marks ``pytest_itemcollected`` auto-added.
_MARKS_DUMP_PLUGIN = """\
import json
import os


def pytest_collection_modifyitems(items):
    payload = {item.nodeid: sorted(mark.name for mark in item.own_markers) for item in items}
    with open(os.environ["MARKS_DUMP"], "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
"""

# Requests the fixture by name only; importing the plugin is unnecessary.
_MARKER_MODULE = """\
import pytest


def test_x(distribution_artifacts):
    pass


@pytest.mark.parametrize("value", [1, 2])
def test_param(distribution_artifacts, value):
    pass


def test_y():
    pass
"""

_USES_ARTIFACTS_MODULE = """\
def test_it(distribution_artifacts):
    assert distribution_artifacts.wheel.is_file()
    assert distribution_artifacts.sdist.is_file()
"""

_TWO_TEST_MODULE = """\
def test_a(distribution_artifacts):
    pass


def test_b(distribution_artifacts):
    pass
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_artifacts(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    wheel = directory / WHEEL_NAME
    sdist = directory / SDIST_NAME
    wheel.write_bytes(_FAKE_WHEEL)
    sdist.write_bytes(_FAKE_SDIST)
    return wheel, sdist


def _write_module(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def _write_uv_stub(bin_dir: Path, script: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "uv"
    stub.write_text(script, encoding="utf-8")
    stub.chmod(0o755)


def _rewrite_manifest(directory: Path, *, remove: str | None = None, **updates: object) -> None:
    manifest = directory / distribution.MANIFEST_NAME
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if remove is not None:
        payload.pop(remove)
    payload.update(updates)
    manifest.write_text(json.dumps(payload), encoding="utf-8")


def _stub_path_env(bin_dir: Path) -> str:
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


def _run_pytest(
    args: Sequence[str],
    *,
    cwd: Path,
    env_extra: dict[str, str] | None = None,
    extra_pythonpath: Sequence[Path] = (),
) -> subprocess.CompletedProcess[str]:
    pythonpath = os.pathsep.join([str(TESTS_DIR), *(str(path) for path in extra_pythonpath)])
    env = {**os.environ, "PYTHONPATH": pythonpath}
    env.pop(distribution.ENV_VAR, None)
    if env_extra is not None:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "fixtures.distribution", "-p", "no:cacheprovider", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _collected_names(completed: subprocess.CompletedProcess[str]) -> list[str]:
    return sorted(line.rsplit("::", 1)[-1] for line in completed.stdout.splitlines() if "::" in line)


def test_write_manifest_then_load_artifacts_round_trip(tmp_path: Path) -> None:
    directory = tmp_path / "artifacts"
    wheel, sdist = _make_artifacts(directory)

    manifest_path = distribution.write_manifest(directory, REPO_ROOT)
    assert manifest_path == directory / distribution.MANIFEST_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["wheel"] == WHEEL_NAME
    assert payload["sdist"] == SDIST_NAME
    assert payload["hashes"] == {WHEEL_NAME: _sha256(wheel), SDIST_NAME: _sha256(sdist)}

    artifacts = distribution.load_artifacts(directory)
    assert artifacts == distribution.DistributionArtifacts(
        directory=directory,
        wheel=wheel,
        sdist=sdist,
        source_sha=payload["source_sha"],
        package_version=payload["package_version"],
        input_sha256=payload["input_sha256"],
        hashes={WHEEL_NAME: _sha256(wheel), SDIST_NAME: _sha256(sdist)},
    )

    pyproject = REPO_ROOT / "pyproject.toml"
    expected_version = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert artifacts.package_version == expected_version
    assert artifacts.input_sha256 == _sha256(pyproject)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    assert artifacts.source_sha == head.stdout.strip()


def test_load_artifacts_requires_manifest(tmp_path: Path) -> None:
    directory = tmp_path / "artifacts"
    _make_artifacts(directory)
    with pytest.raises(distribution.DistributionArtifactsError) as excinfo:
        distribution.load_artifacts(directory)
    message = str(excinfo.value)
    assert distribution.MANIFEST_NAME in message
    assert str(directory) in message


def test_load_artifacts_requires_wheel_file(tmp_path: Path) -> None:
    directory = tmp_path / "artifacts"
    wheel, _sdist = _make_artifacts(directory)
    distribution.write_manifest(directory, REPO_ROOT)
    wheel.unlink()
    with pytest.raises(distribution.DistributionArtifactsError) as excinfo:
        distribution.load_artifacts(directory)
    message = str(excinfo.value)
    assert WHEEL_NAME in message
    assert str(directory) in message


def test_load_artifacts_requires_sdist_file(tmp_path: Path) -> None:
    directory = tmp_path / "artifacts"
    _wheel, sdist = _make_artifacts(directory)
    distribution.write_manifest(directory, REPO_ROOT)
    sdist.unlink()
    with pytest.raises(distribution.DistributionArtifactsError) as excinfo:
        distribution.load_artifacts(directory)
    message = str(excinfo.value)
    assert SDIST_NAME in message
    assert str(directory) in message


def test_write_manifest_rejects_multiple_wheels(tmp_path: Path) -> None:
    directory = tmp_path / "artifacts"
    _make_artifacts(directory)
    (directory / "extra-0.0.0-py3-none-any.whl").write_bytes(b"extra\n")
    with pytest.raises(distribution.DistributionArtifactsError) as excinfo:
        distribution.write_manifest(directory, REPO_ROOT)
    message = str(excinfo.value)
    assert "*.whl" in message
    assert str(directory) in message


def test_write_manifest_rejects_missing_sdist(tmp_path: Path) -> None:
    directory = tmp_path / "artifacts"
    directory.mkdir()
    (directory / WHEEL_NAME).write_bytes(_FAKE_WHEEL)
    with pytest.raises(distribution.DistributionArtifactsError) as excinfo:
        distribution.write_manifest(directory, REPO_ROOT)
    assert str(directory) in str(excinfo.value)


def test_load_artifacts_rejects_hash_mismatch(tmp_path: Path) -> None:
    directory = tmp_path / "artifacts"
    wheel, _sdist = _make_artifacts(directory)
    distribution.write_manifest(directory, REPO_ROOT)
    wheel.write_bytes(b"tampered payload\n")
    with pytest.raises(distribution.DistributionArtifactsError) as excinfo:
        distribution.load_artifacts(directory)
    assert WHEEL_NAME in str(excinfo.value)


def test_load_artifacts_rejects_corrupt_manifest(tmp_path: Path) -> None:
    directory = tmp_path / "artifacts"
    _make_artifacts(directory)
    (directory / distribution.MANIFEST_NAME).write_text("not json\n", encoding="utf-8")
    with pytest.raises(distribution.DistributionArtifactsError) as excinfo:
        distribution.load_artifacts(directory)
    assert distribution.MANIFEST_NAME in str(excinfo.value)


def test_load_artifacts_rejects_unsupported_manifest_version(tmp_path: Path) -> None:
    directory = _prebuilt_dir(tmp_path)
    _rewrite_manifest(directory, version=999)

    with pytest.raises(distribution.DistributionArtifactsError) as excinfo:
        distribution.load_artifacts(directory)

    assert "version" in str(excinfo.value)


@pytest.mark.parametrize("field", ["source_sha", "package_version", "input_sha256"])
def test_load_artifacts_requires_provenance_field(tmp_path: Path, field: str) -> None:
    directory = _prebuilt_dir(tmp_path)
    _rewrite_manifest(directory, remove=field)

    with pytest.raises(distribution.DistributionArtifactsError) as excinfo:
        distribution.load_artifacts(directory)

    assert field in str(excinfo.value)


@pytest.mark.parametrize(
    ("field", "stale_value"),
    [
        ("source_sha", "0" * 40),
        ("package_version", "9.9.9"),
        ("input_sha256", "f" * 64),
    ],
)
def test_load_artifacts_rejects_stale_provenance(tmp_path: Path, field: str, stale_value: str) -> None:
    directory = _prebuilt_dir(tmp_path)
    _rewrite_manifest(directory, **{field: stale_value})

    with pytest.raises(distribution.DistributionArtifactsError) as excinfo:
        distribution.load_artifacts(directory)

    assert field in str(excinfo.value)


def test_build_artifacts_invokes_uv_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "stubbin"
    _write_uv_stub(bin_dir, _UV_BUILD_STUB)
    log = tmp_path / "uv-calls.log"
    monkeypatch.setenv("PATH", _stub_path_env(bin_dir))
    monkeypatch.setenv("FAKE_UV_LOG", str(log))

    out_dir = tmp_path / "built"
    artifacts = distribution.build_artifacts(out_dir, REPO_ROOT)

    assert log.read_text(encoding="utf-8").splitlines() == [f"build --out-dir {out_dir} --clear"]
    assert artifacts.wheel == out_dir / WHEEL_NAME
    assert artifacts.sdist == out_dir / SDIST_NAME
    assert artifacts.wheel.read_bytes() == _FAKE_WHEEL
    assert (out_dir / distribution.MANIFEST_NAME).is_file()


def test_build_artifacts_uv_failure_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "stubbin"
    _write_uv_stub(bin_dir, _UV_FAIL_STUB)
    monkeypatch.setenv("PATH", _stub_path_env(bin_dir))
    monkeypatch.setenv("FAKE_UV_LOG", str(tmp_path / "uv-calls.log"))

    with pytest.raises(distribution.DistributionArtifactsError) as excinfo:
        distribution.build_artifacts(tmp_path / "built", REPO_ROOT)
    message = str(excinfo.value)
    assert "stdout marker" in message
    assert "stderr marker" in message


def test_distribution_marker_selects_fixture_users(tmp_path: Path) -> None:
    module = _write_module(tmp_path, "test_marker_module.py", _MARKER_MODULE)
    completed = _run_pytest(
        ["--collect-only", "-q", "-m", "distribution", str(module)],
        cwd=tmp_path,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert _collected_names(completed) == ["test_param[1]", "test_param[2]", "test_x"]


def test_not_distribution_marker_selects_other_items(tmp_path: Path) -> None:
    module = _write_module(tmp_path, "test_marker_module.py", _MARKER_MODULE)
    completed = _run_pytest(
        ["--collect-only", "-q", "-m", "not distribution", str(module)],
        cwd=tmp_path,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert _collected_names(completed) == ["test_y"]


def test_fixture_users_get_xdist_group_mark(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    _write_module(plugin_dir, "_marks_dump.py", _MARKS_DUMP_PLUGIN)
    dump = tmp_path / "marks.json"
    module = _write_module(tmp_path, "test_marker_module.py", _MARKER_MODULE)
    completed = _run_pytest(
        ["--collect-only", "-q", "-p", "_marks_dump", str(module)],
        cwd=tmp_path,
        env_extra={"MARKS_DUMP": str(dump)},
        extra_pythonpath=[plugin_dir],
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    marks = json.loads(dump.read_text(encoding="utf-8"))
    assert marks, "no items collected"
    for nodeid, names in marks.items():
        short = nodeid.rsplit("::", 1)[-1]
        if short.startswith("test_y"):
            assert "distribution" not in names
            assert "xdist_group" not in names
        else:
            assert "distribution" in names
            assert "xdist_group" in names


def _prebuilt_dir(base: Path, name: str = "prebuilt") -> Path:
    directory = base / name
    _make_artifacts(directory)
    distribution.write_manifest(directory, REPO_ROOT)
    return directory


def test_option_dir_loads_without_build(tmp_path: Path) -> None:
    artifacts_dir = _prebuilt_dir(tmp_path)
    module = _write_module(tmp_path, "test_uses_artifacts.py", _USES_ARTIFACTS_MODULE)
    bin_dir = tmp_path / "stubbin"
    _write_uv_stub(bin_dir, _UV_FAIL_STUB)
    log = tmp_path / "uv-calls.log"
    completed = _run_pytest(
        ["-q", "--distribution-artifacts-dir", str(artifacts_dir), str(module)],
        cwd=tmp_path,
        env_extra={"PATH": _stub_path_env(bin_dir), "FAKE_UV_LOG": str(log)},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout
    assert not log.exists(), f"uv must not run in explicit mode: {log.read_text()}"


def test_env_var_dir_loads_without_build(tmp_path: Path) -> None:
    artifacts_dir = _prebuilt_dir(tmp_path)
    module = _write_module(tmp_path, "test_uses_artifacts.py", _USES_ARTIFACTS_MODULE)
    bin_dir = tmp_path / "stubbin"
    _write_uv_stub(bin_dir, _UV_FAIL_STUB)
    log = tmp_path / "uv-calls.log"
    completed = _run_pytest(
        ["-q", str(module)],
        cwd=tmp_path,
        env_extra={
            distribution.ENV_VAR: str(artifacts_dir),
            "PATH": _stub_path_env(bin_dir),
            "FAKE_UV_LOG": str(log),
        },
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout
    assert not log.exists()


def test_option_takes_precedence_over_env_var(tmp_path: Path) -> None:
    good = _prebuilt_dir(tmp_path, name="good")
    bad = tmp_path / "bad"
    _make_artifacts(bad)  # no manifest: loading from here must fail
    module = _write_module(tmp_path, "test_uses_artifacts.py", _USES_ARTIFACTS_MODULE)
    completed = _run_pytest(
        ["-q", "--distribution-artifacts-dir", str(good), str(module)],
        cwd=tmp_path,
        env_extra={distribution.ENV_VAR: str(bad)},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout


def test_explicit_dir_missing_manifest_fails_run(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "prebuilt"
    _make_artifacts(artifacts_dir)
    module = _write_module(tmp_path, "test_uses_artifacts.py", _USES_ARTIFACTS_MODULE)
    completed = _run_pytest(
        ["-q", "--distribution-artifacts-dir", str(artifacts_dir), str(module)],
        cwd=tmp_path,
    )
    assert completed.returncode != 0, completed.stdout + completed.stderr
    output = completed.stdout + completed.stderr
    assert distribution.MANIFEST_NAME in output
    assert artifacts_dir.name in output


@pytest.mark.parametrize("entrypoint", ["option", "environment"])
def test_explicit_mode_rejects_stale_manifest(tmp_path: Path, entrypoint: str) -> None:
    artifacts_dir = _prebuilt_dir(tmp_path)
    _rewrite_manifest(artifacts_dir, source_sha="0" * 40)
    module = _write_module(tmp_path, "test_uses_artifacts.py", _USES_ARTIFACTS_MODULE)
    args = ["-q", str(module)]
    env_extra: dict[str, str] = {}
    if entrypoint == "option":
        args[1:1] = ["--distribution-artifacts-dir", str(artifacts_dir)]
    else:
        env_extra[distribution.ENV_VAR] = str(artifacts_dir)

    completed = _run_pytest(args, cwd=tmp_path, env_extra=env_extra)

    assert completed.returncode != 0, completed.stdout + completed.stderr
    assert "source_sha" in completed.stdout + completed.stderr


def test_standalone_mode_builds_per_worker(tmp_path: Path) -> None:
    bin_dir = tmp_path / "stubbin"
    _write_uv_stub(bin_dir, _UV_BUILD_STUB)
    log = tmp_path / "uv-calls.log"
    module = _write_module(tmp_path, "test_pair.py", _TWO_TEST_MODULE)
    completed = _run_pytest(
        ["-q", "-n", "2", str(module)],
        cwd=tmp_path,
        env_extra={"PATH": _stub_path_env(bin_dir), "FAKE_UV_LOG": str(log)},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "2 passed" in completed.stdout

    out_dirs: list[str] = []
    for line in log.read_text(encoding="utf-8").splitlines():
        match = re.search(r"--out-dir (\S+)", line)
        assert match is not None, line
        out_dirs.append(match.group(1))
    assert len(out_dirs) == 2, out_dirs
    assert len(set(out_dirs)) == 2, "each xdist worker must build into its own basetemp"
    for out_dir in out_dirs:
        assert "dist/" not in f"{out_dir}/", out_dir
        assert (Path(out_dir) / distribution.MANIFEST_NAME).is_file()


def test_cli_writes_manifest_for_existing_artifacts(tmp_path: Path) -> None:
    directory = tmp_path / "artifacts"
    _make_artifacts(directory)
    completed = subprocess.run(
        [sys.executable, str(PLUGIN_PATH), str(directory)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert WHEEL_NAME in completed.stdout
    assert SDIST_NAME in completed.stdout
    assert (directory / distribution.MANIFEST_NAME).is_file()


def test_cli_rejects_directory_without_artifacts(tmp_path: Path) -> None:
    directory = tmp_path / "empty"
    directory.mkdir()
    completed = subprocess.run(
        [sys.executable, str(PLUGIN_PATH), str(directory)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "exactly one" in completed.stderr
