from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]

EXPECTED_DEV_DEPENDENCIES = {
    "@eslint/js": "10.0.1",
    "axe-core": "4.13.0",
    "browserslist": "4.28.8",
    "eslint": "10.9.1",
    "eslint-plugin-compat": "7.0.2",
    "globals": "17.11.0",
    "prettier": "3.9.6",
    "stylelint": "17.14.1",
    "stylelint-config-standard": "40.0.0",
    "typescript": "7.0.2",
}


def _json(relative: str) -> dict[str, Any]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _is_ignored(relative: str) -> bool:
    completed = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", relative],
        cwd=ROOT,
        check=False,
    )
    assert completed.returncode in {0, 1}
    return completed.returncode == 0


def test_node_runtime_dependencies_and_lock_are_reproducible() -> None:
    assert (ROOT / ".nvmrc").read_text(encoding="utf-8") == "24\n"
    package = _json("package.json")
    assert package["private"] is True
    assert package["type"] == "module"
    assert package["engines"] == {"node": ">=24 <25"}
    assert package["devDependencies"] == EXPECTED_DEV_DEPENDENCIES

    lock = _json("package-lock.json")
    root_package = lock["packages"][""]
    assert root_package["engines"] == package["engines"]
    assert root_package["devDependencies"] == EXPECTED_DEV_DEPENDENCIES


def test_frontend_generated_files_are_ignored_but_lock_is_tracked() -> None:
    assert _is_ignored("node_modules/example/index.js")
    assert _is_ignored(".eslintcache")
    assert _is_ignored(".stylelintcache")
    assert not _is_ignored("package-lock.json")


EXPECTED_SCRIPTS = {
    "lint:js": (
        "eslint eslint.config.mjs prettier.config.mjs stylelint.config.mjs "
        '"src/maatlog/themes/**/*.js" --no-error-on-unmatched-pattern'
    ),
    "format:check": (
        "prettier --check package.json package-lock.json eslint.config.mjs "
        "prettier.config.mjs stylelint.config.mjs tsconfig.json "
        '"src/maatlog/themes/**/*.{js,css}"'
    ),
    "format": (
        "prettier --write package.json package-lock.json eslint.config.mjs "
        "prettier.config.mjs stylelint.config.mjs tsconfig.json "
        '"src/maatlog/themes/**/*.{js,css}"'
    ),
    "typecheck:js": "tsc --noEmit",
    "lint:css": 'stylelint "src/maatlog/themes/**/static/**/*.css"',
    "check": "npm run lint:js && npm run format:check && npm run typecheck:js && npm run lint:css",
}


def test_frontend_scripts_and_browser_policy_are_explicit() -> None:
    package = _json("package.json")
    assert package["scripts"] == EXPECTED_SCRIPTS
    assert package["browserslist"] == [
        "defaults",
        "not IE 11",
        "not op_mini all",
        "not kaios 2.5",
        "not and_uc 15.5",
        "not and_qq 14.9",
    ]


def test_typescript_checks_configs_and_future_product_javascript() -> None:
    config = _json("tsconfig.json")
    options = config["compilerOptions"]
    assert options["allowJs"] is True
    assert options["checkJs"] is True
    assert options["noEmit"] is True
    assert options["strict"] is True
    assert options["lib"] == ["ES2022", "DOM", "DOM.Iterable"]
    assert config["include"] == [
        "src/maatlog/themes/**/*.js",
        "eslint.config.mjs",
        "prettier.config.mjs",
        "stylelint.config.mjs",
    ]
