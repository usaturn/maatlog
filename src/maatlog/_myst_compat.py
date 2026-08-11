"""Narrow compatibility adapter for typed MyST 5.1 front matter."""

from collections.abc import Callable, Mapping
from importlib import import_module
from typing import Protocol, cast

from myst_parser.config.main import TopmatterReadError, read_topmatter


class _Mark(Protocol):
    line: int


class _ScalarNode(Protocol):
    value: object
    start_mark: _Mark


class _MappingNode(Protocol):
    value: list[tuple[_ScalarNode, object]]


class _YamlModule(Protocol):
    compose: Callable[[str], object | None]


class _MySTRendererModule(Protocol):
    yaml: _YamlModule


def read_typed_frontmatter(source: str) -> dict[str, tuple[object, int]] | None:
    """Return MyST front matter values and one-based key lines.

    ``read_topmatter`` is MyST's own typed loader. MyST's renderer module owns
    the YAML implementation used to turn the same payload into marked nodes;
    keeping that access here prevents MaatLog from importing transitive PyYAML
    directly and gives diagnostics the parser's key marks.
    """

    try:
        topmatter = read_topmatter(source)
    except TopmatterReadError:
        return None
    if topmatter is None:
        return None

    payload = _frontmatter_payload(source)
    renderer = cast(_MySTRendererModule, cast(object, import_module("myst_parser.mdit_to_docutils.base")))
    root = renderer.yaml.compose(payload)
    key_lines = _mapping_key_lines(root)
    typed = cast(Mapping[object, object], topmatter)
    return {
        key: (value, key_lines.get(key, 1))
        for key, value in typed.items()
        if isinstance(key, str) and key.startswith("maatlog-")
    }


def _frontmatter_payload(source: str) -> str:
    lines = source.splitlines()
    if not lines or not lines[0].startswith("---"):
        return ""
    payload: list[str] = []
    for line in lines[1:]:
        if line.startswith(("---", "...")):
            break
        payload.append(line)
    return "\n".join(payload) + ("\n" if payload else "")


def _mapping_key_lines(root: object | None) -> dict[str, int]:
    if root is None or not hasattr(root, "value"):
        return {}
    mapping = cast(_MappingNode, root)
    lines: dict[str, int] = {}
    for key_node, _ in mapping.value:
        if isinstance(key_node.value, str):
            # The payload begins on source line 2, while parser marks are zero-based.
            lines[key_node.value] = key_node.start_mark.line + 2
    return lines
