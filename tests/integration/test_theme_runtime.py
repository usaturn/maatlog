"""テーマ JavaScript の配信契約。"""

from __future__ import annotations

import re

import pytest
from conftest import ProjectFactory

RUNTIME_PROJECT = {
    "about.rst": "About\n=====\n\nA plain page.\n",
}


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_official_themes_ship_the_theme_javascript(make_project: ProjectFactory, theme: str) -> None:
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()

    assert result.asset("_static/maatlog.js").exists()


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_is_render_blocking_in_the_head(make_project: ProjectFactory, theme: str) -> None:
    # 保存済みテーマを初期描画前に反映するため、defer も module もあってはならない。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    page = result.html("about.html")
    head = page.text[: page.text.index("</head>")]

    match = re.search(r"<script src=\"([^\"]*maatlog\.js[^\"]*)\"\s*>\s*</script>", head)
    assert match is not None, "maatlog.js の <script> が head にない"
    assert "defer" not in match.group(0)
    assert "async" not in match.group(0)
    assert "type=" not in match.group(0)


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_url_carries_a_cache_busting_version(make_project: ProjectFactory, theme: str) -> None:
    from maatlog.version import PACKAGE_VERSION

    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()

    assert f"_static/maatlog.js?v={PACKAGE_VERSION}" in result.html("about.html").text


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_runs_before_the_pygments_dark_link_is_needed(
    make_project: ProjectFactory, theme: str
) -> None:
    # JS は #pygments_dark_css の media を書き換える。link が script より前にあること。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    text = result.html("about.html").text

    assert text.index("pygments_dark_css") < text.index("maatlog.js")


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_marks_the_document_and_resolves_the_theme(make_project: ProjectFactory, theme: str) -> None:
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")

    assert 'classList.add("maatlog-js")' in script
    assert "maatlog-theme" in script
    assert "pygments_dark_css" in script


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_marks_the_toc_heading_in_view(make_project: ProjectFactory, theme: str) -> None:
    # TOC の現在位置は aria-current="true" で表す（Sidebar の "page" とは別の意味）。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")

    assert ".maatlog-toc-headings" in script
    assert "aria-current" in script
    assert "IntersectionObserver" in script


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_toc_scrollspy_is_progressive_enhancement(make_project: ProjectFactory, theme: str) -> None:
    # IntersectionObserver が無い環境では何もせずに戻る。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")

    assert 'typeof IntersectionObserver !== "function"' in script


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_exposes_one_enhancer_registry(make_project: ProjectFactory, theme: str) -> None:
    # 機能ごとに独自の初期化機構を作らせないための共有 registry（tmp/FRONTEND.md）。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")

    assert "function registerEnhancer(" in script
    assert "function enhance(" in script
    assert "window.maatlog" in script
    assert 'registerEnhancer("toc-scrollspy"' in script
    assert 'registerEnhancer("theme-toggle"' in script


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_enhancers_are_applied_at_most_once_per_element(make_project: ProjectFactory, theme: str) -> None:
    # WeakSet で適用済みを覚える。data-* マーカーは取得 HTML に残留しうるので使わない。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")

    assert "new WeakSet()" in script


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_the_theme_ships_exactly_one_runtime_script(make_project: ProjectFactory, theme: str) -> None:
    # tmp/FRONTEND.md: 機能別 script を独立ロードしない。runtime は maatlog.js 一本。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    text = result.html("about.html").text

    assert len(re.findall(r"<script[^>]*maatlog[^>]*\.js", text)) == 1


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_the_theme_ships_no_other_javascript(make_project: ProjectFactory, theme: str) -> None:
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    static = result.asset("_static")

    assert sorted(path.name for path in static.glob("maatlog*.js")) == ["maatlog.js"]


def test_theme_conf_does_not_add_script_files() -> None:
    # theme.conf の script_files で追加ロードすると同じ runtime が二重に走る。
    from pathlib import Path

    import maatlog

    theme_root = Path(maatlog.__file__).resolve().parent / "themes" / "maatlog-base"

    assert "script_files" not in (theme_root / "theme.conf").read_text(encoding="utf-8")


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_loads_the_next_archive_page(make_project: ProjectFactory, theme: str) -> None:
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")

    assert 'registerEnhancer("infinite-scroll"' in script
    assert '[data-maatlog-component="archive"]' in script
    # rel="next" は .maatlog-pagination-more にも付く。クラスで引く。
    assert ".maatlog-pagination-next" in script
    assert "DOMParser" in script
    assert "maatlog-infinite-sentinel" in script


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_loaded_posts_are_announced_politely(make_project: ProjectFactory, theme: str) -> None:
    # 自動追加はフォーカスを動かさない。読み上げは aria-live に任せる。
    # （モバイル Sidebar など別 enhancer のフォーカス管理は対象外）
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")
    start = script.index("function enhanceInfiniteScroll")
    end = script.index('registerEnhancer("infinite-scroll"')
    infinite = script[start:end]

    assert "maatlog-infinite-status" in script
    assert '"aria-live", "polite"' in script
    assert '"role", "status"' in script
    assert ".focus()" not in infinite


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_appended_cards_go_through_the_same_registry(make_project: ProjectFactory, theme: str) -> None:
    # 追加カードにも登録済み enhancer が当たり、他機能が購読できるイベントが出る。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")

    assert "enhance(card)" in script
    assert "maatlog:content-added" in script


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_prefetches_likely_next_pages(make_project: ProjectFactory, theme: str) -> None:
    # Issue #66: Prefetch は単一 runtime 内の enhancer。機能別 script は増やさない。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")

    assert 'registerEnhancer("prefetch"' in script
    assert ".maatlog-nav-newer" in script
    assert ".maatlog-nav-older" in script
    assert ".maatlog-pagination-next" in script
    assert 'rel", "prefetch"' in script or 'rel = "prefetch"' in script or 'rel="prefetch"' in script
    assert "saveData" in script
    assert "mouseenter" in script
    assert "focusin" in script
    assert "maatlog:content-added" in script


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_marks_new_posts(make_project: ProjectFactory, theme: str) -> None:
    # Issue #62: NEW 表示は単一 runtime の enhancer。機能別 script は増やさない。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")

    assert 'registerEnhancer("new-posts"' in script
    # 機械可読属性から公開日時を読む
    assert "maatlog-published-at" in script
    # localStorage に前回訪問を保存する
    assert "maatlog:last-visit" in script
    # localStorage が使えなくても壊れない（session baseline のキャッシュキーで containment を確認）
    assert "maatlog:session-baseline" in script
    # NEW バッジのクラス
    assert "maatlog-new-badge" in script


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_filters_archive_cards(make_project: ProjectFactory, theme: str) -> None:
    # Issue #60: アーカイブ絞り込みは単一 runtime の enhancer。機能別 script は増やさない。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")

    assert 'registerEnhancer("archive-filter"' in script
    assert "data-maatlog-tags" in script
    assert "maatlog:content-added" in script
    assert "maatlog-archive-empty-filtered" in script


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_theme_javascript_opens_mobile_sidebar(make_project: ProjectFactory, theme: str) -> None:
    # Issue #65: モバイル Sidebar は単一 runtime の enhancer。機能別 script は増やさない。
    result = make_project(files=RUNTIME_PROJECT, theme=theme).build()
    script = result.asset("_static/maatlog.js").read_text(encoding="utf-8")

    assert 'registerEnhancer("mobile-sidebar"' in script
    assert "data-maatlog-toggle" in script
    assert "maatlog-sidebar-open" in script
    assert "maatlog-sidebar-backdrop" in script
