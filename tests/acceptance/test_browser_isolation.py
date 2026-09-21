"""Issue #313: shared_browser のケース単位 Context 分離を検査する。

shared_browser は module scope（Playwright sync API は同一スレッドで
インスタンスを重ねられないため）。同じモジュール内の全ケースが同じ
Browser を共有し、その間も Context はケースごとに独立している。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from acceptance.server import serve_directory
from playwright.sync_api import Browser, Error

INDEX_HTML = "<!doctype html><html><body><p>served</p></body></html>"


@pytest.fixture(scope="module")
def captured_shared_browser(shared_browser: Browser) -> Browser:
    """module scope の Browser を各ケースの同一性検査用に保持する。"""
    return shared_browser


@pytest.mark.browser
@pytest.mark.parametrize("round_", [1, 2], ids=["first", "second"])
def test_shared_browser_is_reused_across_cases(
    shared_browser: Browser,
    captured_shared_browser: Browser,
    round_: int,
) -> None:
    """同じモジュール内の各ケースは同じ Browser インスタンスを受け取る。

    function scope へ後退すると module scope fixture から参照できず ScopeMismatch に
    なる（= 起動がケース数だけ増える退行を検出する）。各ケースは単独・逆順・別
    worker でも、先行ケースの副作用に依存せず検査できる。
    """
    assert shared_browser.is_connected()
    assert shared_browser is captured_shared_browser, f"{round_}ケース目が別の Browser を受け取った"


@pytest.mark.browser
def test_context_state_does_not_leak_between_contexts(shared_browser: Browser, tmp_path: Path) -> None:
    """同一 origin で Context A の storage/cookie/route が Context B へ漏れない。"""
    (tmp_path / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    with serve_directory(tmp_path) as base_url:
        context_a = shared_browser.new_context()
        try:
            page_a = context_a.new_page()
            page_a.goto(base_url, wait_until="load")
            page_a.evaluate("() => localStorage.setItem('isolation-marker', 'A')")
            context_a.add_cookies([{"name": "isolation", "value": "a", "url": base_url}])
            context_a.route("**/*", lambda route: route.fulfill(status=200, body="intercepted"))
            page_a.goto(base_url, wait_until="load")
            assert "intercepted" in page_a.content()
        finally:
            context_a.close()

        context_b = shared_browser.new_context()
        try:
            page_b = context_b.new_page()
            page_b.goto(base_url, wait_until="load")
            # A の route は B に効かず、実通信に戻る。
            assert "served" in page_b.content()
            assert page_b.evaluate("() => localStorage.getItem('isolation-marker')") is None
            assert context_b.cookies(base_url) == []
        finally:
            context_b.close()


@pytest.mark.browser
def test_context_closes_when_the_case_raises(shared_browser: Browser) -> None:
    """ケース内で例外が出ても、finally で破棄した context は再利用できない。"""
    context = shared_browser.new_context()
    with pytest.raises(RuntimeError, match="boom"):
        try:
            context.new_page()
            raise RuntimeError("boom")
        finally:
            context.close()
    with pytest.raises(Error):
        context.new_page()
