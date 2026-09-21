"""Regression tests for the public repository's own quality entrypoint.

``scripts/ci/verify.sh`` must work standalone in this checkout: fixed ``src``/
``tests`` targets, no parent-layout branches, the public-tree guard ahead of
every profile, and the log/disk-gate/parallel invariants preserved.
"""

import ast
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERIFY_SH = ROOT / "scripts/ci/verify.sh"
TREE_CHECK_ARGV = f"run --no-sync python scripts/ci/check_public_tree.py {ROOT}"

# Options that can start pytest-xdist workers, in every spelling: `-n 4`,
# `-n4`, `-nauto`, `--numprocesses 4`, `--numprocesses=4`, `--tx 2*popen`,
# `--tx=2*popen`. A substring check for "-n " misses the other forms, which is
# how a later change could give another profile parallel execution without this
# guard noticing (issue #263).
_WORKER_COUNT_RE = re.compile(r"^-n\S*$|^--numprocesses(=.*)?$|^--tx(=.*)?$")
# `--dist loadfile`, `--dist=loadfile`, and the bare flag.
_DIST_MODE_RE = re.compile(r"^--dist(=.*)?$")


@pytest.fixture(autouse=True)
def isolate_quality_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep subprocess assertions independent of ambient overrides."""
    monkeypatch.delenv("VERIFY_BROWSER_WORKERS", raising=False)
    monkeypatch.setenv("VERIFY_MIN_FREE_MB", "0")
    monkeypatch.delenv("VERIFY_LOG_DIR", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)


def _worker_flags(argv: str) -> list[str]:
    """Worker-starting or dist-mode tokens in a recorded pytest argv string."""
    return [token for token in argv.split() if _WORKER_COUNT_RE.match(token) or _DIST_MODE_RE.match(token)]


def _fake_bin(tmp_path: Path, name: str, body: str) -> None:
    fake = tmp_path / name
    fake.write_text(f"#!/usr/bin/env bash\n{body}\n")
    fake.chmod(0o755)


def _install_noop_quality_stubs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub npm/uv/uvx as no-ops so a full profile run completes quickly."""
    for name in ("npm", "uv", "uvx"):
        _fake_bin(tmp_path, name, "exit 0")
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")


def _install_call_logging_quality_stubs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    calls_path: Path,
) -> None:
    """Stub npm/uv/uvx to record every invocation, so tests can assert none ran."""
    body = f'printf \'%s\\t%s\\n\' "$(basename "$0")" "$*" >> "{calls_path}"\n'
    for name in ("npm", "uv", "uvx"):
        _fake_bin(tmp_path, name, body)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")


def _run_quality_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
) -> list[tuple[str, str, str]]:
    """Run *profile* with call-logging stubs from an unrelated cwd.

    Returns ``(tool, cwd, argv)`` entries; asserts the script resolved and
    entered the repository root regardless of the caller's working directory.
    """
    calls = tmp_path / f"{profile}.calls"
    stub = '#!/usr/bin/env bash\nprintf \'%s\\t%s\\t%s\\n\' "$(basename "$0")" "$PWD" "$*" >> "$QUALITY_CALLS"\n'
    for name in ("npm", "uv", "uvx"):
        fake = tmp_path / name
        fake.write_text(stub)
        fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setenv("QUALITY_CALLS", str(calls))
    # Keep verify.sh's own log output out of the real /tmp during tests (issue #150).
    monkeypatch.setenv("VERIFY_LOG_DIR", str(tmp_path / "verify-logs"))

    subprocess.run([str(VERIFY_SH), profile], cwd=tmp_path, check=True)

    entries: list[tuple[str, str, str]] = []
    for line in calls.read_text().splitlines():
        tool, cwd, argv = line.split("\t", 2)
        entries.append((tool, cwd, argv))
    assert entries
    assert all(cwd == str(ROOT) for _tool, cwd, _argv in entries)
    return entries


# ---- script structure -------------------------------------------------------


def test_quality_entrypoint_is_public_only() -> None:
    """The entrypoint must carry no parent-layout branches or paths."""
    assert VERIFY_SH.is_file()
    assert VERIFY_SH.stat().st_mode & 0o111
    text = VERIFY_SH.read_text()
    assert "uv lock --check" in text
    assert "uv sync --locked --all-groups" in text
    assert "uv build --out-dir dist --clear" in text
    # Issue #318: one build, one manifest record, one `-m distribution` pytest
    # run reusing those artifacts; twine moved inside that suite
    # (test_twine_check_strict_passes), so no shell `uvx twine` step remains.
    assert "uvx twine check --strict dist/*" not in text
    assert "-m distribution" in text
    assert "--distribution-artifacts-dir" in text
    assert "tests/fixtures/distribution.py" in text
    assert re.search(r"(?m)^    uv build$", text) is None
    # The public tree guard runs ahead of dependency setup in every profile.
    assert "scripts/ci/check_public_tree.py" in text
    tree_check_line = next(
        line for line in text.splitlines() if line.strip().startswith("uv run --no-sync python scripts/ci/")
    )
    assert text.index(tree_check_line) < text.index("uv lock --check")
    # No parent-layout branch may survive: no target_set, no ci-shared, no
    # parent-only directories in any conditional or tool invocation.
    for forbidden in ("target_set", "ci-shared", "tools/public_sync", ".agents", "tools/"):
        assert forbidden not in text, f"verify.sh still references {forbidden!r}"


def test_distribution_plugin_is_loaded_from_tests_dir() -> None:
    """Issue #318: `-p fixtures.distribution` resolves via tests/ pythonpath."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pytest_options = data["tool"]["pytest"]["ini_options"]
    assert "-p fixtures.distribution" in pytest_options["addopts"]
    assert "tests" in pytest_options["pythonpath"]
    assert (ROOT / "tests" / "fixtures" / "distribution.py").is_file()


def test_pyproject_references_only_public_present_paths() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pytest_options = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    referenced = [*pytest_options.get("testpaths", []), *pytest_options.get("pythonpath", [])]
    referenced.extend(data.get("tool", {}).get("pyright", {}).get("include", []))
    for relative in referenced:
        assert (ROOT / relative).is_dir(), f"pyproject.toml references a missing path: {relative}"


@pytest.mark.parametrize("extra", ["local", "ci-shared", "anything"])
def test_second_argument_is_rejected_with_64(tmp_path: Path, extra: str) -> None:
    """The old target_set argument must not be silently accepted."""
    result = subprocess.run(
        [str(VERIFY_SH), "full", extra],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 64
    assert "unexpected extra argument" in result.stderr


def test_missing_src_or_tests_rejected_with_64(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    checkout = tmp_path / "partial-checkout"
    script = checkout / "scripts/ci/verify.sh"
    script.parent.mkdir(parents=True)
    script.write_text(VERIFY_SH.read_text())
    script.chmod(0o755)
    (checkout / "tests").mkdir()
    _install_df_stub(tmp_path, avail_kb=1)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

    result = subprocess.run(
        [str(script), "minimum"],
        cwd=checkout,
        capture_output=True,
        text=True,
        env={**os.environ, "VERIFY_LOG_DIR": str(tmp_path / "verify-logs")},
    )

    assert result.returncode == 64
    assert "missing required verification target: src" in result.stdout


def test_parent_only_directories_never_join_the_target_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even when parent-only dirs physically exist, targets stay src + tests."""
    checkout = tmp_path / "checkout"
    script = checkout / "scripts/ci/verify.sh"
    script.parent.mkdir(parents=True)
    script.write_text(VERIFY_SH.read_text())
    script.chmod(0o755)
    for relative in ("src", "tests", "tools/public_sync/tests", ".agents"):
        (checkout / relative).mkdir(parents=True)
    calls = tmp_path / "full.calls"
    _install_call_logging_quality_stubs(tmp_path, monkeypatch, calls)
    monkeypatch.setenv("VERIFY_LOG_DIR", str(tmp_path / "verify-logs"))

    subprocess.run([str(script), "full"], cwd=tmp_path, check=True)

    logged = [tuple(line.split("\t", 1)) for line in calls.read_text().splitlines()]
    # The script records its resolved root (`cd ... && pwd`), not the caller's
    # possibly-symlinked spelling of it.
    assert ("uv", f"run --no-sync python scripts/ci/check_public_tree.py {checkout.resolve()}") in logged
    for _tool, argv in logged:
        tokens = argv.split()
        assert not any(
            token == "tools" or token.startswith("tools/") or token == ".agents" or token.startswith(".agents/")
            for token in tokens
        ), argv
    ruff_argv = [argv for tool, argv in logged if tool == "uv" and "ruff check" in argv]
    assert ruff_argv == ["run --no-sync ruff check src tests"]
    # tmp_path lives under a "pytest-*" directory, so match the command token,
    # not the bare substring.
    pytest_argv = [argv for tool, argv in logged if tool == "uv" and argv.startswith("run --no-sync pytest ")]
    assert pytest_argv
    assert all(argv.endswith(" -v tests") for argv in pytest_argv)


def test_tree_check_failure_stops_before_dependency_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A contaminated tree must abort every profile before lock/sync/pytest."""
    calls_path = tmp_path / "full.calls"
    log_call = f'printf \'%s\\t%s\\n\' "$(basename "$0")" "$*" >> "{calls_path}"\n'
    uv_body = log_call + 'if [[ "$*" == *"check_public_tree"* ]]; then\n  exit 1\nfi\nexit 0\n'
    _fake_bin(tmp_path, "uv", uv_body)
    _fake_bin(tmp_path, "npm", log_call + "exit 0\n")
    _fake_bin(tmp_path, "uvx", log_call + "exit 0\n")
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setenv("VERIFY_LOG_DIR", str(tmp_path / "verify-logs"))

    result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode == 1
    calls = [tuple(line.split("\t", 1)) for line in calls_path.read_text().splitlines()]
    assert calls == [("uv", TREE_CHECK_ARGV)]


@pytest.mark.parametrize("profile", ["full", "static", "quick", "minimum", "latest"])
def test_every_profile_runs_tree_check_before_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
) -> None:
    entries = _run_quality_profile(tmp_path, monkeypatch, profile)
    calls = [(tool, argv) for tool, _cwd, argv in entries]
    assert calls[0] == ("uv", TREE_CHECK_ARGV)
    assert calls[1] == ("uv", "lock --check")
    assert calls[2] == ("uv", "sync --locked --all-groups")


# ---- logging (issue #150) ----------------------------------------------------

VERIFY_LOG_NAME_RE = re.compile(r"^verify-(?P<profile>[a-z0-9_-]+)-(?P<timestamp>\d{8}T\d{6}Z)-(?P<pid>\d+)\.log$")


def test_verify_log_is_created_with_header_and_exit_code_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "verify-logs"
    monkeypatch.setenv("VERIFY_LOG_DIR", str(log_dir))
    _install_noop_quality_stubs(tmp_path, monkeypatch)

    result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0

    logs = sorted(log_dir.glob("verify-*.log"))
    assert len(logs) == 1
    match = VERIFY_LOG_NAME_RE.match(logs[0].name)
    assert match is not None
    assert match.group("profile") == "full"

    content = logs[0].read_text()
    assert f"verify.sh log: {logs[0]}" in content
    assert "profile: full" in content
    assert re.search(r"(?m)^start \(UTC\): \d{8}T\d{6}Z$", content)
    assert re.search(r"(?m)^HEAD: [0-9a-f]{40}$|^HEAD: unknown$", content)
    assert f"workdir: {ROOT}" in content
    assert content.rstrip("\n").splitlines()[-1] == "EXIT=0"


def test_verify_log_records_failure_exit_code_without_swallowing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "verify-logs"
    monkeypatch.setenv("VERIFY_LOG_DIR", str(log_dir))
    _fake_bin(tmp_path, "npm", "exit 3")
    _fake_bin(tmp_path, "uv", "exit 0")
    _fake_bin(tmp_path, "uvx", "exit 0")
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

    result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, capture_output=True, text=True)

    # The real command's exit code (npm ci failing) must reach the caller
    # unchanged; tee/process-substitution must not turn this into 0 or an
    # unrelated code.
    assert result.returncode == 3

    logs = list(log_dir.glob("verify-*.log"))
    assert len(logs) == 1
    assert logs[0].read_text().rstrip("\n").splitlines()[-1] == "EXIT=3"


def test_unknown_profile_exit_code_is_preserved_and_logged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "verify-logs"
    monkeypatch.setenv("VERIFY_LOG_DIR", str(log_dir))
    _install_noop_quality_stubs(tmp_path, monkeypatch)

    result = subprocess.run(
        [str(VERIFY_SH), "bogus-profile"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 64
    logs = list(log_dir.glob("verify-bogus-profile-*.log"))
    assert len(logs) == 1
    assert logs[0].read_text().rstrip("\n").splitlines()[-1] == "EXIT=64"


def test_unknown_profile_with_slash_still_leaves_one_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "verify-logs"
    monkeypatch.setenv("VERIFY_LOG_DIR", str(log_dir))
    _install_noop_quality_stubs(tmp_path, monkeypatch)

    result = subprocess.run([str(VERIFY_SH), "a/b"], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode == 64
    logs = list(log_dir.glob("verify-*.log"))
    assert len(logs) == 1
    assert "/" not in logs[0].name
    match = VERIFY_LOG_NAME_RE.match(logs[0].name)
    assert match is not None
    assert match.group("profile") == "a-b"
    content = logs[0].read_text()
    assert "profile: a/b" in content
    assert content.rstrip("\n").splitlines()[-1] == "EXIT=64"


def test_concurrent_runs_do_not_collide_on_log_filenames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "verify-logs"
    monkeypatch.setenv("VERIFY_LOG_DIR", str(log_dir))
    _install_noop_quality_stubs(tmp_path, monkeypatch)

    procs = [
        subprocess.Popen(
            [str(VERIFY_SH), "full"],
            cwd=tmp_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(2)
    ]
    codes = [proc.wait(timeout=30) for proc in procs]
    assert codes == [0, 0]

    logs = sorted(log_dir.glob("verify-full-*.log"))
    assert len(logs) == 2
    assert logs[0].name != logs[1].name


def test_verify_log_default_dir_uses_tmpdir_maatlog_subdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_tmpdir = tmp_path / "fake-tmp"
    fake_tmpdir.mkdir()
    monkeypatch.setenv("TMPDIR", str(fake_tmpdir))
    _install_noop_quality_stubs(tmp_path, monkeypatch)

    result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0

    expected_dir = fake_tmpdir / "maatlog-verify-logs"
    logs = list(expected_dir.glob("verify-full-*.log"))
    assert len(logs) == 1


def test_verify_log_dir_falls_back_when_unwritable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked_parent = tmp_path / "blocked"
    blocked_parent.mkdir(mode=0o500)
    bad_log_dir = blocked_parent / "verify-logs"
    fallback_tmpdir = tmp_path / "fallback-tmp"
    fallback_tmpdir.mkdir()
    monkeypatch.setenv("VERIFY_LOG_DIR", str(bad_log_dir))
    monkeypatch.setenv("TMPDIR", str(fallback_tmpdir))
    _install_noop_quality_stubs(tmp_path, monkeypatch)

    try:
        result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, capture_output=True, text=True)
        assert result.returncode == 0
        assert not bad_log_dir.exists()
        logs = list(fallback_tmpdir.glob("verify-full-*.log"))
        assert len(logs) == 1
    finally:
        blocked_parent.chmod(0o700)


def test_log_rotation_keeps_recent_generations_and_skips_alive_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "verify-logs"
    log_dir.mkdir()
    monkeypatch.setenv("VERIFY_LOG_DIR", str(log_dir))
    _install_noop_quality_stubs(tmp_path, monkeypatch)

    # 12 pre-existing dead-pid logs (oldest first); rotation keeps at most 10.
    dead_pid = 999_999_999
    old_logs: list[Path] = []
    for index in range(12):
        name = f"verify-full-2020010{1 if index < 10 else 2}T00{index:02d}00Z-{dead_pid}.log"
        path = log_dir / name
        path.write_text("stale\n")
        old_logs.append(path)
        mtime = 1_577_836_800 + index  # deterministic, strictly increasing
        os.utime(path, (mtime, mtime))

    # One old-looking log whose pid is still alive (this test process itself);
    # rotation must never delete it even though it is otherwise old enough.
    alive_pid = os.getpid()
    alive_log = log_dir / f"verify-full-20200101T000000Z-{alive_pid}.log"
    alive_log.write_text("still running\n")
    os.utime(alive_log, (1_577_836_700, 1_577_836_700))

    result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0

    remaining = {path.name for path in log_dir.glob("verify-*.log")}
    assert alive_log.name in remaining, "a log whose pid is still alive must never be rotated away"
    new_logs = remaining - {path.name for path in old_logs} - {alive_log.name}
    assert len(new_logs) == 1, "verify.sh must not delete its own just-created log"
    surviving_old = remaining & {path.name for path in old_logs}
    assert len(surviving_old) <= 10


def test_verify_log_dir_write_failure_exits_66_with_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_noop_quality_stubs(tmp_path, monkeypatch)
    # Force every candidate log directory (VERIFY_LOG_DIR, TMPDIR, /tmp) to be
    # unwritable by making mkdir always fail, regardless of the host's real /tmp
    # permissions.
    _fake_bin(tmp_path, "mkdir", "exit 1")
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setenv("VERIFY_LOG_DIR", str(tmp_path / "unwritable-logs"))

    result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode == 66
    assert "VERIFY_LOG_DIR" in result.stderr


# ---- profile behaviour -------------------------------------------------------


def test_full_profile_runs_fail_fast_order_before_pytest_and_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cheap checks run (and fail) before the pytest suites and the build.

    The tree guard and lock/sync setup come first, then the static checks
    (issue #148), then `npm ci` must still precede pytest
    (tests/acceptance/test_accessibility.py needs the installed axe-core
    browser fixture). The distribution-marked tests run once, in a dedicated
    pytest call that reuses the archives built by the profile's single
    `uv build` (issue #318); `tests/fixtures/distribution.py` records the
    manifest those tests verify against. The non-distribution run is split
    into sequential nonbrowser and browser phases (issue #320).
    """
    entries = _run_quality_profile(tmp_path, monkeypatch, "full")
    calls = [(tool, argv) for tool, _cwd, argv in entries]
    assert ("npm", "ci") in calls
    assert ("npm", "run check") in calls

    tree_check = calls.index(("uv", TREE_CHECK_ARGV))
    lock = calls.index(("uv", "lock --check"))
    sync = calls.index(("uv", "sync --locked --all-groups"))
    ruff_check = calls.index(("uv", "run --no-sync ruff check src tests"))
    ruff_format = calls.index(("uv", "run --no-sync ruff format --check src tests"))
    pyright = calls.index(("uv", "run --no-sync pyright src tests"))
    npm_ci = calls.index(("npm", "ci"))
    frontend = calls.index(("npm", "run check"))

    # Exactly three pytest invocations: parallel browser-less tests, bounded
    # browser tests, then the serial distribution gate against the archives.
    pytest_argv = [argv for tool, argv in calls if tool == "uv" and argv.startswith("run --no-sync pytest ")]
    assert pytest_argv == [
        "run --no-sync pytest -n auto --dist loadgroup -m not browser and not distribution -v tests",
        "run --no-sync pytest -n 2 --dist loadscope -m browser and not distribution -v tests",
        f"run --no-sync pytest -m distribution --distribution-artifacts-dir {ROOT}/dist -v tests",
    ]
    nonbrowser = calls.index(("uv", pytest_argv[0]))
    browser = calls.index(("uv", pytest_argv[1]))
    distribution = calls.index(("uv", pytest_argv[2]))
    build = calls.index(("uv", "build --out-dir dist --clear"))
    manifest = calls.index(("uv", "run --no-sync python tests/fixtures/distribution.py dist"))

    assert tree_check < lock < sync
    assert ruff_check < ruff_format < pyright < npm_ci < frontend
    assert sync < ruff_check
    assert frontend < nonbrowser < browser < build < manifest < distribution
    assert sum(1 for tool, argv in calls if tool == "uv" and argv.startswith("build")) == 1
    assert not [argv for tool, argv in calls if tool == "uvx"], "twine runs inside the distribution pytest suite"
    assert not any("twine" in argv for _tool, argv in calls)


@pytest.mark.parametrize("workers", ["", "0", "-1", "2.5", "auto", "5"])
def test_full_profile_rejects_invalid_browser_worker_count_before_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workers: str,
) -> None:
    calls_path = tmp_path / "full.calls"
    _install_call_logging_quality_stubs(tmp_path, monkeypatch, calls_path)
    monkeypatch.setenv("VERIFY_BROWSER_WORKERS", workers)
    monkeypatch.setenv("VERIFY_LOG_DIR", str(tmp_path / "verify-logs"))
    monkeypatch.setenv("VERIFY_MIN_FREE_MB", "0")

    result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode == 65
    assert "VERIFY_BROWSER_WORKERS must be an integer from 1 to 4" in result.stdout
    assert not calls_path.exists(), "invalid worker settings must fail before dependency setup"


@pytest.mark.parametrize("workers", ["1", "3", "4", "0002"])
def test_full_profile_uses_valid_browser_worker_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workers: str,
) -> None:
    monkeypatch.setenv("VERIFY_BROWSER_WORKERS", workers)

    entries = _run_quality_profile(tmp_path, monkeypatch, "full")

    pytest_argv = [argv for tool, _cwd, argv in entries if tool == "uv" and argv.startswith("run --no-sync pytest ")]
    expected = str(int(workers))
    assert [argv for argv in pytest_argv if "-m browser and not distribution" in argv] == [
        f"run --no-sync pytest -n {expected} --dist loadscope -m browser and not distribution -v tests"
    ]


def test_full_profile_reports_browser_parallel_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_noop_quality_stubs(tmp_path, monkeypatch)
    monkeypatch.setenv("VERIFY_BROWSER_WORKERS", "3")
    monkeypatch.setenv("VERIFY_LOG_DIR", str(tmp_path / "verify-logs"))
    monkeypatch.setenv("VERIFY_MIN_FREE_MB", "0")

    result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, check=True, capture_output=True, text=True)

    assert "browser workers: 3" in result.stdout
    assert "browser distribution: loadscope" in result.stdout


def _run_profile_with_failing_uv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    *,
    fail_pattern: str,
    fail_code: int,
) -> tuple[subprocess.CompletedProcess[str], list[tuple[str, str]]]:
    """Run *profile* with logging stubs; `uv` exits `fail_code` when its argv
    contains `fail_pattern`. Returns the completed process and the calls log."""
    calls_path = tmp_path / f"{profile}.calls"
    monkeypatch.setenv("VERIFY_LOG_DIR", str(tmp_path / "verify-logs"))
    log_call = f'printf \'%s\\t%s\\n\' "$(basename "$0")" "$*" >> "{calls_path}"\n'
    uv_body = log_call + f'if [[ "$*" == *"{fail_pattern}"* ]]; then\n  exit {fail_code}\nfi\nexit 0\n'
    _fake_bin(tmp_path, "uv", uv_body)
    _fake_bin(tmp_path, "npm", log_call + "exit 0\n")
    _fake_bin(tmp_path, "uvx", log_call + "exit 0\n")
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

    result = subprocess.run([str(VERIFY_SH), profile], cwd=tmp_path, capture_output=True, text=True)
    calls: list[tuple[str, str]] = []
    for line in calls_path.read_text().splitlines():
        tool, argv = line.split("\t", 1)
        calls.append((tool, argv))
    return result, calls


def test_full_profile_fail_fast_stops_before_pytest_on_static_lint_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #148 acceptance: a broken static lint must abort before pytest
    (and before npm ci) ever runs, and the failure must still be captured in
    the verify.sh log (issue #150) with the real exit code preserved."""
    log_dir = tmp_path / "verify-logs"
    result, calls = _run_profile_with_failing_uv(tmp_path, monkeypatch, "full", fail_pattern="ruff check", fail_code=1)

    assert result.returncode == 1
    assert ("uv", "run --no-sync ruff check src tests") in calls
    assert not any(tool == "uv" and argv.startswith("run --no-sync pytest ") for tool, argv in calls)
    assert not any(tool == "npm" for tool, _argv in calls), "npm ci must not run once the lint step has failed"

    logs = list(log_dir.glob("verify-full-*.log"))
    assert len(logs) == 1
    assert logs[0].read_text().rstrip("\n").splitlines()[-1] == "EXIT=1"


def test_full_profile_stops_before_distribution_run_when_uv_build_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #318: `set -e` must abort `full` between `uv build` and the
    distribution pytest run — the manifest step and the gated suite must not
    run against a missing or half-written dist/."""
    result, calls = _run_profile_with_failing_uv(
        tmp_path, monkeypatch, "full", fail_pattern="build --out-dir dist --clear", fail_code=5
    )

    assert result.returncode == 5
    assert ("uv", "build --out-dir dist --clear") in calls
    assert not any("tests/fixtures/distribution.py" in argv for _tool, argv in calls)
    assert not any("pytest -m distribution" in argv for _tool, argv in calls)


def test_full_profile_stops_before_browser_when_nonbrowser_pytest_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, calls = _run_profile_with_failing_uv(
        tmp_path,
        monkeypatch,
        "full",
        fail_pattern="-m not browser and not distribution",
        fail_code=8,
    )

    assert result.returncode == 8
    assert any("-m not browser and not distribution" in argv for _tool, argv in calls)
    assert not any("-m browser and not distribution" in argv for _tool, argv in calls)
    assert not any(argv.startswith("build") for _tool, argv in calls)


def test_full_profile_stops_before_distribution_build_when_browser_pytest_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, calls = _run_profile_with_failing_uv(
        tmp_path,
        monkeypatch,
        "full",
        fail_pattern="-m browser and not distribution",
        fail_code=9,
    )

    assert result.returncode == 9
    assert any("-m browser and not distribution" in argv for _tool, argv in calls)
    assert not any(argv.startswith("build") for _tool, argv in calls)
    assert not any("pytest -m distribution" in argv for _tool, argv in calls)


def test_full_profile_stops_before_distribution_run_when_manifest_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #318: a failing manifest record must abort before the distribution
    suite too — that suite verifies the archives against the manifest."""
    result, calls = _run_profile_with_failing_uv(
        tmp_path,
        monkeypatch,
        "full",
        fail_pattern="run --no-sync python tests/fixtures/distribution.py dist",
        fail_code=6,
    )

    assert result.returncode == 6
    assert ("uv", "run --no-sync python tests/fixtures/distribution.py dist") in calls
    assert not any("pytest -m distribution" in argv for _tool, argv in calls)


def test_full_profile_propagates_distribution_pytest_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #318: the `-m distribution` gate failing must fail the profile."""
    result, calls = _run_profile_with_failing_uv(
        tmp_path, monkeypatch, "full", fail_pattern="pytest -m distribution", fail_code=7
    )

    assert result.returncode == 7
    assert (
        "uv",
        f"run --no-sync pytest -m distribution --distribution-artifacts-dir {ROOT}/dist -v tests",
    ) in calls


def _uv_pip_install_calls(calls: list[tuple[str, str]]) -> list[str]:
    """Return every `uv pip install ...` argv, so venv-mutating calls are visible.

    `static` and `quick` (issue #260) must never appear here: they exist to be
    repeatable during development, which only holds while the venv is untouched.
    """
    return [argv for tool, argv in calls if tool == "uv" and argv.startswith("pip install")]


def test_static_profile_runs_static_checks_in_fail_fast_order_without_venv_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #260: `static` is `full`'s static checks and nothing else."""
    entries = _run_quality_profile(tmp_path, monkeypatch, "static")
    calls = [(tool, argv) for tool, _cwd, argv in entries]

    ruff_check = calls.index(("uv", "run --no-sync ruff check src tests"))
    ruff_format = calls.index(("uv", "run --no-sync ruff format --check src tests"))
    pyright = calls.index(("uv", "run --no-sync pyright src tests"))
    npm_ci = calls.index(("npm", "ci"))
    frontend = calls.index(("npm", "run check"))

    assert ruff_check < ruff_format < pyright < npm_ci < frontend
    assert not any(argv.startswith("run --no-sync pytest ") for _tool, argv in calls)
    assert not [argv for tool, argv in calls if tool == "uvx"]
    assert _uv_pip_install_calls(calls) == []
    # The distribution build belongs to `full` only (it rewrites dist/ each run).
    assert not any(argv.startswith("build ") for _tool, argv in calls)


def test_quick_profile_adds_browser_less_pytest_after_static_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #260: `quick` is a Python-only static pass plus one browser-less
    pytest run — since issue #360 the distribution-marked tests share that run
    instead of a serial follow-up, pinned to one worker by xdist_group."""
    entries = _run_quality_profile(tmp_path, monkeypatch, "quick")
    calls = [(tool, argv) for tool, _cwd, argv in entries]

    ruff_check = calls.index(("uv", "run --no-sync ruff check src tests"))
    ruff_format = calls.index(("uv", "run --no-sync ruff format --check src tests"))
    pyright = calls.index(("uv", "run --no-sync pyright src tests"))
    pytest_calls = [
        index for index, (tool, argv) in enumerate(calls) if tool == "uv" and argv.startswith("run --no-sync pytest ")
    ]

    assert len(pytest_calls) == 1
    (parallel_call,) = pytest_calls
    assert calls[parallel_call] == (
        "uv",
        "run --no-sync pytest -n auto --dist loadgroup -m not browser -v tests",
    )
    assert ruff_check < ruff_format < pyright < parallel_call
    assert not any(tool == "npm" for tool, _argv in calls)
    assert not [argv for tool, argv in calls if tool == "uvx"]
    assert _uv_pip_install_calls(calls) == []
    assert not any(argv.startswith("build ") for _tool, argv in calls)


def test_quick_profile_fail_fast_stops_before_pytest_on_static_lint_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #260 acceptance: `quick` inherits `full`'s fail-fast property."""
    log_dir = tmp_path / "verify-logs"
    result, calls = _run_profile_with_failing_uv(
        tmp_path, monkeypatch, "quick", fail_pattern="ruff check", fail_code=1
    )

    assert result.returncode == 1
    assert ("uv", "run --no-sync ruff check src tests") in calls
    assert not any(tool == "uv" and argv.startswith("run --no-sync pytest ") for tool, argv in calls)
    assert not any(tool == "npm" for tool, _argv in calls), "npm ci must not run once the lint step has failed"

    logs = list(log_dir.glob("verify-quick-*.log"))
    assert len(logs) == 1
    assert logs[0].read_text().rstrip("\n").splitlines()[-1] == "EXIT=1"


SETUP_CALLS = [
    ("uv", TREE_CHECK_ARGV),
    ("uv", "lock --check"),
    ("uv", "sync --locked --all-groups"),
]

PYTHON_STATIC_CHECK_CALLS = (
    ("uv", "run --no-sync ruff check src tests"),
    ("uv", "run --no-sync ruff format --check src tests"),
    ("uv", "run --no-sync pyright src tests"),
)

STATIC_CHECK_CALLS = (
    *PYTHON_STATIC_CHECK_CALLS,
    ("npm", "ci"),
    ("npm", "run check"),
)


def _calls_through_static_checks(
    entries: list[tuple[str, str, str]],
    *,
    frontend: bool = True,
) -> list[tuple[str, str]]:
    """Return every call up to and including the last static check.

    The static checks are contiguous; `full` and `static` end them with
    `npm run check`, `quick` (issue #360) ends them with pyright.
    """
    calls = [(tool, argv) for tool, _cwd, argv in entries]
    last = ("npm", "run check") if frontend else PYTHON_STATIC_CHECK_CALLS[-1]
    return calls[: calls.index(last) + 1]


def test_static_checks_are_identical_across_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #264: the static checks have a single definition in verify.sh.

    `full` and `static` issue the same calls in the same order; `quick`
    (issue #360) runs only their Python prefix — the npm pair guards frontend
    tooling whose covered paths all select `full`.
    """
    expected_frontend = [*SETUP_CALLS, *STATIC_CHECK_CALLS]
    expected_python = [*SETUP_CALLS, *PYTHON_STATIC_CHECK_CALLS]
    observed: dict[str, list[tuple[str, str]]] = {}
    for profile in ("full", "static", "quick"):
        profile_dir = tmp_path / profile
        profile_dir.mkdir()
        observed[profile] = _calls_through_static_checks(
            _run_quality_profile(profile_dir, monkeypatch, profile),
            frontend=profile != "quick",
        )

    assert observed["full"] == expected_frontend
    assert observed["static"] == expected_frontend
    assert observed["quick"] == expected_python


@pytest.mark.parametrize("profile", ["minimum", "latest"])
def test_compatibility_profiles_skip_browser_and_node_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
) -> None:
    entries = _run_quality_profile(tmp_path, monkeypatch, profile)
    calls = [(tool, argv) for tool, _cwd, argv in entries]
    assert all(tool != "npm" for tool, _argv in calls)
    pytest_calls = [argv for tool, argv in calls if tool == "uv" and argv.startswith("run --no-sync pytest ")]
    assert pytest_calls == ["run --no-sync pytest -m not browser -v tests"]


@pytest.mark.parametrize(
    ("profile", "install_argv"),
    [
        ("minimum", "pip install Sphinx==9.1.0 myst-parser==5.1.0"),
        ("latest", "pip install --upgrade Sphinx myst-parser"),
    ],
)
def test_compatibility_profiles_install_their_dependency_pins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    install_argv: str,
) -> None:
    entries = _run_quality_profile(tmp_path, monkeypatch, profile)
    calls = [(tool, argv) for tool, _cwd, argv in entries]
    assert ("uv", install_argv) in calls


# ---- issue #145: disk-space gate --------------------------------------------


def _install_df_stub(
    tmp_path: Path,
    avail_kb: int,
    source: str = "/dev/fake0",
    calls_path: Path | None = None,
    *,
    avail_kb_for_prefix: tuple[str, int] | None = None,
) -> None:
    """Stub `df` so gate tests do not depend on the host's real free space.

    Understands the invocation shape verify.sh uses: `--output=avail ...`.
    When calls_path is given, every invocation's arguments are appended to it
    (one per line) so tests can assert call counts. Paths whose last argument
    starts with `avail_kb_for_prefix[0]` report that prefix's KiB instead of
    `avail_kb`.
    """
    log_line = f'printf \'%s\\n\' "$*" >> "{calls_path}"\n' if calls_path is not None else ""
    prefix_branch = ""
    if avail_kb_for_prefix is not None:
        prefix, prefix_kb = avail_kb_for_prefix
        prefix_branch = (
            '  path="${@: -1}"\n'
            f'  if [[ "$path" == "{prefix}"* ]]; then\n'
            f"    printf '{prefix_kb}\\n'\n"
            "    exit 0\n"
            "  fi\n"
        )
    body = (
        f"{log_line}"
        'if [[ "$*" == *avail* ]]; then\n'
        "  printf 'Avail\\n'\n"
        f"{prefix_branch}"
        f"  printf '{avail_kb}\\n'\n"
        "else\n"
        "  printf 'Filesystem\\n'\n"
        f"  printf '{source}\\n'\n"
        "fi\n"
    )
    _fake_bin(tmp_path, "df", body)


def _install_stat_stub(
    tmp_path: Path,
    *,
    default_dev: str,
    prefix: str | None = None,
    prefix_dev: str | None = None,
) -> None:
    """Stub GNU `stat -c %d` so uniqueness tests do not depend on the host.

    Paths whose last argument starts with `prefix` report `prefix_dev`;
    every other path reports `default_dev`.
    """
    if prefix is None:
        body = f"printf '%s\\n' '{default_dev}'\n"
    else:
        body = (
            'path="${@: -1}"\n'
            f'if [[ "$path" == "{prefix}"* ]]; then\n'
            f"  printf '%s\\n' '{prefix_dev}'\n"
            "else\n"
            f"  printf '%s\\n' '{default_dev}'\n"
            "fi\n"
        )
    _fake_bin(tmp_path, "stat", body)


def test_disk_gate_blocks_full_profile_when_free_space_is_below_default_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VERIFY_MIN_FREE_MB")
    log_dir = tmp_path / "verify-logs"
    calls_path = tmp_path / "quality.calls"
    monkeypatch.setenv("VERIFY_LOG_DIR", str(log_dir))
    _install_call_logging_quality_stubs(tmp_path, monkeypatch, calls_path)
    # full profile requires 5120 MiB by default; report far less.
    _install_df_stub(tmp_path, avail_kb=100 * 1024)

    result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode == 65
    assert "not enough free disk space" in result.stderr
    assert "5120" in result.stderr
    # The gate must run before uv lock/sync, npm ci, and pytest.
    assert not calls_path.exists()
    # The gate runs before log setup (issue #152 spec), so a gate failure
    # leaves no verify.sh log file behind.
    assert list(log_dir.glob("verify-*.log")) == []


def test_disk_gate_min_free_env_override_can_force_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "verify-logs"
    monkeypatch.setenv("VERIFY_LOG_DIR", str(log_dir))
    monkeypatch.setenv("VERIFY_MIN_FREE_MB", "999999999")
    _install_noop_quality_stubs(tmp_path, monkeypatch)

    # No df stub: this must fail against the host's real free space too,
    # since no real machine has ~954 TiB free.
    result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode == 65
    assert "999999999" in result.stderr
    assert list(log_dir.glob("verify-*.log")) == []


def test_disk_gate_disabled_with_zero_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "verify-logs"
    monkeypatch.setenv("VERIFY_LOG_DIR", str(log_dir))
    monkeypatch.setenv("VERIFY_MIN_FREE_MB", "0")
    _install_noop_quality_stubs(tmp_path, monkeypatch)
    _install_df_stub(tmp_path, avail_kb=1)  # essentially no free space

    result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode == 0
    assert len(list(log_dir.glob("verify-full-*.log"))) == 1


@pytest.mark.parametrize(
    ("profile", "avail_mb", "expect_pass"),
    [
        ("full", 3000, False),  # below the full-profile default (5120 MiB)
        ("minimum", 3000, True),  # above the minimum/latest default (2048 MiB)
        ("latest", 3000, True),
    ],
)
def test_disk_gate_uses_profile_specific_default_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    avail_mb: int,
    expect_pass: bool,
) -> None:
    monkeypatch.delenv("VERIFY_MIN_FREE_MB")
    log_dir = tmp_path / "verify-logs"
    monkeypatch.setenv("VERIFY_LOG_DIR", str(log_dir))
    _install_noop_quality_stubs(tmp_path, monkeypatch)
    _install_df_stub(tmp_path, avail_kb=avail_mb * 1024)

    result = subprocess.run([str(VERIFY_SH), profile], cwd=tmp_path, capture_output=True, text=True)

    if expect_pass:
        assert result.returncode == 0
    else:
        assert result.returncode == 65


def test_disk_gate_checks_each_distinct_filesystem_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VERIFY_MIN_FREE_MB")
    log_dir = tmp_path / "verify-logs"
    monkeypatch.setenv("VERIFY_LOG_DIR", str(log_dir))
    _install_noop_quality_stubs(tmp_path, monkeypatch)
    df_calls = tmp_path / "df.calls"
    _install_df_stub(tmp_path, avail_kb=999_999_999, calls_path=df_calls)
    # Host repo and /tmp are often different devices; pin both candidates
    # to one id so this test stays about "once per device", not the host layout.
    _install_stat_stub(tmp_path, default_dev="10")

    result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode == 0
    avail_queries = [line for line in df_calls.read_text().splitlines() if "avail" in line]
    # The repo checkout and the (stubbed) log filesystem resolve to the same
    # device here, so the gate must not query --output=avail for it twice.
    assert len(avail_queries) == 1


def test_disk_gate_blocks_when_log_filesystem_is_short_even_if_source_name_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same df source string is not the same device.

    Production change that fails this test: unique-key the two candidates by
    `df --output=source` instead of `stat -c %d`. Two tmpfs mounts then
    collapse to one check and a starving log filesystem is missed.
    """
    log_dir = tmp_path / "verify-logs"
    log_dir.mkdir()
    monkeypatch.setenv("VERIFY_LOG_DIR", str(log_dir))
    monkeypatch.setenv("VERIFY_MIN_FREE_MB", "100")
    _install_noop_quality_stubs(tmp_path, monkeypatch)
    df_calls = tmp_path / "df.calls"
    _install_df_stub(
        tmp_path,
        avail_kb=999_999_999,
        source="tmpfs",
        calls_path=df_calls,
        avail_kb_for_prefix=(str(tmp_path), 1024),
    )
    _install_stat_stub(
        tmp_path,
        default_dev="10",
        prefix=str(tmp_path),
        prefix_dev="20",
    )

    result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode == 65
    assert "not enough free disk space" in result.stderr
    assert "required : 100 MiB" in result.stderr
    avail_queries = [line for line in df_calls.read_text().splitlines() if "avail" in line]
    assert len(avail_queries) == 2
    assert list(log_dir.glob("verify-*.log")) == []


def test_disk_gate_skips_candidate_when_df_exits_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_dir = tmp_path / "verify-logs"
    monkeypatch.setenv("VERIFY_LOG_DIR", str(log_dir))
    # Gate must run (not VERIFY_MIN_FREE_MB=0) so the df calls are reached.
    monkeypatch.setenv("VERIFY_MIN_FREE_MB", "100")
    _install_noop_quality_stubs(tmp_path, monkeypatch)
    _fake_bin(tmp_path, "df", "exit 1")

    result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, capture_output=True, text=True)

    # pipefail must not abort the script; skip the candidate and continue.
    assert result.returncode == 0
    assert "not enough free disk space" not in result.stderr
    assert len(list(log_dir.glob("verify-full-*.log"))) == 1


@pytest.mark.parametrize(
    ("env_value", "required_mib"),
    [
        ("010", "10"),
        ("08", "8"),
    ],
)
def test_disk_gate_treats_leading_zeros_as_decimal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    env_value: str,
    required_mib: str,
) -> None:
    log_dir = tmp_path / "verify-logs"
    monkeypatch.setenv("VERIFY_LOG_DIR", str(log_dir))
    monkeypatch.setenv("VERIFY_MIN_FREE_MB", env_value)
    _install_noop_quality_stubs(tmp_path, monkeypatch)
    # 5 MiB free: below decimal 10 and decimal 8.
    _install_df_stub(tmp_path, avail_kb=5 * 1024)

    result = subprocess.run([str(VERIFY_SH), "full"], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode == 65
    assert f"required : {required_mib} MiB" in result.stderr
    assert "value too great for base" not in result.stderr
    assert list(log_dir.glob("verify-*.log")) == []


# ---- parallel execution (issues #263, #318, #320) ----------------------------


def test_quick_profile_pytest_is_parallel_with_group_aware_scheduling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #263: `quick`'s browser-less run must carry BOTH xdist flags.

    `-n auto` alone still runs in parallel but schedules per test; `--dist
    loadgroup` keeps each `xdist_group`-marked set on one worker. Asserting
    the two flags independently means losing `--dist loadgroup` fails here
    instead of weakening the distribution group silently.
    """
    entries = _run_quality_profile(tmp_path, monkeypatch, "quick")
    calls = [(tool, argv) for tool, _cwd, argv in entries]
    pytest_argv = [argv for tool, argv in calls if tool == "uv" and argv.startswith("run --no-sync pytest ")]

    assert len(pytest_argv) == 1
    (parallel_argv,) = pytest_argv
    assert "-n auto" in parallel_argv
    assert "--dist loadgroup" in parallel_argv


@pytest.mark.parametrize("profile", ["minimum", "latest"])
def test_compatibility_profiles_do_not_run_pytest_in_parallel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
) -> None:
    """Compatibility jobs remain serial because they were not benchmarked."""
    entries = _run_quality_profile(tmp_path, monkeypatch, profile)
    calls = [(tool, argv) for tool, _cwd, argv in entries]
    pytest_argv = [argv for tool, argv in calls if tool == "uv" and argv.startswith("run --no-sync pytest ")]

    assert pytest_argv
    for argv in pytest_argv:
        leaked = _worker_flags(argv)
        assert not leaked, f"the compatibility profile {profile} must not gain parallel execution: {leaked}"


def test_full_profile_parallelizes_only_non_distribution_suites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = _run_quality_profile(tmp_path, monkeypatch, "full")
    pytest_argv = [argv for tool, _cwd, argv in entries if tool == "uv" and argv.startswith("run --no-sync pytest ")]

    assert len(pytest_argv) == 3
    nonbrowser_argv, browser_argv, distribution_argv = pytest_argv
    assert _worker_flags(nonbrowser_argv) == ["-n", "--dist"]
    assert _worker_flags(browser_argv) == ["-n", "--dist"]
    assert not _worker_flags(distribution_argv)


def _collected_nodeids(marker: str | None = None) -> set[str]:
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    if marker is not None:
        argv.extend(["-m", marker])
    argv.append("tests")
    completed = subprocess.run(argv, cwd=ROOT, check=True, capture_output=True, text=True)
    return {line for line in completed.stdout.splitlines() if line.startswith("tests/") and "::" in line}


def test_full_profile_marker_partitions_cover_every_nodeid_once() -> None:
    all_nodeids = _collected_nodeids()
    partitions = (
        _collected_nodeids("not browser and not distribution"),
        _collected_nodeids("browser and not distribution"),
        _collected_nodeids("distribution"),
    )

    assert all(partitions), "each full-profile phase must select at least one test"
    assert not (partitions[0] & partitions[1])
    assert not (partitions[0] & partitions[2])
    assert not (partitions[1] & partitions[2])
    assert set().union(*partitions) == all_nodeids


@pytest.mark.parametrize(
    "token",
    [
        "-n",
        "-n2",
        "-n4",
        "-nauto",
        "--numprocesses",
        "--numprocesses=4",
        "--tx",
        "--tx=2*popen",
        "--dist",
        "--dist=loadfile",
        "--dist=loadgroup",
    ],
)
def test_parallel_flag_tokens_are_detected(token: str) -> None:
    """Issue #263: every spelling of a worker-starting or dist-mode option.

    The first version of this guard checked for the substring ``"-n "`` and so
    accepted ``-n2``/``-nauto``/``--numprocesses``; `full` is located by the
    ``"pytest -v"`` substring, so appending ``-n2`` after ``-v`` kept every
    other assertion in this file green while parallelising the release gate.
    """
    assert _WORKER_COUNT_RE.match(token) or _DIST_MODE_RE.match(token)


@pytest.mark.parametrize(
    "token",
    [
        "--no-sync",
        "-v",
        "-m",
        "not",
        "browser",
        "distribution",
        "tests",
        "--import-mode=importlib",
        "--distribution-artifacts-dir",
    ],
)
def test_benign_pytest_tokens_are_not_flagged(token: str) -> None:
    """The predicates must not fire on ordinary arguments, `--no-sync` above all.

    `--distribution-artifacts-dir` shares the `--dist` prefix with the xdist
    scheduling option but must never count as a parallel-execution flag.
    """
    assert not _WORKER_COUNT_RE.match(token)
    assert not _DIST_MODE_RE.match(token)


# ---- distribution fixture scheduling guard (issues #263, #318, #360) --------
#
# `quick` runs its single browser-less pytest with `--dist loadgroup`, so the
# distribution-marked tests share that run: the group pins them to one worker,
# whose session fixture builds the wheel/sdist pair once into that worker's
# basetemp while the other workers proceed. `full` instead builds the archives
# into the repo-root dist/ and runs the group serially against them.
# tests/fixtures/distribution.py auto-marks every item that requests
# `distribution_artifacts` with `xdist_group("distribution")`; xdist joins
# *every* xdist_group mark on an item into the effective group name, so an
# extra group added later would silently split them again while a mere
# presence check passed. Only tests/ is scanned — that is the whole public
# suite.

GROUP = "distribution"
FIXTURE = "distribution_artifacts"

# A test/fixture signature that takes the fixture as a parameter — `[^)]*`
# spans multi-line signatures — or a usefixtures mark naming it. This is a
# cheap candidate-module scan and can also match code embedded in a string;
# collection metadata below identifies the items that really request the
# fixture.
_FIXTURE_REQUEST_RE = re.compile(
    rf"(?m)^\s*(?:async\s+)?def\s+\w+\s*\([^)]*\b{FIXTURE}\b"
    rf'|usefixtures\([^)]*["\']{FIXTURE}["\']'
)


def _dynamic_fixture_request_lines(text: str) -> list[int]:
    tree = ast.parse(text)
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "getfixturevalue"
        and any(
            isinstance(value, ast.Constant) and value.value == FIXTURE
            for value in [
                *node.args[:1],
                *(keyword.value for keyword in node.keywords if keyword.arg == "argname"),
            ]
        )
    )


# Group names are opaque strings: "" and "a,b" are legal, and xdist keeps
# them distinct from "distribution". JSON preserves them without delimiter
# loss. The dump also records whether each item requests the fixture, because
# the guard below constrains only those items — other tests in a scanned
# module are free to stay ungrouped.
_DUMP_PLUGIN = """
import json
import os


def pytest_collection_modifyitems(items):
    payload = {}
    for item in items:
        payload[item.nodeid] = {
            "groups": sorted(
                str(mark.args[0] if mark.args else mark.kwargs.get("name", "default"))
                for mark in item.iter_markers("xdist_group")
            ),
            "requests_artifacts": "distribution_artifacts" in getattr(item, "fixturenames", ()),
        }
    with open(os.environ["XDIST_GROUP_DUMP"], "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
"""


def _modules_using_distribution_fixture(root: Path | None = None) -> list[str]:
    base_root = ROOT if root is None else root
    found: list[str] = []
    tests_root = base_root / "tests"
    if not tests_root.is_dir():
        return found
    for path in sorted(tests_root.rglob("test_*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(base_root).as_posix()
        dynamic_lines = _dynamic_fixture_request_lines(text)
        if dynamic_lines:
            locations = ", ".join(f"{relative}:{line}" for line in dynamic_lines)
            raise AssertionError(
                f"{locations}: getfixturevalue({FIXTURE!r}) bypasses automatic distribution/xdist markers; "
                "request the fixture through a function parameter or pytest.mark.usefixtures"
            )
        if _FIXTURE_REQUEST_RE.search(text):
            found.append(relative)
    return found


def _collected_items(tmp_path: Path, modules: list[str]) -> dict[str, dict[str, Any]]:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "_xdist_group_dump.py").write_text(_DUMP_PLUGIN, encoding="utf-8")
    dump = tmp_path / "groups.json"

    env = dict(os.environ)
    env["XDIST_GROUP_DUMP"] = str(dump)
    env["PYTHONPATH"] = str(plugin_dir)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "_xdist_group_dump",
            *modules,
        ],
        cwd=str(ROOT),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        pytest.fail(f"collection failed:\n{completed.stdout}\n{completed.stderr}")

    return dict(json.loads(dump.read_text(encoding="utf-8")))


def test_scan_finds_the_known_dist_touching_module() -> None:
    """The scan must actually reach the known fixture-using module.

    A predicate that silently matched nothing would make the guard below
    vacuous.
    """
    assert "tests/acceptance/test_distribution.py" in _modules_using_distribution_fixture()


@pytest.mark.parametrize(
    "call_template",
    [
        'request.getfixturevalue("{}")',
        'request.getfixturevalue(argname="{}")',
    ],
)
def test_scan_rejects_dynamic_fixture_requests(tmp_path: Path, call_template: str) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    fixture_name = "distribution_" + "artifacts"
    call = call_template.format(fixture_name)
    (tests / "test_dynamic.py").write_text(
        f"""\
def test_dynamic(request):
    {call}
""",
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match="getfixturevalue"):
        _modules_using_distribution_fixture(tmp_path)


def test_fixture_requesting_tests_share_exactly_one_xdist_group(tmp_path: Path) -> None:
    modules = _modules_using_distribution_fixture()
    items = _collected_items(tmp_path, modules)
    requesting = {nodeid: set(entry["groups"]) for nodeid, entry in items.items() if entry["requests_artifacts"]}
    assert requesting, "collected no items requesting the distribution_artifacts fixture"

    wrong = {nodeid: names for nodeid, names in requesting.items() if names != {GROUP}}
    assert not wrong, (
        "every test requesting the distribution_artifacts fixture must have the effective "
        f"xdist group {{{GROUP!r}}}; xdist joins all xdist_group marks on an item, "
        f"so these would be scheduled onto other workers: {wrong}"
    )


def test_effective_groups_preserves_empty_and_comma_names(tmp_path: Path) -> None:
    module = tmp_path / "test_extra_groups.py"
    module.write_text(
        """
import pytest

pytestmark = pytest.mark.xdist_group("distribution")


@pytest.mark.xdist_group("")
def test_empty_group():
    pass


@pytest.mark.xdist_group("distribution,")
def test_comma_group():
    pass
""",
        encoding="utf-8",
    )
    groups = {
        nodeid.rsplit("::", 1)[-1]: set(entry["groups"])
        for nodeid, entry in _collected_items(tmp_path, [str(module)]).items()
    }
    assert groups == {
        "test_empty_group": {"", "distribution"},
        "test_comma_group": {"distribution", "distribution,"},
    }
