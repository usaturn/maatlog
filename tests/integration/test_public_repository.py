"""Public-tree and CI guards for the standalone public repository.

The public repository must stay inspectable without the parent repository:
tracked paths must not carry parent-private directory names, public-facing
files must not contain concrete parent-environment strings, and the CI
secret-scan job must scan with the base branch's ruleset only.

Guard and fixture literals that would themselves trip the text rules live only
in this file, in ``tests/integration/test_quality_entrypoint.py``, and in
``scripts/ci/check_public_tree.py``; the guard exempts exactly those paths from
the text scan.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT = REPO_ROOT / "scripts" / "ci" / "check_public_tree.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PUBLISH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish-to-pypi.yml"

APPROVED_GITLEAKS_PIN = (
    "8.30.1",
    "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
)

# Strings that identify parent-private material. Each is specific enough that
# ordinary prose ("reviews", "tools") never matches them.
PARENT_ONLY_DIR_EXAMPLES = (".agents", "tools", "devenv", "docs_draft", "sync")
PRIVATE_TEXT_EXAMPLE = "private Git submodule"
PRIVATE_QUOTED_EXAMPLE = '"devenv",'
# Deliberately excluded from the rule set: the bare word is ordinary prose.
NATURAL_WORD = "reviews"

# Not a real credential: gitleaks's own documentation and the retired parent
# suite both use this AWS example key id shape for detection fixtures. The
# literal is split so this tracked file itself stays invisible to the scan;
# the fixture value at runtime is the complete key id.
FAKE_AWS_KEY = "AKIA" + "IMNOJVGFDXXXE4OA"


def _init_repo(root: Path, files: dict[str, str]) -> Path:
    """Create a git repository at *root* with *files* staged into the index."""
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for relative, content in files.items():
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", "--", relative], cwd=root, check=True)
    return root


def _minimal_repo_files() -> dict[str, str]:
    return {
        "src/ok.py": "VALUE = 1\n",
        "tests/test_ok.py": "def test_ok():\n    assert True\n",
        "pyproject.toml": '[project]\nname = "fixture"\nversion = "0.0.0"\n',
        "README.rst": "Fixture\n=======\n\nText.\n",
    }


def _run_tree_check(root: Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), str(root)],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


# ---- tracked-path rules -----------------------------------------------------


def test_clean_public_tree_passes(tmp_path: Path) -> None:
    root = _init_repo(tmp_path / "repo", _minimal_repo_files())
    result = _run_tree_check(root)
    assert result.returncode == 0, result.stderr


def test_natural_language_reviews_is_not_flagged(tmp_path: Path) -> None:
    files = _minimal_repo_files()
    files["README.rst"] = "Fixture\n=======\n\nUser reviews and code reviews are welcome.\n"
    root = _init_repo(tmp_path / "repo", files)
    result = _run_tree_check(root)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("target", "rule"),
    [
        ("/workspaces/maatlog/devenv/", "forbidden-text"),
        ("./devenv/setup.sh", "forbidden-text"),
        ("../tools/shared.py", "parent-path"),
    ],
)
def test_tracked_symlink_to_parent_only_path_is_flagged(tmp_path: Path, target: str, rule: str) -> None:
    root = _init_repo(tmp_path / "repo", _minimal_repo_files())
    (root / "leak-link").symlink_to(target)
    subprocess.run(["git", "add", "leak-link"], cwd=root, check=True)

    result = _run_tree_check(root)
    assert result.returncode == 1
    assert f"{rule}: leak-link" in result.stdout


def test_tracked_symlink_to_public_path_passes(tmp_path: Path) -> None:
    root = _init_repo(tmp_path / "repo", _minimal_repo_files())
    (root / "ok-link").symlink_to("src/ok.py")
    subprocess.run(["git", "add", "ok-link"], cwd=root, check=True)

    result = _run_tree_check(root)
    assert result.returncode == 0, result.stdout


def test_exempt_path_symlink_to_parent_only_path_is_flagged(tmp_path: Path) -> None:
    root = _init_repo(tmp_path / "repo", _minimal_repo_files())
    relative = "scripts/ci/check_public_tree.py"
    link = root / relative
    link.parent.mkdir(parents=True)
    link.symlink_to("../tools/evil.py")
    subprocess.run(["git", "add", relative], cwd=root, check=True)

    result = _run_tree_check(root)
    assert result.returncode == 1, result.stdout
    assert f"parent-path: {relative}" in result.stdout


@pytest.mark.parametrize("parent_dir", PARENT_ONLY_DIR_EXAMPLES)
def test_tracked_parent_only_directory_is_flagged(tmp_path: Path, parent_dir: str) -> None:
    files = _minimal_repo_files()
    files[f"{parent_dir}/note.md"] = "private note\n"
    root = _init_repo(tmp_path / "repo", files)
    result = _run_tree_check(root)
    assert result.returncode == 1
    assert f"{parent_dir}/note.md" in result.stdout
    assert "parent-path" in result.stdout


def test_untracked_parent_only_directory_is_ignored(tmp_path: Path) -> None:
    """Only tracked files are inspected: a stray untracked dir must not fail."""
    root = _init_repo(tmp_path / "repo", _minimal_repo_files())
    stray = root / ".agents" / "local.md"
    stray.parent.mkdir()
    stray.write_text("untracked\n", encoding="utf-8")
    result = _run_tree_check(root)
    assert result.returncode == 0, result.stderr


# ---- shared-text rules ------------------------------------------------------


def test_readme_disclosing_private_environment_is_flagged(tmp_path: Path) -> None:
    files = _minimal_repo_files()
    files["README.rst"] = f"Fixture\n=======\n\nThis checkout is a {PRIVATE_TEXT_EXAMPLE}.\n"
    root = _init_repo(tmp_path / "repo", files)
    result = _run_tree_check(root)
    assert result.returncode == 1
    assert "forbidden-text" in result.stdout
    assert "README.rst" in result.stdout


def test_frontend_config_referencing_parent_dir_is_flagged(tmp_path: Path) -> None:
    files = _minimal_repo_files()
    files["package.json"] = '{\n  "workspaces": ["app", ' + PRIVATE_QUOTED_EXAMPLE + "]\n}\n"
    root = _init_repo(tmp_path / "repo", files)
    result = _run_tree_check(root)
    assert result.returncode == 1
    assert "package.json" in result.stdout


def test_violation_output_never_echoes_file_content(tmp_path: Path) -> None:
    """Findings are ``rule: path`` only; matched text must not be printed."""
    marker = "parent marker 9f3c2e must not be echoed"
    files = _minimal_repo_files()
    files["README.rst"] = f"Fixture\n=======\n\nA {PRIVATE_TEXT_EXAMPLE} {marker}.\n"
    root = _init_repo(tmp_path / "repo", files)
    result = _run_tree_check(root)
    assert result.returncode == 1
    assert marker not in result.stdout
    assert marker not in result.stderr
    assert PRIVATE_TEXT_EXAMPLE not in result.stdout
    assert PRIVATE_TEXT_EXAMPLE not in result.stderr


def test_guard_own_files_are_the_only_text_scan_exemptions(tmp_path: Path) -> None:
    """The exempt set is exactly the guard script and its guard-test files.

    The same literal in a differently named file must still be flagged; an
    exemption by directory or suffix would silently disable the scan.
    """
    files = _minimal_repo_files()
    files["tests/integration/test_public_repository.py"] = f"X = {PRIVATE_QUOTED_EXAMPLE}\n"
    files["tests/integration/test_quality_entrypoint.py"] = f"Y = {PRIVATE_QUOTED_EXAMPLE}\n"
    files["scripts/ci/check_public_tree.py"] = f"Z = {PRIVATE_QUOTED_EXAMPLE}\n"
    root = _init_repo(tmp_path / "repo", files)
    assert _run_tree_check(root).returncode == 0

    files["docs/leak.rst"] = f"A {PRIVATE_TEXT_EXAMPLE}.\n"
    root2 = _init_repo(tmp_path / "repo2", files)
    result = _run_tree_check(root2)
    assert result.returncode == 1
    assert "docs/leak.rst" in result.stdout


# ---- input and git errors ---------------------------------------------------


def test_missing_required_path_fails_closed(tmp_path: Path) -> None:
    files = _minimal_repo_files()
    del files["src/ok.py"]
    root = _init_repo(tmp_path / "repo", files)
    assert _run_tree_check(root).returncode == 2


def test_missing_pyproject_fails_closed(tmp_path: Path) -> None:
    files = _minimal_repo_files()
    del files["pyproject.toml"]
    root = _init_repo(tmp_path / "repo", files)
    assert _run_tree_check(root).returncode == 2


def test_non_git_directory_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "not-a-repo"
    root.mkdir()
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert _run_tree_check(root).returncode == 2


def test_nonexistent_root_fails_closed(tmp_path: Path) -> None:
    assert _run_tree_check(tmp_path / "absent").returncode == 2


def test_check_is_cwd_independent(tmp_path: Path) -> None:
    root = _init_repo(tmp_path / "repo", _minimal_repo_files())
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = _run_tree_check(root, cwd=elsewhere)
    assert result.returncode == 0, result.stderr


def test_default_root_is_the_repository() -> None:
    """With no argument the script inspects its own repository checkout."""
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_real_public_tree_is_clean() -> None:
    result = _run_tree_check(REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


# ---- publish workflow (read-only contract) ----------------------------------


def _job_body(workflow: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)",
        workflow,
    )
    assert match is not None, name
    return match.group("body")


def test_publish_workflow_triggers_and_default_permissions() -> None:
    text = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    assert text.startswith("name: Publish Python distribution\n")
    assert re.search(r'(?ms)^on:\n  workflow_dispatch:\n  push:\n    tags:\n      - "v\*"\n', text)
    on_match = re.search(r"(?ms)^on:\n.*?(?=^permissions:)", text)
    jobs_match = re.search(r"(?ms)^jobs:\n", text)
    perms_match = re.search(r"(?ms)^permissions:\n  contents: read\n", text)
    assert on_match is not None
    assert perms_match is not None
    assert jobs_match is not None
    assert on_match.end() <= perms_match.start() < jobs_match.start()
    assert "contents: write" not in text
    assert "packages: write" not in text
    assert "permissions: write-all" not in text


def test_build_job_has_no_publish_permission() -> None:
    body = _job_body(PUBLISH_WORKFLOW.read_text(encoding="utf-8"), "build")
    assert "runs-on: ubuntu-latest" in body
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in body
    assert "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9" in body
    assert 'python-version: "3.14"' in body
    assert "uv build --out-dir dist --clear" in body
    assert "uvx twine check --strict dist/*" in body
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in body
    assert "name: python-package-distributions" in body
    assert "id-token: write" not in body
    assert "pypa/gh-action-pypi-publish" not in body


def test_testpypi_job_is_workflow_dispatch_only() -> None:
    text = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    body = _job_body(text, "publish-to-testpypi")
    assert "if: github.event_name == 'workflow_dispatch'" in body
    assert "needs:\n      - build\n" in body
    assert "name: testpypi\n" in body
    assert "url: https://test.pypi.org/p/maatlog\n" in body
    assert "id-token: write" in body
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" in body
    assert "name: python-package-distributions" in body
    assert "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33" in body
    assert "repository-url: https://test.pypi.org/legacy/" in body
    assert "secrets." not in body
    assert "password:" not in body


def test_pypi_job_is_tag_push_only() -> None:
    body = _job_body(PUBLISH_WORKFLOW.read_text(encoding="utf-8"), "publish-to-pypi")
    assert "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/')" in body
    assert "github.event_name == 'workflow_dispatch'" not in body
    assert "needs:\n      - build\n" in body
    assert "name: pypi\n" in body
    assert "url: https://pypi.org/p/maatlog\n" in body
    assert "id-token: write" in body
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" in body
    assert "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33" in body
    assert "repository-url:" not in body
    assert "test.pypi.org" not in body
    assert "secrets." not in body
    assert "password:" not in body


# ---- public CI workflow (read-only contract) --------------------------------


def _ci_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def test_public_gitignore_does_not_ignore_product_roots() -> None:
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for required in ("uv.lock", "LICENSE", "scripts", "src", "tests", "docs"):
        # Product roots must remain trackable; only docs/_build/ is excluded.
        assert not re.search(rf"(?m)^{re.escape(required)}/?$", text)
    assert "docs/_build/" in text
    for generated in ("node_modules/", ".eslintcache", ".stylelintcache"):
        assert generated in text
    assert "package-lock.json" not in text


def test_public_workflow_permissions_are_contents_read_only() -> None:
    text = _ci_text()
    # Parse as text so PyYAML cannot reinterpret the YAML ``on`` key.
    on_match = re.search(r"(?ms)^on:\n.*?(?=^permissions:)", text)
    jobs_match = re.search(r"(?ms)^jobs:\n", text)
    perms_match = re.search(r"(?ms)^permissions:\n  contents: read\n", text)
    assert on_match is not None
    assert perms_match is not None
    assert jobs_match is not None
    assert on_match.end() <= perms_match.start() < jobs_match.start()
    assert "permissions:\n  contents: read\n" in text
    # No broader or job-specific write permission.
    assert "contents: write" not in text
    assert "permissions: write" not in text
    assert "id-token: write" not in text
    assert "packages: write" not in text
    assert "submodules:" not in text


def test_public_full_ci_pins_node_and_prepares_chromium() -> None:
    text = _ci_text()
    assert "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020" in text
    assert 'node-version-file: ".nvmrc"' in text
    assert 'cache-dependency-path: "package-lock.json"' in text
    assert text.count("if: matrix.profile == 'full'") >= 2
    assert "uv sync --locked --all-groups" in text
    assert "uv run playwright install --with-deps chromium" in text
    assert text.index("Set up Node.js") < text.index("Install Chromium") < text.index("verify.sh")


# ---- secret-scan job: base-owned ruleset and execution boundary -------------


def _secret_scan_body() -> str:
    return _job_body(_ci_text(), "secret-scan")


def test_secret_scan_events_keep_verify_off_pull_request_target() -> None:
    text = _ci_text()
    on_match = re.search(r"(?ms)^on:\n(.*?)(?=^permissions:)", text)
    assert on_match is not None
    on_block = on_match.group(1)
    assert re.search(r"(?m)^  pull_request:\s*$", on_block)
    assert re.search(r"(?m)^  pull_request_target:\s*$", on_block)
    assert re.search(r"(?ms)^  push:\n    branches: \[main\]\n", on_block)
    assert re.search(r"(?m)^  workflow_dispatch:\s*$", on_block)

    # The PR event and the trusted event must each run exactly one family:
    # verify never sees pull_request_target, secret-scan never sees pull_request.
    assert "github.event_name != 'pull_request_target'" in _job_body(text, "verify")
    assert "github.event_name != 'pull_request'" in _secret_scan_body()


def test_secret_scan_installer_uses_approved_pin() -> None:
    body = _secret_scan_body()
    assert f'GITLEAKS_VERSION: "{APPROVED_GITLEAKS_PIN[0]}"' in body
    assert f'GITLEAKS_ARCHIVE_SHA256: "{APPROVED_GITLEAKS_PIN[1]}"' in body
    assert "v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" in body
    assert '"$GITLEAKS_ARCHIVE_SHA256"' in body
    assert "sha256sum -c -" in body


def test_secret_scan_never_executes_pull_request_content() -> None:
    """The trusted job must not build, test, or cache anything from the PR."""
    body = _secret_scan_body()
    assert "contents: read" in body
    assert "persist-credentials: false" in body
    assert "fetch-depth: 0" in body
    for forbidden in (
        "ref: ${{ github.event.pull_request.head",
        "uv sync",
        "uv run",
        "uvx ",
        "npm ",
        "pytest",
        "setup-node",
        "setup-uv",
        "actions/cache",
        "upload-artifact",
        "secrets.",
    ):
        assert forbidden not in body, forbidden


def test_secret_scan_compares_event_shas_before_scanning() -> None:
    """A moving refs/pull tip or wrong checkout must fail closed."""
    body = _secret_scan_body()
    assert "PR_NUMBER" in body
    assert "BASE_SHA" in body
    assert "HEAD_SHA" in body
    assert "github.event.pull_request.number" in body
    assert "github.event.pull_request.base.sha" in body
    assert "github.event.pull_request.head.sha" in body
    # The checked-out base must equal the event's base.sha, and the fetched
    # refs/pull head must equal the event's head.sha, before any scan runs.
    assert "git rev-parse HEAD" in body
    assert 'git fetch --no-tags origin "refs/pull/' in body
    assert "git rev-parse FETCH_HEAD" in body
    assert "git merge-base" in body


def test_secret_scan_uses_base_config_and_redacts() -> None:
    body = _secret_scan_body()
    assert 'gitleaks git --redact --no-banner --config "$GITHUB_WORKSPACE/.gitleaks.toml"' in body
    assert body.count("--ignore-gitleaks-allow") == 2
    assert "--log-opts=" in body
    # Environment config injection must not be able to replace the pinned rules.
    assert "unset GITLEAKS_CONFIG GITLEAKS_CONFIG_TOML" in body
    # Push events scan the pushed range, falling back to the full history when
    # the before SHA is absent (new branch) rather than skipping the scan.
    assert "github.event.before" in body


def test_gitleaks_config_extends_defaults_without_allowlist() -> None:
    text = (REPO_ROOT / ".gitleaks.toml").read_text(encoding="utf-8")
    assert "useDefault = true" in text
    assert "allowlist" not in text
    assert "[rules]" not in text
    assert "[[rules]]" not in text


# ---- gitleaks behaviour against disposable repositories ---------------------

_GITLEAKS = shutil.which("gitleaks")
requires_gitleaks = pytest.mark.skipif(_GITLEAKS is None, reason="gitleaks is not installed")

_BASE_CONFIG = 'title = "maatlog public"\n\n[extend]\nuseDefault = true\n'
# A config that would let the fake key through if it ever won over --config.
_PERMISSIVE_CONFIG = (
    'title = "tree-supplied"\n\n[[rules]]\nid = "nothing"\ndescription = "matches nothing"\nregex = '
    "'''zzzzzzzznevermatchzzzzzzzz'''\n"
)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _commit_file(root: Path, relative: str, content: str, message: str) -> str:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(root, "add", "--", relative)
    _git(
        root,
        "-c",
        "user.name=fixture",
        "-c",
        "user.email=fixture@example.test",
        "commit",
        "-qm",
        message,
    )
    return _git(root, "rev-parse", "HEAD")


def _secret_repo(tmp_path: Path, *, leak: bool = True, inline_allow: bool = False) -> tuple[Path, str, str]:
    """Repo whose base branch is clean and whose PR branch adds a secret.

    The PR branch also swaps ``.gitleaks.toml`` for a permissive ruleset, so the
    scan only detects the key when the base-owned config wins.
    Returns ``(root, base_sha, head_sha)`` with the worktree left on the base.
    """
    root = tmp_path / "scan-repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    base = _commit_file(root, "app.py", "VALUE = 1\n", "base")
    _commit_file(root, ".gitleaks.toml", _BASE_CONFIG, "base config")
    base = _git(root, "rev-parse", "HEAD")

    _git(root, "switch", "-q", "-c", "pr")
    if leak:
        allow = "  #gitleaks:allow" if inline_allow else ""
        _commit_file(root, "leak.py", f'AWS_KEY = "{FAKE_AWS_KEY}"{allow}\n', "add key")
    _commit_file(root, ".gitleaks.toml", _PERMISSIVE_CONFIG, "weaken config")
    head = _git(root, "rev-parse", "HEAD")
    _git(root, "switch", "-q", "main")
    return root, base, head


def _run_range_scan(
    root: Path,
    base: str,
    head: str,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the same command shape the CI scan step runs against the base checkout."""
    env = dict(os.environ)
    env.pop("GITLEAKS_CONFIG", None)
    env.pop("GITLEAKS_CONFIG_TOML", None)
    env.update(env_extra or {})
    return subprocess.run(
        [
            "gitleaks",
            "git",
            "--redact",
            "--no-banner",
            "--config",
            str(root / ".gitleaks.toml"),
            "--ignore-gitleaks-allow",
            f"--log-opts={base}..{head}",
            ".",
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


@requires_gitleaks
def test_range_scan_detects_secret_despite_tree_config(tmp_path: Path) -> None:
    root, base, head = _secret_repo(tmp_path)
    result = _run_range_scan(root, base, head)
    assert result.returncode == 1, result.stderr
    # --redact must keep the secret text out of every output stream.
    assert FAKE_AWS_KEY not in result.stdout
    assert FAKE_AWS_KEY not in result.stderr


@requires_gitleaks
def test_range_scan_rejects_inline_gitleaks_allow(tmp_path: Path) -> None:
    root, base, head = _secret_repo(tmp_path, inline_allow=True)
    result = _run_range_scan(root, base, head)
    assert result.returncode == 1, result.stderr
    assert FAKE_AWS_KEY not in result.stdout
    assert FAKE_AWS_KEY not in result.stderr


@requires_gitleaks
def test_range_scan_passes_clean_history(tmp_path: Path) -> None:
    root, base, head = _secret_repo(tmp_path, leak=False)
    result = _run_range_scan(root, base, head)
    assert result.returncode == 0, result.stderr + result.stdout


@requires_gitleaks
def test_range_scan_scopes_to_the_pr_commits(tmp_path: Path) -> None:
    """A secret already on the base branch is outside the merge-base..head range."""
    root = tmp_path / "scan-repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    base = _commit_file(root, "old.py", f'KEY = "{FAKE_AWS_KEY}"\n', "old leak")
    _commit_file(root, ".gitleaks.toml", _BASE_CONFIG, "base config")
    base = _git(root, "rev-parse", "HEAD")
    _git(root, "switch", "-q", "-c", "pr")
    head = _commit_file(root, "clean.py", "OK = 1\n", "clean")
    _git(root, "switch", "-q", "main")
    result = _run_range_scan(root, base, head)
    assert result.returncode == 0, result.stderr + result.stdout


@requires_gitleaks
def test_explicit_config_beats_environment_override(tmp_path: Path) -> None:
    """GITLEAKS_CONFIG/GITLEAKS_CONFIG_TOML must not replace the pinned rules."""
    root, base, head = _secret_repo(tmp_path)
    permissive = tmp_path / "permissive.toml"
    permissive.write_text(_PERMISSIVE_CONFIG, encoding="utf-8")
    for env_extra in (
        {"GITLEAKS_CONFIG": str(permissive)},
        {"GITLEAKS_CONFIG_TOML": _PERMISSIVE_CONFIG},
    ):
        result = _run_range_scan(root, base, head, env_extra=env_extra)
        assert result.returncode == 1, f"{env_extra}: permissive config must not weaken the scan"


@requires_gitleaks
def test_scan_missing_config_fails_closed(tmp_path: Path) -> None:
    root, base, head = _secret_repo(tmp_path)
    env = dict(os.environ)
    env.pop("GITLEAKS_CONFIG", None)
    env.pop("GITLEAKS_CONFIG_TOML", None)
    result = subprocess.run(
        [
            "gitleaks",
            "git",
            "--redact",
            "--no-banner",
            "--config",
            str(root / "absent.toml"),
            f"--log-opts={base}..{head}",
            ".",
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_missing_scanner_fails_closed(tmp_path: Path) -> None:
    """With no gitleaks on PATH the shell reports 127 rather than passing."""
    bash = shutil.which("bash")
    assert bash is not None
    env = dict(os.environ)
    env["PATH"] = str(tmp_path)  # no gitleaks here
    result = subprocess.run(
        [bash, "-c", "gitleaks git --redact --no-banner ."],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 127


@requires_gitleaks
def test_unresolvable_range_is_a_silent_pass(tmp_path: Path) -> None:
    """gitleaks exits 0 on an unresolvable ``--log-opts`` range.

    The scanner itself cannot be the fail-closed boundary for a moving or
    malformed range; the workflow's ``git merge-base``/SHA comparisons are what
    reject it, so this test pins both halves of that contract.
    """
    root, _base, head = _secret_repo(tmp_path)
    result = _run_range_scan(root, "0" * 40, head)
    assert result.returncode == 0, result.stderr + result.stdout
    merge = subprocess.run(
        ["git", "-C", str(root), "merge-base", "0" * 40, head],
        check=False,
        capture_output=True,
        text=True,
    )
    assert merge.returncode != 0
