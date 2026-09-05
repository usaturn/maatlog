#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

profile="${1:-full}"

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

quality_targets=(src tests)
if [[ -d tools/public_sync ]]; then
  quality_targets+=(tools)
fi
# The shared pyproject.toml only lists test paths present in both layouts;
# the parent-side sync tests are added here where they exist.
pytest_targets=(tests)
if [[ -d tools/public_sync/tests ]]; then
  pytest_targets+=(tools/public_sync/tests)
fi
uv lock --check
uv sync --locked --all-groups

case "$profile" in
  full)
    # Fail-fast (issue #148): cheap static checks (seconds) run before the
    # ~7-minute pytest suite and the distribution build, so a lint/type error
    # is caught immediately instead of after the whole suite has run.
    # `npm ci` must still precede pytest: tests/acceptance/test_accessibility.py
    # requires the installed node_modules/axe-core/axe.min.js fixture.
    uv run --no-sync ruff check "${quality_targets[@]}"
    uv run --no-sync ruff format --check "${quality_targets[@]}"
    uv run --no-sync pyright "${quality_targets[@]}"
    npm ci
    npm run check
    uv run --no-sync pytest -v "${pytest_targets[@]}"
    uv build --out-dir dist --clear
    uvx twine check --strict dist/*
    uv run --no-sync pytest tests/acceptance/test_distribution.py -v
    if [[ -d tools/public_sync ]]; then
      uv run --no-sync pytest tools/public_sync/tests/test_distribution_gate.py -v
    fi
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
