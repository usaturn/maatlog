"""生成サイトをローカル HTTP で配信する受け入れテスト用ヘルパ。

``file://`` では ``fetch()`` が同一オリジンポリシーで必ず失敗するため、
Infinite Scroll のようにページを取得する機能は HTTP 配信でしか検証できない。
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class _QuietHandler(SimpleHTTPRequestHandler):
    """アクセスログを stderr へ出さない（テスト出力を汚さない）。"""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 — 基底クラスの署名
        del format, args


@contextmanager
def serve_directory(root: Path) -> Generator[str]:
    """*root* を ``127.0.0.1`` の動的ポートで配信し、末尾スラッシュ付きの base URL を返す。"""
    handler = partial(_QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    host, port = server.server_address[0], server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
