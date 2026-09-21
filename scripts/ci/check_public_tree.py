#!/usr/bin/env python3
"""Fail when the public tree carries parent-private paths or text.

Two rules, applied to the git-tracked file set of a checkout:

- ``parent-path``: no tracked path may contain a parent-private directory or
  file name (``.agents``, ``tools``, ``devenv``, ...). The match is on whole
  path components, so ordinary names are never flagged.
- ``forbidden-text``: no tracked text file may contain the concrete
  parent-environment strings in ``FORBIDDEN_SHARED_TEXT``. The only exempt
  paths are this guard and its guard tests, which embed the literals as data.

Exit codes: 0 clean, 1 violations found, 2 input or git error.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[2]

PARENT_ONLY_PARTS = frozenset(
    {
        ".agents",
        ".claude",
        ".codex",
        ".devcontainer",
        ".pi",
        "devenv",
        "docs_draft",
        "reviews",
        "sync",
        "tools",
    }
)

# Concrete strings tied to the private parent environment. Quoted forms keep
# ordinary prose ("reviews", "tools") out of the rule.
FORBIDDEN_SHARED_TEXT = (
    "maatlog-devenv",
    "./devenv/",
    "/workspaces/maatlog/devenv/",
    "private Git submodule",
    "私有 Git サブモジュール",
    '"devenv",  # private サブモジュール',
    '".agents"',
    '".claude"',
    '".codex"',
    '".devcontainer"',
    '".pi"',
    '"devenv",',
    '"docs_draft"',
    '"reviews"',
    "maatlog-0.6.0/sync/",
    "maatlog-0.6.0/tools/",
)

# The guard and its tests legitimately embed the forbidden literals as rule
# data. They are the only paths exempt from the text scan.
TEXT_SCAN_EXEMPT_PATHS = frozenset(
    {
        "scripts/ci/check_public_tree.py",
        "tests/integration/test_public_repository.py",
        "tests/integration/test_quality_entrypoint.py",
    }
)

# Tracked entries proving the checkout is the public repository at all.
REQUIRED_PATHS = ("src", "tests", "pyproject.toml")

RULE_PARENT_PATH = "parent-path"
RULE_FORBIDDEN_TEXT = "forbidden-text"


class TreeCheckError(RuntimeError):
    """The checkout cannot be inspected (bad input or git failure)."""


def _tracked_files(root: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise TreeCheckError(f"cannot run git ls-files in {root}: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise TreeCheckError(f"git ls-files failed in {root}: {detail}")
    return [p for p in completed.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def _require_public_layout(files: list[str]) -> None:
    names = set(files)
    top_parts = {PurePosixPath(name).parts[0] for name in files}
    missing = [
        required
        for required in REQUIRED_PATHS
        if required not in (names if required == "pyproject.toml" else top_parts)
    ]
    if missing:
        raise TreeCheckError(f"checkout is missing required public paths: {', '.join(missing)}")


def _violations_for_path(relative: str) -> str | None:
    if PARENT_ONLY_PARTS & set(PurePosixPath(relative).parts):
        return f"{RULE_PARENT_PATH}: {relative}"
    return None


def check_public_tree(root: Path) -> list[str]:
    """Return ``rule: path`` violations for the tracked tree under *root*."""
    if not root.is_dir():
        raise TreeCheckError(f"not a directory: {root}")
    files = _tracked_files(root)
    _require_public_layout(files)

    violations: list[str] = []
    for relative in files:
        violation = _violations_for_path(relative)
        if violation is not None:
            violations.append(violation)

    for relative in files:
        if relative in TEXT_SCAN_EXEMPT_PATHS:
            continue
        path = root.joinpath(*PurePosixPath(relative).parts)
        if path.is_symlink():
            try:
                target = os.readlink(path)
            except OSError:
                continue
            if _violations_for_path(target) is not None:
                violations.append(f"{RULE_PARENT_PATH}: {relative}")
            if any(forbidden in target for forbidden in FORBIDDEN_SHARED_TEXT):
                violations.append(f"{RULE_FORBIDDEN_TEXT}: {relative}")
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError, OSError:
            continue
        if any(forbidden in text for forbidden in FORBIDDEN_SHARED_TEXT):
            violations.append(f"{RULE_FORBIDDEN_TEXT}: {relative}")
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]).expanduser() if args else REPO_ROOT
    try:
        violations = check_public_tree(root)
    except TreeCheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for violation in violations:
        print(violation)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
