"""Table wrapper DOM contract: ``.maatlog-table-wrapper`` (Issue #202, Theme API 1.19)."""

from __future__ import annotations

import re
from io import StringIO
from pathlib import Path

import pytest
from conftest import ProjectFactory, SphinxFactory
from sphinx.application import Sphinx

from maatlog.builders import FULL_HTML_BUILDERS
from maatlog.table_layout import WRAPPER_CLASS

# docutils の starttag は属性をアルファベット順に出すため、開始タグ文字列は確定できる。
WRAPPER_START = f'<div class="{WRAPPER_CLASS}" tabindex="0">'
DOCUTILS_TABLE = re.compile(r'<table[^>]*class="[^"]*\bdocutils\b')
WRAPPED_TABLE = re.compile(re.escape(WRAPPER_START) + r'\n<table[^>]*class="[^"]*\bdocutils\b')

CONFIG: dict[str, object] = {"numfig": True}

TABLES_RST = """\
Tables
======

短い list-table。

.. list-table::
   :header-rows: 1

   * - 列A
     - 列B
     - 列C
   * - a1
     - b1
     - c1

caption・名前・列幅・配置を持つ表。

.. table:: 惑星一覧
   :name: tbl-planets
   :widths: 30 70
   :align: center

   ========  =====================
   Planet    Description
   ========  =====================
   Earth     Our home
   Mars      The red one
   ========  =====================

rowspan / colspan を持つ grid 表。

+------------------------+---------------------+
| Header 1               | Header 2            |
+========================+=====================+
| Spans two rows         | row 1, column 2     |
+                        +---------------------+
|                        | row 2, column 2     |
+------------------------+---------------------+
| Spans two columns                            |
+------------------------+---------------------+

csv-table。

.. csv-table:: CSV 一覧
   :header: "名前", "値"

   "alpha", "1"
   "beta", "2"

入れ子の表（セル内に list-table）。

.. list-table::
   :header-rows: 1

   * - 項目
     - 内容
   * - outer
     - .. list-table::
          :class: nested-inner

          * - inner-a
            - inner-b

hlist はレイアウト表（対象外）。

.. hlist::
   :columns: 2

   - 項目 1
   - 項目 2

引用文献（対象外）。参照 [CIT1]_。

.. [CIT1] 引用文献メモ。
"""

CODE_RST = """\
Code
====

caption なしコード。

.. code-block:: python

   print("hello")

caption 付きコード。

.. code-block:: python
   :caption: sample.py の抜粋

   print("captioned")

行番号付きコード（highlighttable は対象外）。

.. code-block:: python
   :linenos:

   print("line 1")
   print("line 2")

literalinclude（caption + 行番号）。

.. literalinclude:: _code/sample.py
   :language: python
   :caption: sample.py
   :linenos:

parsed-literal（非ハイライト経路）。

.. parsed-literal::

   plain *emphasized* text
"""

REFS_RST = """\
References
==========

名前付き表への :ref:`tbl-planets` と :numref:`tbl-planets`。
"""

MD_PAGE = """\
# MD ページ

| 列A | 列B |
| --- | --- |
| 1   | 2   |
"""

SAMPLE_PY = '''\
"""literalinclude 対象のサンプルモジュール。"""


def greet(name: str) -> str:
    """名前を挨拶に変換する。"""
    return f"hello {name}"
'''

WRAPPER_PROJECT: dict[str, str | bytes] = {
    "tables.rst": TABLES_RST,
    "code.rst": CODE_RST,
    "refs.rst": REFS_RST,
    "mdpage.md": MD_PAGE,
    "_code/sample.py": SAMPLE_PY,
}


def test_full_html_builders_constant_names_the_full_capability_tier() -> None:
    # transform の宣言的ゲートと builder_capability が同じ正本を共有する。
    assert FULL_HTML_BUILDERS == ("html", "dirhtml")

    from maatlog.table_layout import TableWrapperPostTransform

    assert TableWrapperPostTransform.builders == FULL_HTML_BUILDERS


def test_every_docutils_table_is_wrapped_exactly_once(make_project: ProjectFactory) -> None:
    page = make_project(files=WRAPPER_PROJECT, config=CONFIG).build().html("tables.html")

    assert page.text.count(WRAPPER_START) == 6
    assert len(DOCUTILS_TABLE.findall(page.text)) == 6
    assert len(WRAPPED_TABLE.findall(page.text)) == 6
    # 同じ表の二重ラップ禁止: wrapper 直後に wrapper が来てはならない。
    assert (WRAPPER_START + "\n" + WRAPPER_START) not in page.text


def test_wrapper_carries_keyboard_tabindex(make_project: ProjectFactory) -> None:
    page = make_project(files=WRAPPER_PROJECT, config=CONFIG).build().html("tables.html")

    wrappers = page.select(f".{WRAPPER_CLASS}")

    assert len(wrappers) == 6
    assert all(wrapper.get("tabindex") == "0" for wrapper in wrappers)


def test_caption_id_widths_and_align_stay_on_the_table(make_project: ProjectFactory) -> None:
    page = make_project(files=WRAPPER_PROJECT, config=CONFIG).build().html("tables.html")

    # docutils starttag は属性をアルファベット順（class → id）に出す。
    assert '<table class="docutils align-center" id="tbl-planets">' in page.text
    assert re.search(
        r'<table class="docutils align-center" id="tbl-planets">\s*<caption>',
        page.text,
    )
    assert "惑星一覧" in page.text
    # docutils 0.22 は colwidths を float で出力するため "30.0%" になる。
    assert 'col style="width: 30.0%"' in page.text  # :widths: 30 70 → colgroup
    assert 'rowspan="2"' in page.text
    assert 'colspan="2"' in page.text


def test_reference_and_numref_point_at_the_table_id(make_project: ProjectFactory) -> None:
    result = make_project(files=WRAPPER_PROJECT, config=CONFIG).build()

    refs = result.html("refs.html")

    # :ref: と :numref: の両方が <table> 側に残った id を指す。
    assert refs.text.count('href="tables.html#tbl-planets"') == 2


def test_nested_table_gets_its_own_wrapper(make_project: ProjectFactory) -> None:
    page = make_project(files=WRAPPER_PROJECT, config=CONFIG).build().html("tables.html")

    assert re.search(
        r"<td>\s*" + re.escape(WRAPPER_START) + r'\s*<table[^>]*class="[^"]*nested-inner',
        page.text,
    )


def test_myst_pipe_table_is_wrapped(make_project: ProjectFactory) -> None:
    page = make_project(files=WRAPPER_PROJECT, config=CONFIG).build().html("mdpage.html")

    assert page.text.count(WRAPPER_START) == 1
    assert len(WRAPPED_TABLE.findall(page.text)) == 1


def test_linenos_tables_and_parsed_literal_are_not_wrapped(make_project: ProjectFactory) -> None:
    page = make_project(files=WRAPPER_PROJECT, config=CONFIG).build().html("code.html")

    assert WRAPPER_START not in page.text
    # :linenos: の 2 ブロック分は出力された。Sphinx 9.1 は行番号を pre 内の
    # <span class="linenos"> で描画し、highlighttable の <table> を生成しない。
    assert page.text.count('class="linenos"') >= 2
    assert len(DOCUTILS_TABLE.findall(page.text)) == 0
    assert '<pre class="literal-block">' in page.text


def test_hlist_and_citation_do_not_add_wrappers(make_project: ProjectFactory) -> None:
    page = make_project(files=WRAPPER_PROJECT, config=CONFIG).build().html("tables.html")

    assert 'class="hlist"' in page.text
    assert "citation" in page.text
    # hlist / citation があっても wrapper は docutils 表 6 個分だけ。
    assert page.text.count(WRAPPER_START) == 6


PLAIN_TABLE_PROJECT: dict[str, str | bytes] = {
    "plain.rst": "Plain\n====\n\n.. list-table::\n\n   * - a\n     - b\n",
}

EXTRA_TABLE_RST = """
追加の表。

.. list-table::

   * - x
     - y
"""


def test_dirhtml_build_emits_the_same_wrappers(make_project: ProjectFactory) -> None:
    result = make_project(files=WRAPPER_PROJECT, config=CONFIG, builder="dirhtml").build()

    page = result.html("tables/index.html")

    assert page.text.count(WRAPPER_START) == 6
    assert len(WRAPPED_TABLE.findall(page.text)) == 6


def _build_singlehtml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, str]:
    """singlehtml は partial-support 警告を許容してビルドする（test_builders.py 前例）。"""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1785542400")
    root = tmp_path / "singlehtml"
    srcdir = root / "source"
    srcdir.mkdir(parents=True)
    files = {
        **WRAPPER_PROJECT,
        "index.rst": "Root\n====\n\n.. toctree::\n\n   tables\n   code\n   refs\n   mdpage\n",
    }
    conf_lines = [
        "extensions = ['maatlog']",
        "source_suffix = {'.rst': 'restructuredtext', '.md': 'markdown'}",
        "root_doc = 'index'",
        "html_theme = 'maatlog-default'",
        "html_baseurl = 'https://example.test/'",
        "numfig = True",
    ]
    (srcdir / "conf.py").write_text("\n".join(conf_lines) + "\n", encoding="utf-8")
    for name, content in files.items():
        target = srcdir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
    warning = StringIO()
    app = Sphinx(
        str(srcdir),
        str(srcdir),
        str(root / "output"),
        str(root / "doctrees"),
        "singlehtml",
        status=StringIO(),
        warning=warning,
        warningiserror=False,
        freshenv=True,
    )
    app.build()
    html = (root / "output" / "index.html").read_text(encoding="utf-8")
    return html, warning.getvalue()


def test_singlehtml_build_stays_unwrapped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html, warnings = _build_singlehtml(tmp_path, monkeypatch)

    assert WRAPPER_START not in html
    assert "<table" in html  # 表自体は従来どおり出力される
    for line in warnings.splitlines():
        if line.strip():
            # partial-support 以外の新しい警告を増やさない。
            # ただし同一プロセス内の先行ビルドが docutils にノード/ディレクティブ/
            # ロールを登録済みのため、各拡張（sphinx 内部・myst_parser・maatlog
            # 自身のノードも含む）の setup が "already registered" を発することがある
            # （順序依存のアンビエント警告。wrapper 機能の挙動とは無関係。
            # test_builders.py は statuscode のみ検証しこの警告を許容している）。
            # これら複数系譜の共通マーカ "already registered" で許容し、
            # partial-support 以外の新規警告（wrapper 由来など）は通さない。
            assert "maatlog.builder.partial-support" in line or "already registered" in line


def test_text_build_stays_unwrapped(make_sphinx: SphinxFactory) -> None:
    app = make_sphinx(files=PLAIN_TABLE_PROJECT, builder="text")
    app.build()

    texts = list(Path(app.outdir).rglob("*.txt"))

    assert texts
    assert all("maatlog-table-wrapper" not in text.read_text(encoding="utf-8") for text in texts)


def test_incremental_rebuilds_do_not_duplicate_wrappers(make_project: ProjectFactory) -> None:
    project = make_project(files=WRAPPER_PROJECT, config=CONFIG)
    project.build(reuse_environment=False)

    unchanged = project.build(reuse_environment=True)
    assert unchanged.html("tables.html").text.count(WRAPPER_START) == 6

    project.write("tables.rst", TABLES_RST + EXTRA_TABLE_RST)
    changed = project.build(reuse_environment=True)
    assert changed.html("tables.html").text.count(WRAPPER_START) == 7


def test_parallel_write_matches_serial(make_project: ProjectFactory) -> None:
    serial = make_project(files=WRAPPER_PROJECT, config=CONFIG).build()
    parallel = make_project(files=WRAPPER_PROJECT, config=CONFIG).build(parallel=2)

    for name in ("tables.html", "code.html", "mdpage.html", "refs.html"):
        assert serial.html(name).text == parallel.html(name).text


def test_base_theme_gets_the_wrapper_without_wrapper_css(make_project: ProjectFactory) -> None:
    result = make_project(files=WRAPPER_PROJECT, config=CONFIG, theme="maatlog-base").build()

    assert result.html("tables.html").text.count(WRAPPER_START) == 6
    # base CSS は無変更（Spec §4.5）。wrapper のスタイルは default テーマだけが持つ。
    css = result.asset("_static/maatlog.css").read_text(encoding="utf-8")
    assert WRAPPER_CLASS not in css


def _css_rule(css: str, selector: str) -> str:
    start = css.index(f"{selector} {{")
    return css[start : css.index("}", start) + 1]


def test_default_stylesheet_carries_the_wrapper_baseline(make_project: ProjectFactory) -> None:
    css = (
        make_project(files=PLAIN_TABLE_PROJECT, theme="maatlog-default")
        .build()
        .asset("_static/maatlog.css")
        .read_text(encoding="utf-8")
    )

    rule = _css_rule(css, ".maatlog-layout-main .maatlog-table-wrapper")
    assert "max-width: 100%" in rule
    assert "overflow-x: auto" in rule

    focus = _css_rule(css, ".maatlog-layout-main .maatlog-table-wrapper:focus-visible")
    assert "outline" in focus
