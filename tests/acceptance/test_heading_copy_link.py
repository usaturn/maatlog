"""Issue #59: 見出しリンク Copy の実ブラウザ挙動。

Clipboard API は実行環境次第で使えたり使えなかったりするので、
``page.add_init_script`` で ``navigator.clipboard`` をスタブし、
実呼び出しとその実引数を検証する。
"""

from __future__ import annotations

import pytest
from acceptance.server import serve_directory
from acceptance.site import AcceptanceSite
from playwright.sync_api import Browser, Page, expect, sync_playwright

# 記事ページ。canonical を持つ。
POST_PAGE = "posts/rst-post.html"
# 記事ではない通常ページ。h2 の permalink は昇格してはならない。
PLAIN_PAGE = "guide.html"

LABEL = "Copy link to this heading"

# h2 > h3 > h4 の入れ子を持つ記事へ差し替える。共有プロジェクトは汚さず、
# このテストのビルドにだけ効く（test_prefetch.py と同じ手法）。
EXTRA_POSTS: dict[str, str] = {
    "posts/rst-post.rst": (
        ":maatlog-post: true\n"
        ":maatlog-slug: rst-post\n"
        ":maatlog-published-at: 2026-08-10T12:00:00Z\n"
        ":maatlog-authors: alice\n"
        ":maatlog-excerpt: Nested headings for the copy-link acceptance tests.\n"
        "\n"
        "reStructuredText post\n"
        "=====================\n"
        "\n"
        "Body with nested headings.\n"
        "\n"
        "Level Two\n"
        "---------\n"
        "\n"
        "Two.\n"
        "\n"
        "Level Three\n"
        "~~~~~~~~~~~\n"
        "\n"
        "Three.\n"
        "\n"
        "Level Four\n"
        "^^^^^^^^^^\n"
        "\n"
        "Four.\n"
    )
}

# 実行時に window.__clipboardMode を切り替えられる Clipboard スタブ。
CLIPBOARD_STUB = """
(() => {
  window.__clipboardCalls = [];
  window.__clipboardMode = "resolve";
  const clipboard = {
    writeText: (text) => {
      window.__clipboardCalls.push(text);
      if (window.__clipboardMode === "reject") {
        return Promise.reject(new Error("clipboard denied"));
      }
      return Promise.resolve();
    },
  };
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    get: () => (window.__clipboardMode === "undefined" ? undefined : clipboard),
  });
})();
"""


def _new_page(browser: Browser) -> Page:
    page = browser.new_context().new_page()
    page.add_init_script(CLIPBOARD_STUB)
    return page


def _open_post(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}{POST_PAGE}", wait_until="load")
    # runtime が走り終わるまで待つ。昇格済みなら aria-label が置き換わっている。
    expect(page.locator(f'.maatlog-post-body h2 > a.headerlink[aria-label="{LABEL}"]').first).to_have_count(1)


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_h2_h3_h4_are_upgraded_and_h1_is_not(site: AcceptanceSite, theme: str) -> None:
    """受け入れ条件 1: h2 / h3 / h4 にコピー UI が付き、記事タイトル h1 には付かない。"""
    result = site.build("html", theme=theme, extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = _new_page(browser)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)

                for level in ("h2", "h3", "h4"):
                    anchor = page.locator(f".maatlog-post-body {level} > a.headerlink")
                    expect(anchor).to_have_count(1)
                    expect(anchor).to_have_attribute("aria-label", LABEL)
                    expect(anchor).to_have_attribute("title", LABEL)

                # 記事タイトルの h1 は昇格しない。Sphinx は文書タイトル (h1) に
                # headerlink を出さないため、件数ゼロであること自体が期待値。
                # 万が一 h1 に permalink が出る構成でも LABEL 付きはゼロのまま。
                h1 = page.locator(".maatlog-post-body h1 > a.headerlink")
                expect(h1).to_have_count(0)
                expect(page.locator(f'.maatlog-post-body h1 > a.headerlink[aria-label="{LABEL}"]')).to_have_count(0)
        finally:
            browser.close()


@pytest.mark.browser
def test_pages_outside_the_post_body_are_untouched(site: AcceptanceSite) -> None:
    """記事本文の外（通常ページ）の見出しは昇格しない。"""
    result = site.build("html", theme="maatlog-default", extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = _new_page(browser)
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{PLAIN_PAGE}", wait_until="load")
                expect(page.locator("a.headerlink")).not_to_have_count(0)
                expect(page.locator(f'a.headerlink[aria-label="{LABEL}"]')).to_have_count(0)
        finally:
            browser.close()


@pytest.mark.browser
def test_only_one_permalink_control_per_heading(site: AcceptanceSite) -> None:
    """受け入れ条件 4: 同一見出しに permalink UI が重複しない。"""
    result = site.build("html", theme="maatlog-default", extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = _new_page(browser)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)

                # 見出しの中の対話要素は permalink 1 つだけ。ボタンは増えていない。
                counts = page.evaluate(
                    "() => [...document.querySelectorAll('.maatlog-post-body :is(h2, h3, h4)')]"
                    ".map((h) => h.querySelectorAll('a, button').length)"
                )
                assert counts == [1, 1, 1], counts
                expect(page.locator(".maatlog-post-body :is(h2, h3, h4) button")).to_have_count(0)
        finally:
            browser.close()


@pytest.mark.browser
def test_without_javascript_the_permalink_still_links(site: AcceptanceSite) -> None:
    """受け入れ条件 7: JS 無効でも記事と既存アンカーは通常どおり。"""
    result = site.build("html", theme="maatlog-default", extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context(java_script_enabled=False).new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{POST_PAGE}", wait_until="load")

                anchor = page.locator(".maatlog-post-body h2 > a.headerlink")
                expect(anchor).to_have_count(1)
                expect(anchor).to_have_attribute("href", "#level-two")
                # 昇格していないので Sphinx 既定の title のまま、live region も無い。
                expect(anchor).to_have_attribute("title", "Link to this heading")
                expect(page.locator(".maatlog-copy-link-status")).to_have_count(0)
                expect(page.locator(".maatlog-post-body")).to_contain_text("Body with nested headings.")
        finally:
            browser.close()


def _wait_for_copy(page: Page) -> str:
    page.wait_for_function("() => window.__clipboardCalls.length > 0")
    value = page.evaluate("() => window.__clipboardCalls[0]")
    assert isinstance(value, str)
    return value


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_click_copies_the_canonical_url_with_the_section_anchor(site: AcceptanceSite, theme: str) -> None:
    """受け入れ条件 3: canonical URL + セクションアンカーをコピーする。"""
    result = site.build("html", theme=theme, extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = _new_page(browser)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                canonical = page.evaluate("() => document.querySelector('link[rel=canonical]').href")

                page.locator(".maatlog-post-body h3 > a.headerlink").click()

                assert _wait_for_copy(page) == f"{canonical}#level-three"
                # 既定動作は妨げない。アンカージャンプは従来どおり起きる。
                assert page.url.endswith("#level-three")
        finally:
            browser.close()


@pytest.mark.browser
def test_without_canonical_the_address_bar_url_is_used(site: AcceptanceSite) -> None:
    """受け入れ条件 3 の裏: canonical が無ければ location.href をベースにする。"""
    result = site.build("html", theme="maatlog-default", extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = _new_page(browser)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                page_url = page.url
                page.evaluate(
                    "() => { const l = document.querySelector('link[rel=canonical]'); if (l) { l.remove(); } }"
                )

                page.locator(".maatlog-post-body h2 > a.headerlink").click()

                assert _wait_for_copy(page) == f"{page_url}#level-two"
        finally:
            browser.close()


@pytest.mark.browser
def test_copied_url_never_carries_two_fragments(site: AcceptanceSite) -> None:
    """アンカー付き URL で開いた後でも、コピー URL の "#" は 1 個だけ。"""
    result = site.build("html", theme="maatlog-default", extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = _new_page(browser)
            with serve_directory(result.outdir) as base_url:
                # 別のアンカー付きで開く。location.href には既に "#" が入っている。
                page.goto(f"{base_url}{POST_PAGE}#level-four", wait_until="load")
                expect(page.locator(f'a.headerlink[aria-label="{LABEL}"]').first).to_have_count(1)
                page.evaluate(
                    "() => { const l = document.querySelector('link[rel=canonical]'); if (l) { l.remove(); } }"
                )

                page.locator(".maatlog-post-body h2 > a.headerlink").click()

                copied = _wait_for_copy(page)
                assert copied.count("#") == 1, copied
                assert copied.endswith("#level-two"), copied
        finally:
            browser.close()


@pytest.mark.browser
def test_copied_url_lands_on_the_section(site: AcceptanceSite) -> None:
    """受け入れ条件 2: コピーした URL のフラグメントで対象セクションへ移動する。"""
    result = site.build("html", theme="maatlog-default", extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = _new_page(browser)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                page.locator(".maatlog-post-body h4 > a.headerlink").click()
                fragment = _wait_for_copy(page).split("#")[1]

                # canonical は配信していないホストを指すので、同じ fragment を
                # ローカル配信 URL に付けて到達性を確かめる。
                page.goto(f"{base_url}{POST_PAGE}#{fragment}", wait_until="load")

                assert (
                    page.evaluate(
                        "() => { const t = document.getElementById(location.hash.slice(1));"
                        "  return t !== null && t.getBoundingClientRect().top < window.innerHeight; }"
                    )
                    is True
                )
        finally:
            browser.close()


@pytest.mark.browser
def test_modified_clicks_are_left_to_the_browser(site: AcceptanceSite) -> None:
    """修飾キー付きクリック（新規タブ等）はクリップボードを奪わない。"""
    result = site.build("html", theme="maatlog-default", extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = _new_page(browser)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)

                page.locator(".maatlog-post-body h2 > a.headerlink").click(modifiers=["ControlOrMeta"])

                page.wait_for_timeout(200)
                assert page.evaluate("() => window.__clipboardCalls.length") == 0
        finally:
            browser.close()


@pytest.mark.browser
def test_enhancing_twice_does_not_copy_twice(site: AcceptanceSite) -> None:
    """冪等性: enhance を呼び直してもリスナは 1 つのまま。"""
    result = site.build("html", theme="maatlog-default", extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = _new_page(browser)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                page.evaluate("() => window.maatlog.enhance(document)")
                page.evaluate("() => window.maatlog.enhance(document)")

                page.locator(".maatlog-post-body h2 > a.headerlink").click()

                page.wait_for_function("() => window.__clipboardCalls.length > 0")
                page.wait_for_timeout(200)
                assert page.evaluate("() => window.__clipboardCalls.length") == 1
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_copy_success_is_announced_and_shown(site: AcceptanceSite, theme: str) -> None:
    """受け入れ条件 5: コピー成功が視覚と非視覚の両方で通知される。"""
    result = site.build("html", theme=theme, extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = _new_page(browser)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                anchor = page.locator(".maatlog-post-body h2 > a.headerlink")

                anchor.click()

                # 非視覚: live region はページに 1 つだけで、そこに結果が入る。
                status = page.locator(".maatlog-copy-link-status")
                expect(status).to_have_count(1)
                expect(status).to_have_attribute("role", "status")
                expect(status).to_have_attribute("aria-live", "polite")
                expect(status).to_have_text("Copied")
                # 視覚: バブルは data 属性で駆動され、文言は JS 側が持つ。
                expect(anchor).to_have_attribute("data-maatlog-copy-state", "copied")
                expect(anchor).to_have_attribute("data-maatlog-copy-label", "Copied")
                # 視覚の実描画: 疑似要素は content が none だとボックスを生成
                # しない。テーマごとに maatlog.css は 1 枚だけ配布される二重持ち
                # 構成なので、構造規則の複製漏れを computed style で直接固定する。
                bubble_content = anchor.evaluate("el => getComputedStyle(el, '::after').content")
                assert bubble_content == '"Copied"'
                anchor_position = anchor.evaluate("el => getComputedStyle(el).position")
                assert anchor_position == "relative"
        finally:
            browser.close()


@pytest.mark.browser
def test_copy_feedback_clears_itself(site: AcceptanceSite) -> None:
    """バブルは出しっぱなしにしない。"""
    result = site.build("html", theme="maatlog-default", extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = _new_page(browser)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                anchor = page.locator(".maatlog-post-body h2 > a.headerlink")

                anchor.click()
                expect(anchor).to_have_attribute("data-maatlog-copy-state", "copied")

                expect(anchor).not_to_have_attribute("data-maatlog-copy-state", "copied", timeout=5000)
        finally:
            browser.close()


@pytest.mark.browser
def test_clipboard_failure_is_reported_without_breaking_the_page(site: AcceptanceSite) -> None:
    """受け入れ条件 5 の裏: 失敗も通知し、例外はページへ漏らさない。"""
    result = site.build("html", theme="maatlog-default", extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = _new_page(browser)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                page.evaluate("() => { window.__clipboardMode = 'reject'; }")
                anchor = page.locator(".maatlog-post-body h2 > a.headerlink")

                anchor.click()

                expect(page.locator(".maatlog-copy-link-status")).to_have_text("Copy failed")
                expect(anchor).to_have_attribute("data-maatlog-copy-state", "failed")
                # ジャンプは成功しており、アドレスバーに同じ URL が残る。
                assert page.url.endswith("#level-two")
                assert errors == [], errors
        finally:
            browser.close()


@pytest.mark.browser
def test_status_reports_the_current_press_not_the_previous_one(site: AcceptanceSite) -> None:
    """live region は「今押した結果」だけを述べる。"""
    result = site.build("html", theme="maatlog-default", extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = _new_page(browser)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                page.locator(".maatlog-post-body h2 > a.headerlink").click()
                expect(page.locator(".maatlog-copy-link-status")).to_have_text("Copied")

                page.evaluate("() => { window.__clipboardMode = 'reject'; }")
                page.locator(".maatlog-post-body h3 > a.headerlink").click()

                expect(page.locator(".maatlog-copy-link-status")).to_have_text("Copy failed")
        finally:
            browser.close()


@pytest.mark.browser
def test_keyboard_only_operation_copies(site: AcceptanceSite) -> None:
    """受け入れ条件 6: キーボードだけで操作できる。"""
    result = site.build("html", theme="maatlog-default", extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = _new_page(browser)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                page.evaluate("() => document.querySelector('.maatlog-post-body h2 > a.headerlink').focus()")
                assert (
                    page.evaluate("() => document.activeElement.matches('.maatlog-post-body h2 > a.headerlink')")
                    is True
                )

                page.keyboard.press("Enter")

                assert _wait_for_copy(page).endswith("#level-two")
                expect(page.locator(".maatlog-copy-link-status")).to_have_text("Copied")
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("theme", ["maatlog-base", "maatlog-default"])
def test_touch_only_readers_can_see_the_control(site: AcceptanceSite, theme: str) -> None:
    """受け入れ条件: hover を持たない環境でもコピー UI が使える。"""
    result = site.build("html", theme=theme, extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            # has_touch=True だけでは media query は動かない。Chromium に
            # (hover: none) / (pointer: coarse) を報告させる。
            context = browser.new_context(has_touch=True, is_mobile=True, viewport={"width": 390, "height": 844})
            page = context.new_page()
            page.add_init_script(CLIPBOARD_STUB)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)

                assert page.evaluate("() => window.matchMedia('(hover: none)').matches") is True
                anchor = page.locator(".maatlog-post-body h2 > a.headerlink")
                expect(anchor).to_be_visible()
                assert page.evaluate(
                    "() => {"
                    "  const s = getComputedStyle(document.querySelector("
                    "    '.maatlog-post-body h2 > a.headerlink'));"
                    "  return [s.visibility, s.opacity];"
                    "}"
                ) == ["visible", "1"]

                anchor.tap()

                assert _wait_for_copy(page).endswith("#level-two")
        finally:
            browser.close()


@pytest.mark.browser
def test_heading_text_stays_selectable(site: AcceptanceSite) -> None:
    """アクセシビリティ要件: 見出しテキスト自体の選択を妨げない。"""
    result = site.build("html", theme="maatlog-default", extra_files=EXTRA_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = _new_page(browser)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)

                assert (
                    page.evaluate("() => getComputedStyle(document.querySelector('.maatlog-post-body h2')).userSelect")
                    != "none"
                )
        finally:
            browser.close()
