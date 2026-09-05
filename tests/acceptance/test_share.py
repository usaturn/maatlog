"""Issue #64: Share / 記事 URL コピーの実ブラウザ挙動。

Web Share / Clipboard API は実行環境次第で使えたり使えなかったりするので、
`page.add_init_script` で Navigator をスタブし、実呼び出しとその実引数を検証する。
受け入れ条件 1〜7 を 1 本ずつの Playwright テストで担保する。
"""

from __future__ import annotations

import pytest
from acceptance.server import serve_directory
from acceptance.site import AcceptanceSite
from playwright.sync_api import Page, expect, sync_playwright

# 受け入れプロジェクトの公開済み記事の 1 つ。canonical を持つ post ページ。
POST_PAGE = "posts/rst-post.html"

# 実行時に window.__shareMode / __clipboardMode を切り替えられる Navigator スタブ。
# getter で返す値を変えることで、navigator.share の有無と成功/失敗を click 直前に制御する。
SHARE_STUB = """
(() => {
  window.__shareCalls = [];
  window.__clipboardCalls = [];
  window.__shareMode = "resolve";
  window.__clipboardMode = "resolve";

  const shareFn = function(data) {
    if (this !== navigator) {
      return Promise.reject(new TypeError("Illegal invocation"));
    }
    window.__shareCalls.push(data);
    if (window.__shareMode === "abort") {
      return Promise.reject(new DOMException("The user aborted a request.", "AbortError"));
    }
    if (window.__shareMode === "other-error") {
      return Promise.reject(new Error("share boom"));
    }
    return Promise.resolve();
  };
  Object.defineProperty(navigator, "share", {
    configurable: true,
    get: () => (window.__shareMode === "undefined" ? undefined : shareFn),
  });

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


def _open_post(page: Page, base_url: str) -> None:
    """記事ページを開き、runtime が Share を表示するまで待つ。"""
    page.goto(f"{base_url}{POST_PAGE}", wait_until="load")
    # .maatlog-js が付くまで .maatlog-share は display:none。可視になるのを待つ。
    expect(page.locator(".maatlog-share")).to_be_visible()


def _canonical_href(page: Page) -> str:
    href = page.evaluate("() => document.querySelector('link[rel=\"canonical\"]').href")
    assert isinstance(href, str) and href
    return href


def _status_text(page: Page) -> str:
    value = page.evaluate("() => document.querySelector('.maatlog-share-status').textContent")
    return value if isinstance(value, str) else ""


@pytest.mark.browser
def test_share_button_is_reachable_by_its_visible_name(site: AcceptanceSite) -> None:
    """WCAG 2.5.3: アクセシブル名が可視ラベルと一致し、可視の名前で起動できる。"""
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.add_init_script(SHARE_STUB)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)

                share = page.get_by_role("button", name="Share", exact=True)
                assert share.count() == 1

                # 可視の名前で引いたロケータからそのまま起動できる。
                share.click()
                page.wait_for_function("() => window.__shareCalls.length > 0")
        finally:
            browser.close()


@pytest.mark.browser
def test_native_share_receives_title_and_canonical_url(site: AcceptanceSite) -> None:
    """受け入れ条件 1: navigator.share が { title, url } で呼ばれ、url は canonical。"""
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.add_init_script(SHARE_STUB)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                title = page.evaluate("() => document.title")
                canonical = _canonical_href(page)
                # canonical は address-bar の URL と別物であること（優先を実証するため）。
                assert canonical != page.url

                page.locator(".maatlog-share-button").click()
                page.wait_for_function("() => window.__shareCalls.length > 0", timeout=5_000)

                shared = page.evaluate("() => window.__shareCalls[0]")
                assert isinstance(shared, dict)
                assert shared["url"] == canonical
                assert shared["title"] == title
                assert page.evaluate("() => window.__clipboardCalls.length") == 0
        finally:
            browser.close()


@pytest.mark.browser
def test_unsupported_share_falls_back_to_clipboard(site: AcceptanceSite) -> None:
    """受け入れ条件 2: navigator.share が無い時は clipboard.writeText へ canonical URL が渡る。"""
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.add_init_script(SHARE_STUB)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                canonical = _canonical_href(page)
                page.evaluate("() => { window.__shareMode = 'undefined'; }")

                page.locator(".maatlog-share-button").click()
                page.wait_for_function("() => window.__clipboardCalls.length > 0")

                copied = page.evaluate("() => window.__clipboardCalls[0]")
                assert copied == canonical
        finally:
            browser.close()


@pytest.mark.browser
def test_canonical_is_preferred_and_location_is_the_fallback(site: AcceptanceSite) -> None:
    """受け入れ条件 3: canonical があればそれを、無ければ location.href を使う。"""
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.add_init_script(SHARE_STUB)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                canonical = _canonical_href(page)
                page.evaluate("() => { window.__shareMode = 'undefined'; }")

                # canonical が在るときは canonical を渡す。
                page.locator(".maatlog-share-button").click()
                page.wait_for_function("() => window.__clipboardCalls.length > 0")
                assert page.evaluate("() => window.__clipboardCalls[0]") == canonical

                # canonical を剥がすと address-bar の URL (location.href) へフォールバック。
                page.evaluate(
                    "() => {"
                    "  window.__clipboardCalls.length = 0;"
                    "  const l = document.querySelector('link[rel=canonical]');"
                    "  if (l) { l.remove(); }"
                    "}"
                )
                page.locator(".maatlog-share-button").click()
                page.wait_for_function("() => window.__clipboardCalls.length > 0")
                assert page.evaluate("() => window.__clipboardCalls[0]") == page.url
        finally:
            browser.close()


@pytest.mark.browser
def test_relative_canonical_falls_back_to_the_address_bar_url(site: AcceptanceSite) -> None:
    """相対 canonical は共有 URL に使わない。

    ブラウザは相対 ``href`` を文書からの相対として解決するので、``canonical.href`` を
    そのまま信じるとルート直下に無い記事で 1 階層ずれた到達不能な URL を配布する。
    """
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.add_init_script(SHARE_STUB)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                page.evaluate("() => { window.__shareMode = 'undefined'; }")

                # canonical を相対 href に差し替える。解決結果は 1 階層ずれた URL になる。
                misresolved = page.evaluate(
                    "() => {"
                    "  const l = document.querySelector('link[rel=canonical]');"
                    "  l.setAttribute('href', 'posts/rst-post.html');"
                    "  return l.href;"
                    "}"
                )
                assert misresolved != page.url

                page.locator(".maatlog-share-button").click()
                page.wait_for_function("() => window.__clipboardCalls.length > 0")

                assert page.evaluate("() => window.__clipboardCalls[0]") == page.url
        finally:
            browser.close()


@pytest.mark.browser
def test_cancelled_share_does_not_copy(site: AcceptanceSite) -> None:
    """受け入れ条件 4: navigator.share が AbortError で reject されたら clipboard を呼ばない。"""
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.add_init_script(SHARE_STUB)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                page.evaluate("() => { window.__shareMode = 'abort'; }")

                page.locator(".maatlog-share-button").click()
                page.wait_for_function("() => window.__shareCalls.length > 0")
                # AbortError の後処理（reject の伝播）が終わるまで一呼吸置く。
                page.wait_for_timeout(150)

                assert page.evaluate("() => window.__clipboardCalls.length") == 0
                assert _status_text(page) == ""
        finally:
            browser.close()


@pytest.mark.browser
def test_clipboard_success_notifies_copied(site: AcceptanceSite) -> None:
    """受け入れ条件 5: clipboard 成功時は status に「Copied!」が表示される。"""
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.add_init_script(SHARE_STUB)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                page.evaluate("() => { window.__shareMode = 'undefined'; }")

                page.locator(".maatlog-share-button").click()
                expect(page.locator(".maatlog-share-status")).to_have_text("Copied!", timeout=5000)

                assert page.evaluate("() => window.__clipboardCalls.length") == 1
        finally:
            browser.close()


@pytest.mark.browser
def test_status_reports_the_current_press_not_the_previous_one(site: AcceptanceSite) -> None:
    """status は直前の操作の結果だけを示す（前回の「Copied!」が残らない）。"""
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.add_init_script(SHARE_STUB)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)

                # 1 回目: clipboard フォールバックで「Copied!」が出る。
                page.evaluate("() => { window.__shareMode = 'undefined'; }")
                page.locator(".maatlog-share-button").click()
                expect(page.locator(".maatlog-share-status")).to_have_text("Copied!", timeout=5000)

                # 2 回目: navigator.share が成功する経路。status は何も主張しない。
                page.evaluate("() => { window.__shareMode = 'resolve'; }")
                page.locator(".maatlog-share-button").click()
                page.wait_for_function("() => window.__shareCalls.length > 0")
                expect(page.locator(".maatlog-share-status")).to_have_text("", timeout=5000)
        finally:
            browser.close()


@pytest.mark.browser
def test_clipboard_failure_still_leaves_the_article_readable(site: AcceptanceSite) -> None:
    """受け入れ条件 6: clipboard 失敗でも未処理エラーにせず、URL を status に示す。"""
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.add_init_script(SHARE_STUB)
            with serve_directory(result.outdir) as base_url:
                _open_post(page, base_url)
                page.evaluate("() => { window.__shareMode = 'undefined'; window.__clipboardMode = 'reject'; }")

                # フォールバック先の URL を決めてから押す。canonical が在るので、渡る URL は canonical。
                canonical = _canonical_href(page)
                page.locator(".maatlog-share-button").click()
                page.wait_for_function(
                    "(expected) => document.querySelector('.maatlog-share-status').textContent === expected",
                    arg=canonical,
                )

                assert _status_text(page) == canonical
                assert page.evaluate("() => window.__clipboardCalls.length") == 1
                assert page_errors == []  # 未処理エラーがページに流れていない。
                # 記事は引き続き閲覧できる。
                expect(page.locator(".maatlog-post")).to_be_visible()
                assert len(page.text_content(".maatlog-post") or "") > 0
        finally:
            browser.close()


@pytest.mark.browser
def test_without_javascript_article_is_readable_and_share_is_hidden(site: AcceptanceSite) -> None:
    """受け入れ条件 7: JS 無効でも記事は読め、Share は出ない。"""
    result = site.build("html", theme="maatlog-default")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(java_script_enabled=False)
            page = context.new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{POST_PAGE}", wait_until="load")

                # 記事本文は静的 HTML として見える。
                expect(page.locator(".maatlog-post")).to_be_visible()
                assert len(page.text_content(".maatlog-post") or "") > 0
                # Share は runtime (.maatlog-js) が無いため display:none のまま。
                expect(page.locator(".maatlog-share")).to_be_hidden()
        finally:
            browser.close()
