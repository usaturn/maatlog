"""Worker-local shared Sphinx build cache for integration tests (issue #364).

Successful builds are reused only inside one pytest-xdist worker: each test
process gets a fresh ``BuiltProjects`` root under its own basetemp, so nothing
is shared between workers or between pytest invocations.
"""

from __future__ import annotations

import os
from collections import Counter, OrderedDict
from enum import IntEnum, StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest
from conftest import ProjectFactory
from fixtures.integration_builds import BuiltProject, BuiltProjects, make_build_key

if TYPE_CHECKING:
    from collections.abc import Callable

FILES = {"about.rst": "About\n=====\n\nShared fixture probe.\n"}


def empty_build(root: Path) -> BuiltProject:
    srcdir, outdir, doctreedir = root / "source", root / "output", root / "doctrees"
    for path in (srcdir, outdir, doctreedir):
        path.mkdir(parents=True, exist_ok=True)
    (outdir / "about.html").write_text("<p>probe</p>", encoding="utf-8")
    return BuiltProject(
        root=root,
        srcdir=srcdir,
        outdir=outdir,
        doctreedir=doctreedir,
        builder="html",
        warnings="",
        stdout="",
        stderr="",
        returncode=0,
        manifest=MappingProxyType({}),
        images=MappingProxyType({}),
    )


def fail_build(root: Path) -> BuiltProject:
    raise RuntimeError("boom")


def test_same_key_builds_once(tmp_path: Path) -> None:
    calls: list[Path] = []

    def build(root: Path) -> BuiltProject:
        calls.append(root)
        return empty_build(root)

    sites = BuiltProjects(tmp_path)
    key = make_build_key(route="inprocess", files=FILES)
    first = sites.get(key, build)
    assert sites.get(key, build) is first
    assert len(calls) == 1
    assert first.html("about.html").text == "<p>probe</p>"


def test_failure_is_not_cached(tmp_path: Path) -> None:
    calls: list[Path] = []

    def build(root: Path) -> BuiltProject:
        calls.append(root)
        if len(calls) == 1:
            (root / "partial").write_text("bad", encoding="utf-8")
            raise RuntimeError("injected build failure")
        return empty_build(root)

    sites = BuiltProjects(tmp_path)
    key = make_build_key(route="inprocess", files=FILES)
    with pytest.raises(RuntimeError, match="injected build failure"):
        sites.get(key, build)
    assert not calls[0].exists()
    result = sites.get(key, build)
    assert len(calls) == 2 and calls[0] != calls[1]
    assert result.html("about.html").text == "<p>probe</p>"


def test_content_and_scalar_types_select_distinct_keys() -> None:
    first = make_build_key(route="inprocess", files=FILES, config={"flag": True})
    assert first != make_build_key(route="inprocess", files=FILES, config={"flag": 1})
    assert first != make_build_key(route="inprocess", files=FILES, config={"flag": 1.0})
    assert first != make_build_key(route="inprocess", files={"about.rst": b"About\n"}, config={"flag": True})
    assert first != make_build_key(route="subprocess", files=FILES, config={"flag": True})
    assert first != make_build_key(route="inprocess", files=FILES, builder="dirhtml", config={"flag": True})
    assert make_build_key(route="inprocess", files=FILES, config={"flag": 0.0}) != make_build_key(
        route="inprocess", files=FILES, config={"flag": -0.0}
    )
    with pytest.raises(TypeError):
        make_build_key(route="inprocess", files=FILES, config={"callback": object()})


def test_key_distinguishes_file_content_and_set() -> None:
    base = make_build_key(route="inprocess", files={"a.rst": "A\n=\n", "b.rst": "B\n=\n"})
    same = make_build_key(route="inprocess", files={"b.rst": "B\n=\n", "a.rst": "A\n=\n"})
    assert base == same
    assert base != make_build_key(route="inprocess", files={"a.rst": "A\n=\n"})
    assert base != make_build_key(route="inprocess", files={"a.rst": "A2\n=\n", "b.rst": "B\n=\n"})
    assert base != make_build_key(route="inprocess", files={"a.rst": "A\n=\n", "c.rst": "B\n=\n"})
    assert make_build_key(route="inprocess", files={"a.rst": "A\n=\n"}) != make_build_key(
        route="inprocess", files={"a.rst": b"A\n=\n"}
    )


def test_key_distinguishes_config_shape_and_order() -> None:
    base = make_build_key(
        route="inprocess",
        files=FILES,
        config={"outer": {"inner": [1, 2]}, "alpha": 1, "beta": 2},
        extensions=["a_ext", "b_ext"],
    )
    assert base == make_build_key(
        route="inprocess",
        files=FILES,
        config={"beta": 2, "alpha": 1, "outer": {"inner": [1, 2]}},
        extensions=["a_ext", "b_ext"],
    )
    assert base != make_build_key(
        route="inprocess",
        files=FILES,
        config={"outer": {"inner": [2, 1]}, "alpha": 1, "beta": 2},
        extensions=["a_ext", "b_ext"],
    )
    assert base != make_build_key(
        route="inprocess",
        files=FILES,
        config={"outer": {"inner": (1, 2)}, "alpha": 1, "beta": 2},
        extensions=["a_ext", "b_ext"],
    )
    assert base != make_build_key(
        route="inprocess",
        files=FILES,
        config={"outer": {"inner": [1, 2]}, "alpha": 1, "beta": 2},
        extensions=["b_ext", "a_ext"],
    )
    with pytest.raises(TypeError, match="not stable"):
        make_build_key(route="inprocess", files=FILES, config={"p": Path("x")})
    assert make_build_key(route="inprocess", files=FILES, conf_py_prefix="# a") != make_build_key(
        route="inprocess", files=FILES, conf_py_prefix="# b"
    )
    assert make_build_key(route="inprocess", files=FILES, source_date_epoch="1") != make_build_key(
        route="inprocess", files=FILES, source_date_epoch="2"
    )
    assert make_build_key(route="inprocess", files=FILES, theme="a") != make_build_key(
        route="inprocess", files=FILES, theme="b"
    )
    assert make_build_key(route="inprocess", files=FILES, config={"tags": {1, 2}}) == make_build_key(
        route="inprocess", files=FILES, config={"tags": {2, 1}}
    )
    assert make_build_key(route="inprocess", files=FILES, config={"tags": frozenset({1, 2})}) == make_build_key(
        route="inprocess", files=FILES, config={"tags": frozenset({2, 1})}
    )
    assert make_build_key(route="inprocess", files=FILES, config={"tags": {1, 2}}) != make_build_key(
        route="inprocess", files=FILES, config={"tags": frozenset({1, 2})}
    )
    with pytest.raises(TypeError):
        make_build_key(route="inprocess", files=FILES, config={"bad": float("nan")})
    with pytest.raises(TypeError):
        make_build_key(route="inprocess", files=FILES, config={1: "non-str-key"})  # type: ignore[arg-type]


def test_config_rejects_non_builtin_subtypes() -> None:
    """Builtin subtypes must hit TypeError instead of sharing a key with equal builtins."""

    class StrAxis(StrEnum):
        CATEGORY = "category"

    class IntLevel(IntEnum):
        LOW = 1

    class CustomFloat(float): ...

    class CustomList(list[object]): ...

    class CustomTuple(tuple[object, ...]): ...

    class CustomSet(set[object]): ...

    unstable_values: tuple[object, ...] = (
        StrAxis.CATEGORY,
        IntLevel.LOW,
        CustomFloat(1.5),
        CustomList([1]),
        CustomTuple((1,)),
        CustomSet({1, 2}),
        {1: 0, 2: 0}.keys(),
        {1: 0, 2: 0}.items(),
        Counter({"a": 1}),
        OrderedDict({"a": 1}),
        MappingProxyType({"a": 1}),
    )
    for value in unstable_values:
        with pytest.raises(TypeError, match="not stable"):
            make_build_key(route="inprocess", files=FILES, config={"v": value})
    with pytest.raises(TypeError, match="not stable"):
        make_build_key(route="inprocess", files=FILES, config={"outer": {"inner": StrAxis.CATEGORY}})
    with pytest.raises(TypeError, match="keys must be strings"):
        make_build_key(route="inprocess", files=FILES, config={StrAxis.CATEGORY: 1})  # type: ignore[dict-item]


def test_config_accepts_top_level_mapping() -> None:
    wrapped = MappingProxyType({"x": 1})
    assert make_build_key(route="inprocess", files=FILES, config=wrapped) == make_build_key(
        route="inprocess", files=FILES, config={"x": 1}
    )


def test_config_rejects_paths_before_shared_build(tmp_path: Path) -> None:
    class CustomPath(type(Path())):
        pass

    with pytest.raises(TypeError, match="not stable"):
        make_build_key(route="inprocess", files=FILES, config={"p": CustomPath("x")})
    with pytest.raises(TypeError, match="not stable"):
        BuiltProjects(tmp_path).project(files=FILES, config={"probe_path": Path("x")})
    assert not list(tmp_path.iterdir())


_KEY_COLLISION_FILES = {"about.rst": "About\n=====\n\n|probe|\n"}

_KEY_COLLISION_CONF_PREFIX = """\
def setup(app):
    value = app.config.html_context["probe"]
    app.config.rst_prolog = (
        ".. |probe| replace:: " + type(value).__name__ + ":" + repr(value) + "\\n"
    )
"""


@pytest.mark.parametrize(
    ("first_value", "second_value"),
    [
        pytest.param({1, 2}, frozenset({1, 2}), id="set-vs-frozenset"),
        pytest.param(0.0, -0.0, id="signed-zero"),
    ],
)
def test_project_builds_distinct_results_for_colliding_config_values(
    tmp_path: Path, first_value: object, second_value: object
) -> None:
    """Values that used to freeze to one key must not share a single build."""
    sites = BuiltProjects(tmp_path)
    first = sites.project(
        files=_KEY_COLLISION_FILES,
        config={"html_context": {"probe": first_value}},
        conf_py_prefix=_KEY_COLLISION_CONF_PREFIX,
    )
    second = sites.project(
        files=_KEY_COLLISION_FILES,
        config={"html_context": {"probe": second_value}},
        conf_py_prefix=_KEY_COLLISION_CONF_PREFIX,
    )
    assert second is not first
    assert f"{type(first_value).__name__}:{first_value!r}" in first.html("about.html")
    assert f"{type(second_value).__name__}:{second_value!r}" in second.html("about.html")


def test_project_result_is_read_only_and_restores_epoch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1234567890")
    sites = BuiltProjects(tmp_path)
    first = sites.project(files=FILES)
    assert sites.project(files=dict(FILES)) is first
    assert "Shared fixture probe." in first.html("about.html").text
    assert os.environ["SOURCE_DATE_EPOCH"] == "1234567890"
    assert not hasattr(first, "app")
    assert not hasattr(first, "build")
    with pytest.raises(TypeError):
        first.images["bad"] = "bad"  # type: ignore[index]
    with pytest.raises(TypeError):
        first.manifest["bad"] = "bad"  # type: ignore[index]


def test_project_restores_unset_epoch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    sites = BuiltProjects(tmp_path)
    sites.project(files=FILES)
    assert "SOURCE_DATE_EPOCH" not in os.environ


def test_project_env_restored_and_failure_not_cached_when_build_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1234567890")
    sites = BuiltProjects(tmp_path)
    with pytest.raises(Exception, match="injected conf failure"):
        sites.project(files=FILES, conf_py_prefix="raise ValueError('injected conf failure')")
    assert os.environ["SOURCE_DATE_EPOCH"] == "1234567890"
    with pytest.raises(Exception, match="injected conf failure"):
        sites.project(files=FILES, conf_py_prefix="raise ValueError('injected conf failure')")


def test_caller_config_and_files_are_not_mutated(tmp_path: Path) -> None:
    files = dict(FILES)
    config = {"author": "caller"}
    sites = BuiltProjects(tmp_path)
    result = sites.project(files=files, config=config)
    assert files == FILES
    assert config == {"author": "caller"}
    conf = (result.srcdir / "conf.py").read_text(encoding="utf-8")
    assert "html_theme" in conf


def test_project_route_writes_same_conf_py_as_independent_route(
    make_project: ProjectFactory, built_projects: BuiltProjects
) -> None:
    """Shared and independent routes must merge defaults into identical conf.py."""
    config = {"html_baseurl": "https://docs.example.test/"}
    shared = built_projects.project(files=FILES, config=config, theme="maatlog-base")
    independent = make_project(files=FILES, config=config, theme="maatlog-base")
    shared_conf = (shared.srcdir / "conf.py").read_text(encoding="utf-8")
    independent_conf = (independent.srcdir / "conf.py").read_text(encoding="utf-8")
    assert shared_conf == independent_conf


def test_separate_managers_do_not_share(tmp_path: Path) -> None:
    first = BuiltProjects(tmp_path / "a")
    second = BuiltProjects(tmp_path / "b")
    key = make_build_key(route="inprocess", files=FILES)
    one = first.get(key, empty_build)
    two = second.get(key, empty_build)
    assert one is not two
    assert one.root != two.root


def test_real_runs_cli_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fixtures.responsive_real_build import RealProject

    calls = 0
    real_build = RealProject.build

    def counted(self: RealProject, *args: object, **kwargs: object):  # noqa: ANN202
        nonlocal calls
        calls += 1
        return real_build(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(RealProject, "build", counted)
    sites = BuiltProjects(tmp_path)
    first = sites.real(post_count=3)
    assert sites.real(post_count=3) is first
    assert calls == 1
    assert first.returncode == 0
    assert list((first.outdir / "_images" / "maatlog").glob("*.jpg"))


def test_real_failure_is_not_cached_and_keeps_stderr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fixtures.responsive_real_build import RealProject

    calls = 0
    real_build = RealProject.build

    def counted(self: RealProject, *args: object, **kwargs: object):  # noqa: ANN202
        nonlocal calls
        calls += 1
        return real_build(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(RealProject, "build", counted)
    sites = BuiltProjects(tmp_path)
    for _ in range(2):
        with pytest.raises(RuntimeError, match="maatlog.config.invalid"):
            sites.real(post_count=3, config={"maatlog_responsive_image_widths": (0,)})
    assert calls == 2


def test_get_rejects_results_outside_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()

    def bad_build(root: Path) -> BuiltProject:
        result = empty_build(root)
        return BuiltProject(
            root=root,
            srcdir=outside,
            outdir=result.outdir,
            doctreedir=result.doctreedir,
            builder=result.builder,
            warnings="",
            stdout="",
            stderr="",
            returncode=0,
            manifest=result.manifest,
            images=result.images,
        )

    sites = BuiltProjects(tmp_path / "cache")
    key = make_build_key(route="inprocess", files=FILES)
    with pytest.raises(ValueError, match="outside"):
        sites.get(key, bad_build)


def test_get_requires_build_callback(tmp_path: Path) -> None:
    sites = BuiltProjects(tmp_path)
    key = make_build_key(route="inprocess", files=FILES)
    callback: Callable[[Path], BuiltProject] = fail_build
    with pytest.raises(RuntimeError, match="boom"):
        sites.get(key, callback)


_PROBE = """\
import json
import os
from pathlib import Path

import pytest
from fixtures.integration_builds import BuiltProjects

LOG_DIR = Path(os.environ["PROBE_LOG_DIR"])

FILES = {"about.rst": "About\\n=====\\n\\nWorker-locality probe.\\n"}


@pytest.fixture(scope="session")
def probe_projects(tmp_path_factory: pytest.TempPathFactory) -> BuiltProjects:
    return BuiltProjects(tmp_path_factory.mktemp("probe-builds"))


def _record(projects: BuiltProjects) -> None:
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    built = projects.project(files=FILES)
    entry = {"worker": worker, "root": str(built.root), "outdir": str(built.outdir)}
    with (LOG_DIR / f"{worker}.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry) + "\\n")


@pytest.mark.xdist_group("probe-shared")
def test_probe_first(probe_projects: BuiltProjects) -> None:
    _record(probe_projects)


@pytest.mark.xdist_group("probe-shared")
def test_probe_second(probe_projects: BuiltProjects) -> None:
    _record(probe_projects)
"""


def test_xdist_group_shares_one_build_inside_one_worker(tmp_path: Path) -> None:
    """Two same-group tests must land on one worker and share one result."""
    import json
    import subprocess
    import sys

    log_dir = tmp_path / "probe-logs"
    log_dir.mkdir()
    probe = tmp_path / "test_probe_shared.py"
    probe.write_text(_PROBE, encoding="utf-8")
    env = os.environ | {"PROBE_LOG_DIR": str(log_dir)}
    repo = Path(__file__).parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(repo / "pyproject.toml"),
            str(probe),
            "-n",
            "2",
            "--dist",
            "loadgroup",
            "-q",
        ],
        env=env,
        capture_output=True,
        text=True,
        cwd=repo,
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    logs = list(log_dir.glob("*.jsonl"))
    assert len(logs) == 1
    records = [json.loads(line) for line in logs[0].read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert len({record["root"] for record in records}) == 1
    assert len({record["outdir"] for record in records}) == 1
