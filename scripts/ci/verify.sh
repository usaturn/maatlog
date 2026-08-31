#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

profile="${1:-full}"
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
    npm ci
    uv run --no-sync pytest -v "${pytest_targets[@]}"
    uv run --no-sync ruff format --check "${quality_targets[@]}"
    uv run --no-sync ruff check "${quality_targets[@]}"
    uv run --no-sync pyright "${quality_targets[@]}"
    npm run check
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
