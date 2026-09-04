"""Issue #62 「新着」表示の受け入れ条件を実ブラウザで検証する。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from acceptance.server import serve_directory
from playwright.sync_api import Page, sync_playwright

if TYPE_CHECKING:
    from acceptance.site import AcceptanceSite

ARCHIVE_PAGE = "blog.html"

# 2 本の post をフィクスチャとして用意する。
# 公開日時の新旧をテスト側で localStorage に書き込んで制御する。
# SOURCE_DATE_EPOCH (2026-08-15) 以前でなければ投稿が除外される。
# old-post: 古い投稿（前回訪問より前）
# new-post: 前回訪問より後かつ SOURCE_DATE_EPOCH 以前の投稿
OLD_PUBLISHED_AT = "2026-08-01T00:00:00Z"
NEW_PUBLISHED_AT = "2026-08-12T00:00:00Z"

FIXTURE_POSTS: dict[str, str] = {
    "posts/old-post.rst": (
        ":maatlog-post: true\n"
        ":maatlog-slug: old-post\n"
        f":maatlog-published-at: {OLD_PUBLISHED_AT}\n"
        "\n"
        "Old post\n"
        "========\n"
        "\n"
        "Body.\n"
    ),
    "posts/new-post.rst": (
        ":maatlog-post: true\n"
        ":maatlog-slug: new-post\n"
        f":maatlog-published-at: {NEW_PUBLISHED_AT}\n"
        "\n"
        "New post\n"
        "========\n"
        "\n"
        "Body.\n"
    ),
}


def _has_new_badge(page: Page, slug: str) -> bool:
    return page.evaluate(
        """(slug) => {
            const card = document.querySelector(`.maatlog-post-card[data-slug="${slug}"]`);
            if (!card) return false;
            return card.querySelector('.maatlog-new-badge') !== null;
        }""",
        slug,
    )


@pytest.mark.browser
def test_first_visit_shows_no_new_badge(site: AcceptanceSite) -> None:
    """初回訪問（localStorage にキーなし）では NEW バッジを表示しない。"""
    result = site.build("html", theme="maatlog-default", extra_files=FIXTURE_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context()
            page = context.new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
                page.wait_for_timeout(300)

                # localStorage に何も書いていない → NEW なし
                assert not _has_new_badge(page, "old-post")
                assert not _has_new_badge(page, "new-post")
        finally:
            browser.close()


@pytest.mark.browser
def test_second_visit_shows_new_badge_only_for_newer_posts(site: AcceptanceSite) -> None:
    """前回訪問以降に公開された投稿にのみ NEW バッジが付く。"""
    result = site.build("html", theme="maatlog-default", extra_files=FIXTURE_POSTS)
    # 前回訪問 = 2026-08-10T12:00Z（rst-post / md-post の公開日と同時刻）
    # new-post (2026-08-12) → NEW、old-post (2026-08-01) → 非NEW
    previous_visit = "2026-08-10T12:00:00.000Z"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context()
            # add_init_script でページロード前に localStorage を設定する。
            # これにより maatlog.js がスクリプト解析時に正しい baseline を読める。
            context.add_init_script(f"window.localStorage.setItem('maatlog:last-visit', {previous_visit!r});")
            page = context.new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
                page.wait_for_timeout(300)

                assert _has_new_badge(page, "new-post"), "new-post に NEW バッジがない"
                assert not _has_new_badge(page, "old-post"), "old-post に NEW バッジがある (前回訪問より古い)"
        finally:
            browser.close()


@pytest.mark.browser
def test_new_badge_persists_across_navigation_in_same_session(site: AcceptanceSite) -> None:
    """同一セッション中にページ遷移しても NEW 状態が維持される。"""
    result = site.build("html", theme="maatlog-default", extra_files=FIXTURE_POSTS)
    previous_visit = "2026-08-10T12:00:00.000Z"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context()
            # add_init_script はコンテキスト内の全ナビゲーションで再実行されるため、
            # 無条件の書き込みだと本番コードが更新した last-visit を毎回リセットしてしまう。
            # 初回ロードのみ種を与え、以降は本番コードが書いた実際の値を残す。
            context.add_init_script(
                "if (window.localStorage.getItem('maatlog:last-visit') === null) {"
                f"  window.localStorage.setItem('maatlog:last-visit', {previous_visit!r});"
                "}"
            )
            page = context.new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
                page.wait_for_timeout(300)

                # アーカイブで NEW を確認
                assert _has_new_badge(page, "new-post")

                # 別ページ（posts/ 配下のページ）に遷移してアーカイブに戻る
                page.goto(f"{base_url}posts/new-post.html", wait_until="load")
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
                page.wait_for_timeout(300)

                # sessionStorage に baseline がキャッシュされているので
                # localStorage の last-visit が更新されても比較基準は変わらない
                assert _has_new_badge(page, "new-post"), "ページ遷移後も NEW バッジが必要"
        finally:
            browser.close()


@pytest.mark.browser
def test_new_badge_absent_when_localStorage_unavailable(site: AcceptanceSite) -> None:
    """localStorage が使えない環境でも通常のアーカイブ表示として動作する。"""
    result = site.build("html", theme="maatlog-default", extra_files=FIXTURE_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context()
            page = context.new_page()
            # localStorage を無効化 (always throw)
            page.add_init_script(
                "Object.defineProperty(window, 'localStorage', { get() { throw new Error('storage blocked'); } });"
            )
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
                page.wait_for_timeout(300)

                # エラーにならず、バッジも出ない
                assert not _has_new_badge(page, "old-post")
                assert not _has_new_badge(page, "new-post")
        finally:
            browser.close()


@pytest.mark.browser
def test_published_at_is_read_from_machine_readable_attribute(site: AcceptanceSite) -> None:
    """公開日時は data-maatlog-published-at 属性から読み取る（表示文字列に依存しない）。"""
    result = site.build("html", theme="maatlog-default", extra_files=FIXTURE_POSTS)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context()
            page = context.new_page()
            with serve_directory(result.outdir) as base_url:
                page.goto(f"{base_url}{ARCHIVE_PAGE}", wait_until="load")
                # post-card に data-maatlog-published-at が存在することを確認
                has_attr = page.evaluate(
                    """() => {
                        const cards = document.querySelectorAll('.maatlog-post-card[data-maatlog-published-at]');
                        return cards.length > 0;
                    }"""
                )
                assert has_attr, "post-card に data-maatlog-published-at 属性がない"
        finally:
            browser.close()
