#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

profile="${1:-full}"
quality_targets=(src tests)
if [[ -d tools/public_sync ]]; then
  quality_targets+=(tools)
fi
uv lock --check
uv sync --locked --all-groups

case "$profile" in
  full)
    uv run --no-sync pytest -v
    uv run --no-sync ruff format --check "${quality_targets[@]}"
    uv run --no-sync ruff check "${quality_targets[@]}"
    uv run --no-sync pyright "${quality_targets[@]}"
    uv build --out-dir dist --clear
    uvx twine check --strict dist/*
    uv run --no-sync pytest tests/acceptance/test_distribution.py -v
    ;;
  minimum)
    uv pip install 'Sphinx==9.1.0' 'myst-parser==5.1.0'
    uv run --no-sync pytest -v
    ;;
  latest)
    uv pip install --upgrade Sphinx myst-parser
    uv run --no-sync pytest -v
    ;;
  *)
    printf 'unknown verification profile: %s\n' "$profile" >&2
    exit 64
    ;;
esac
