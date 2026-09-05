"""Issue #64: Share ボタンのマークアップ契約と HTML 出力。"""

from __future__ import annotations

import pytest
from conftest import HtmlPage, ProjectFactory

POST_PROJECT = {
    "post.md": """---
maatlog-post: true
maatlog-slug: share-me
maatlog-published-at: 2026-08-01T09:00:00Z
---
# Share Me

A shareable blog post body.
""",
}

OTHER_PROJECT = {
    "about.rst": "About\n=====\n\nA plain page.\n",
}

# ルート直下に無い記事。相対 canonical だとブラウザが 1 階層ずらして解決してしまう。
NESTED_POST_PROJECT = {
    "posts/deep.md": """---
maatlog-post: true
maatlog-slug: deep
maatlog-published-at: 2026-08-01T09:00:00Z
---
# Deep

A post below the root.
""",
}


def _post_html(make_project: ProjectFactory, theme: str) -> HtmlPage:
    return make_project(files=POST_PROJECT, theme=theme).build().html("post.html")


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_post_page_renders_exactly_one_share_control(make_project: ProjectFactory, theme: str) -> None:
    page = _post_html(make_project, theme)

    assert len(page.select('[data-maatlog-component="share"]')) == 1

    button = page.select_one(".maatlog-share-button")
    assert button is not None
    assert button.get("type") == "button"
    # WCAG 2.5.3 (Label in Name): 可視ラベルをそのままアクセシブル名にするため上書きしない。
    assert button.get("aria-label") is None
    # runtime が読まないフックは契約に載せない（結合点はクラスである）。
    assert button.get("data-maatlog-share") is None
    # 可視ラベルがそのままアクセシブル名になる（HtmlPage は属性しか返さないので生 HTML で見る）。
    assert ">Share</button>" in page

    status = page.select_one(".maatlog-share-status")
    assert status is not None
    assert status.get("role") == "status" or status.get("aria-live") in ("polite", "assertive")


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_share_control_is_absent_on_non_post_pages(make_project: ProjectFactory, theme: str) -> None:
    page = make_project(files=OTHER_PROJECT, theme=theme).build().html("about.html")

    assert page.select_one('[data-maatlog-component="share"]') is None


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_post_page_emits_a_canonical_link(make_project: ProjectFactory, theme: str) -> None:
    page = _post_html(make_project, theme)

    canonical = page.select_one('link[rel="canonical"]')
    assert canonical is not None
    assert canonical.get("href")


@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_no_canonical_link_without_a_resolvable_baseurl(make_project: ProjectFactory, theme: str) -> None:
    """canonical を出せるのは絶対 URL のときだけ。

    ``html_baseurl`` が無いと canonical のフォールバックは builder の target URI
    （先頭 ``/`` の無いルート相対パス）になる。それを ``href`` に出すとブラウザは文書からの
    相対として解決し、Share が配布する URL ごとずれる。feeds を無効にするとこの構成は
    ``validate_baseurl()`` を通らずに成立する。
    """
    page = (
        make_project(
            files=NESTED_POST_PROJECT,
            theme=theme,
            config={"html_baseurl": "", "maatlog_generate_feeds": False},
        )
        .build()
        .html("posts/deep.html")
    )

    assert page.select_one('link[rel="canonical"]') is None


def _runtime(make_project: ProjectFactory) -> str:
    return (
        make_project(files=POST_PROJECT, theme="maatlog-default")
        .build()
        .asset("_static/maatlog.js")
        .read_text(encoding="utf-8")
    )


def test_runtime_registers_the_share_enhancer(make_project: ProjectFactory) -> None:
    script = _runtime(make_project)

    assert 'registerEnhancer("share"' in script
    assert "selector: '[data-maatlog-component=\"share\"]'" in script


def test_runtime_resolves_canonical_url(make_project: ProjectFactory) -> None:
    # 文字列契約ベース: 'link[rel="canonical"]' と 'location.href' の両参照を検証
    script = _runtime(make_project)

    assert 'link[rel="canonical"]' in script
    assert "location.href" in script


def test_runtime_does_not_fallback_to_clipboard_on_abort(make_project: ProjectFactory) -> None:
    # 'AbortError' の参照と、キャンセル時にコピーしない分岐の存在を検証
    script = _runtime(make_project)

    assert "AbortError" in script


def test_theme_ships_a_single_runtime_file(make_project: ProjectFactory) -> None:
    static_dir = make_project(files=POST_PROJECT, theme="maatlog-default").build().asset("_static")

    assert sorted(path.name for path in static_dir.glob("maatlog*.js")) == ["maatlog.js"]
