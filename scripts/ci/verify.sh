#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

profile="${1:-full}"
if (($# > 1)); then
  printf 'verify.sh takes only the profile argument; unexpected extra argument: %s\n' "$2" >&2
  exit 64
fi

# ---- disk-space gate (issue #145) ------------------------------------------
# Runs before log setup: writing the log itself needs free space too, so a
# gate failure here is reported on stderr only and never reaches a log file.
_verify_existing_ancestor() {
  local path="$1"
  while [[ ! -d "$path" && "$path" != "/" ]]; do
    path="$(dirname "$path")"
  done
  printf '%s' "$path"
}

verify_min_free_mb="${VERIFY_MIN_FREE_MB:-}"
if [[ -z "$verify_min_free_mb" ]]; then
  case "$profile" in
    full) verify_min_free_mb=5120 ;;
    *) verify_min_free_mb=2048 ;;
  esac
fi
if [[ ! "$verify_min_free_mb" =~ ^[0-9]+$ ]]; then
  printf 'ERROR: VERIFY_MIN_FREE_MB must be a non-negative integer (MiB), got: %s\n' "$verify_min_free_mb" >&2
  exit 65
fi
verify_min_free_mb=$((10#$verify_min_free_mb))

if [[ "$verify_min_free_mb" != "0" ]]; then
  # The repo checkout and the log destination (issue #150) can live on
  # different filesystems; check both, but only once each even if they
  # resolve to the same underlying device.
  verify_log_area="$(_verify_existing_ancestor "${VERIFY_LOG_DIR:-${TMPDIR:-/tmp}}")"

  declare -A verify_seen_devices=()
  verify_gate_paths=()
  for verify_candidate_path in "$repo_root" "$verify_log_area"; do
    verify_device="$(stat -c %d "$verify_candidate_path" 2>/dev/null)" || true
    if [[ -n "$verify_device" && -n "${verify_seen_devices[$verify_device]:-}" ]]; then
      continue
    fi
    if [[ -n "$verify_device" ]]; then
      verify_seen_devices[$verify_device]=1
    fi
    verify_gate_paths+=("$verify_candidate_path")
  done

  for verify_candidate_path in "${verify_gate_paths[@]}"; do
    verify_avail_kb="$(df --output=avail -k "$verify_candidate_path" 2>/dev/null | tail -n1 | tr -d ' ')" || true
    if [[ -z "$verify_avail_kb" ]]; then
      continue # df failed for this path; do not let that block the run
    fi
    verify_avail_mb=$((verify_avail_kb / 1024))
    if ((verify_avail_mb < verify_min_free_mb)); then
      {
        printf 'ERROR: not enough free disk space to run verify.sh (%s profile)\n' "$profile"
        printf '  required : %d MiB\n' "$verify_min_free_mb"
        printf '  available: %d MiB on %s\n' "$verify_avail_mb" "$verify_candidate_path"
        printf '  hint: clean /tmp/pr-review-*, stale verify.sh logs, or unused git worktrees\n'
        printf '  hint: override with VERIFY_MIN_FREE_MB=<mb>; VERIFY_MIN_FREE_MB=0 disables this gate\n'
      } >&2
      exit 65
    fi
  done
fi

# ---- automatic logging (issue #150) ----------------------------------------
# Every invocation (success or failure) must leave exactly one timestamped log
# file behind, without ever swallowing the wrapped commands' exit code.

verify_log_dir_candidates=()
if [[ -n "${VERIFY_LOG_DIR:-}" ]]; then
  verify_log_dir_candidates+=("$VERIFY_LOG_DIR")
else
  verify_log_dir_candidates+=("${TMPDIR:-/tmp}/maatlog-verify-logs")
fi
verify_log_dir_candidates+=("${TMPDIR:-/tmp}")
verify_log_dir_candidates+=("/tmp")

verify_log_dir=""
for candidate in "${verify_log_dir_candidates[@]}"; do
  if mkdir -p "$candidate" 2>/dev/null && [[ -w "$candidate" ]]; then
    verify_log_dir="$candidate"
    break
  fi
done

if [[ -z "$verify_log_dir" ]]; then
  {
    printf 'ERROR: verify.sh could not find a writable directory for its log file\n'
    printf 'tried:\n'
    for candidate in "${verify_log_dir_candidates[@]}"; do
      printf '  - %s\n' "$candidate"
    done
    printf 'hint: set VERIFY_LOG_DIR to a writable directory and retry\n'
  } >&2
  exit 66
fi

verify_log_timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
safe_profile="${profile//\//-}"
verify_log_file="$verify_log_dir/verify-${safe_profile}-${verify_log_timestamp}-$$.log"

# Use process substitution (not a pipe) so `$?` after the script's own commands
# still reflects the real command, not tee. Capture tee's pid so the EXIT trap
# can close our fds and wait for it, guaranteeing the last lines are flushed.
exec > >(tee "$verify_log_file") 2>&1
verify_tee_pid=$!

_verify_exit_trap() {
  local code=$?
  printf 'EXIT=%s\n' "$code"
  exec >&- 2>&-
  wait "$verify_tee_pid" 2>/dev/null || true
  exit "$code"
}
trap _verify_exit_trap EXIT

verify_head_sha="$(git rev-parse HEAD 2>/dev/null || printf 'unknown')"
printf 'verify.sh log: %s\n' "$verify_log_file"
printf 'profile: %s\n' "$profile"
printf 'start (UTC): %s\n' "$verify_log_timestamp"
printf 'HEAD: %s\n' "$verify_head_sha"
printf 'workdir: %s\n' "$repo_root"

# ---- log rotation (issue #150) ----------------------------------------------
# Keep the most recent 10 generations under $verify_log_dir. Never delete this
# run's own log, and never delete a log whose pid is still alive (another
# verify.sh run in progress) even if it is otherwise old enough to prune.
_verify_rotate_logs() {
  local dir="$1" keep=10 count=0 name path pid
  local -a logs=()
  while IFS= read -r name; do
    logs+=("$name")
  done < <(cd "$dir" && ls -t -- verify-*.log 2>/dev/null || true)
  for name in "${logs[@]}"; do
    path="$dir/$name"
    count=$((count + 1))
    if ((count <= keep)); then
      continue
    fi
    if [[ "$path" == "$verify_log_file" ]]; then
      continue
    fi
    pid="${name%.log}"
    pid="${pid##*-}"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
      continue
    fi
    rm -f -- "$path"
  done
}
_verify_rotate_logs "$verify_log_dir"

# This checkout is the public repository: the package lives in src/ and its
# suite in tests/. Those are the only verification targets — a checkout that
# lacks either is broken rather than a different layout.
quality_targets=(src tests)
pytest_targets=(tests)
for required_target in src tests; do
  if [[ ! -d "$required_target" ]]; then
    printf 'missing required verification target: %s\n' "$required_target" >&2
    exit 64
  fi
done

# Issue #320 measured the browser suite with 1/2/4 workers. Two workers with
# loadscope were the fastest stable candidate; four workers timed out. Keep the
# override bounded so a host cannot accidentally turn this into `-n auto`.
verify_browser_workers="${VERIFY_BROWSER_WORKERS-2}"
if [[ "$profile" == "full" ]]; then
  if [[ ! "$verify_browser_workers" =~ ^[0-9]+$ ]] \
    || ((10#$verify_browser_workers < 1 || 10#$verify_browser_workers > 4)); then
    printf 'ERROR: VERIFY_BROWSER_WORKERS must be an integer from 1 to 4, got: %s\n' \
      "$verify_browser_workers" >&2
    exit 65
  fi
  verify_browser_workers=$((10#$verify_browser_workers))
  printf 'browser workers: %d\n' "$verify_browser_workers"
  printf 'browser distribution: loadscope\n'
fi
# The Python-side static checks shared by `full`, `static` and `quick`
# (issue #264). One definition, so adding a tool or changing the targets is a
# single edit. Fail-fast order (issue #148): these cost seconds, so the
# quality profiles (`full`, `static` and `quick`) run them first — `full`
# and `quick` before pytest — so a lint or type error surfaces
# immediately instead of after the suite. `set -e` applies inside
# the body and every call site below is a plain command, so the first failing
# check still aborts the whole script.
run_python_static_checks() {
  uv run --no-sync ruff check "${quality_targets[@]}"
  uv run --no-sync ruff format --check "${quality_targets[@]}"
  uv run --no-sync pyright "${quality_targets[@]}"
}

# `full` and `static` additionally run the frontend checks. `npm ci` must
# precede `npm run check`, which needs node_modules (eslint / prettier / tsc /
# stylelint).
run_static_checks() {
  run_python_static_checks
  npm ci
  npm run check
}

# The public tree itself is a checked invariant: a tracked parent-only path
# or a leaked private-environment reference fails every profile before any
# dependency setup runs. The checker is stdlib-only, so it needs no synced venv.
uv run --no-sync python scripts/ci/check_public_tree.py "$repo_root"

uv lock --check
uv sync --locked --all-groups

case "$profile" in
  full)
    # `npm ci`, inside run_static_checks, must also precede pytest here:
    # tests/acceptance/test_accessibility.py requires the installed
    # node_modules/axe-core/axe.min.js fixture.
    run_static_checks
    # Issue #320: keep the three marker partitions sequential. Browser-less
    # tests use the group-aware quick-profile scheduling, browser tests use the
    # measured bounded worker count, and distribution remains serial after its
    # single archive build (issue #318).
    uv run --no-sync pytest -n auto --dist loadgroup -m "not browser and not distribution" -v "${pytest_targets[@]}"
    uv run --no-sync pytest -n "$verify_browser_workers" --dist loadscope \
      -m "browser and not distribution" -v "${pytest_targets[@]}"
    uv build --out-dir dist --clear
    uv run --no-sync python tests/fixtures/distribution.py dist
    uv run --no-sync pytest -m distribution --distribution-artifacts-dir "$repo_root/dist" -v "${pytest_targets[@]}"
    ;;
  static)
    # `static` and `quick` (issue #260) are the development-time profiles: they
    # never run `uv pip install`, so the venv stays exactly as `uv sync` left it
    # and they can be repeated freely. `full` remains the release gate.
    run_static_checks
    ;;
  quick)
    # Issue #360: `quick` keeps only the Python static checks. The `npm ci` /
    # `npm run check` pair guards frontend tooling that `full` already owns —
    # every path it protects (theme assets under src/maatlog/themes/, the npm
    # manifests, the frontend tooling root configs) selects the `full`
    # profile — so quick paid ~5-7 s for no coverage. A single browser-less
    # pytest run then covers everything else:
    # `xdist_group("distribution")` holds all distribution tests on one worker
    # under `--dist loadgroup`, and that worker's session fixture builds the
    # archives once into its run-private basetemp while the other workers
    # proceed — the serial follow-up run from issue #318 only pays off in
    # `full`, where the gate must verify a specific repo-root dist/ tree.
    run_python_static_checks
    uv run --no-sync pytest -n auto --dist loadgroup -m "not browser" -v "${pytest_targets[@]}"
    ;;
  minimum)
    uv pip install 'Sphinx==9.1.0' 'myst-parser==5.1.0'
    uv run --no-sync pytest -m "not browser" -v "${pytest_targets[@]}"
    ;;
  latest)
    uv pip install --upgrade Sphinx myst-parser
    uv run --no-sync pytest -m "not browser" -v "${pytest_targets[@]}"
    ;;
  *)
    printf 'unknown verification profile: %s\n' "$profile" >&2
    exit 64
    ;;
esac
