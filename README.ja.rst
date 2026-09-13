MaatLog
=======

MaatLog は、ドキュメントプロジェクトを静的ブログに変える Sphinx 拡張です。
投稿は小さなメタデータスキーマを持つ、通常の reStructuredText または MyST
Markdown ドキュメントです。MaatLog は Sphinx の公開拡張インターフェイスの上に、
アーカイブ、タクソノミーナビゲーション、Atom フィード、HTML Theme API を追加します。

要件
----

* Python 3.14+
* Sphinx 9.1+
* myst-parser 5.1+

インストール
------------

ビルド済み配布物（wheel または sdist）から::

    pip install maatlog

またはチェックアウトから `uv` で::

    uv sync
    uv pip install -e .

クイックスタート
----------------

1. ``conf.py`` で拡張を有効にし、（任意で）同梱テーマを設定します::

    extensions = ["maatlog"]

    html_theme = "maatlog-default"
    html_baseurl = "https://example.com/"  # Atom フィード有効時は必須

    maatlog_timezone = "UTC"
    maatlog_tags = {"sphinx": "Sphinx", "python": "Python"}
    maatlog_categories = {"engineering": "Engineering"}
    maatlog_authors = {"alice": "Alice"}

2. reStructuredText の投稿を書きます（タイトル前の field list）::

    :maatlog-post: true
    :maatlog-published-at: 2026-08-01T09:00:00+09:00
    :maatlog-slug: hello-maatlog
    :maatlog-tags: sphinx, python
    :maatlog-categories: engineering
    :maatlog-authors: alice
    :maatlog-excerpt: First post with MaatLog.

    Hello MaatLog
    =============

    投稿本文…

3. または同等の MyST Markdown 投稿（YAML front matter）::

    ---
    maatlog-post: true
    maatlog-published-at: 2026-08-01T09:00:00+09:00
    maatlog-slug: hello-maatlog
    maatlog-tags: [sphinx, python]
    maatlog-categories: [engineering]
    maatlog-authors: [alice]
    maatlog-excerpt: First post with MaatLog.
    ---

    # Hello MaatLog

    投稿本文…

4. HTML をビルドします::

    sphinx-build -b html sourcedir builddir

上記のデフォルト設定では、MaatLog は次を生成します。

* 選択した MaatLog テーマを使った投稿ページ
* ``blog/`` 配下のアーカイブ（``maatlog_archive_docname`` で設定可能）
* アーカイブルート配下の Atom フィード（``maatlog_generate_feeds`` が true のとき）
* ``:maatlog:post:``、``:maatlog:tag:`` などの相互参照ロール

再ビルドに関する注意
--------------------

ほとんどの ``maatlog_*`` 設定は Sphinx 環境（``env``）を再構築します。フィード関連の
設定は HTML 出力のみ（``html``）を再構築します。タクソノミー辞書、アーカイブルート、
ページサイズ、タイムゾーン、フィードオプションを変更したあとは、アーカイブと
フィードの整合を保つため、クリーンビルドまたはフルリビルドを実行してください。

``SOURCE_DATE_EPOCH``（Unix 秒、UTC）は、下書き / 予約 / 期限切れの公開ステータスに
使うビルド時計を固定します。再現可能な CI ビルドではこちらを推奨します。

MaatLog が置き換えないもの
--------------------------

MaatLog は Sphinx のドキュメントタイトル、toctree、検索、autodoc、Pygments、
intersphinx を置き換えません。通常のドキュメントページは、同じプロジェクト内で
投稿と共存します。完全な HTML 機能（アーカイブ、Theme API 検証、フィード、
MaatLog HTML メタデータ）が保証されるのは ``html`` および ``dirhtml`` ビルダーのみです。
それ以外のビルダーでは、該当する場合に投稿本文とロール解決は維持されます。

ドキュメント
------------

* `docs/authoring.rst` — 投稿メタデータスキーマと例
* `docs/configuration.rst` — conf.py の設定とデフォルト
* `docs/theme-api.rst` — Theme API 1.0 仕様と公式テーマ
* `docs/builders.rst` — ビルダー行列と静的サイト制約

開発
----

Node.js 24 は、開発者向けの JavaScript / CSS 品質ツールにだけ必要です。
MaatLog の Python パッケージをインストールして利用する環境には Node.js を要求しません。

公式の HTML / CSS 対応範囲は ``package.json`` の ``browserslist`` です。
``defaults`` に残る長尾ブラウザ（Opera Mini、KaiOS 2.x、UC Browser、QQ Browser）は対象外です。

Python と frontend の lock 済み開発環境を構築し、frontend 検査を実行します::

    uv sync --locked --all-groups
    npm ci
    npm run check

frontend 検査の個別コマンドは次のとおりです::

    npm run lint:js
    npm run format:check
    npm run typecheck:js
    npm run lint:css
    npm run format

full プロファイルはブラウザを使うアクセシビリティテストを実行するため、
実行前に一度 Playwright のブラウザを導入します。ブラウザの OS 依存パッケージも
必要な環境では、同じコマンドに ``--with-deps`` を付けます（``sudo`` を使います）::

    uv run playwright install chromium

リポジトリ全体の authoritative な検証入口は引き続き次です::

    ./scripts/ci/verify.sh full

検証プロファイル
----------------

検証の入口は ``scripts/ci/verify.sh <profile>`` に一本化されています。プロファイル
によって実行時間だけでなく、検査する範囲が変わります:

``static``
    static チェック一式です。``ruff check``、``ruff format --check``、``pyright``、
    および frontend の検査（``npm ci`` と ``npm run check``）を実行します。

``quick``
    static と同じ検査に続けて、``pytest -m "not browser"`` を実行します。

``full``
    リリース前のゲートです。static チェック、ブラウザを使うアクセシビリティテストを
    含む全テスト、配布物のビルド（``uv build``、``twine check``）、配布物のテストを
    実行します。

``minimum`` / ``latest``
    CI が実行する Sphinx の互換性マトリクスです。``uv pip install`` で Sphinx の
    バージョンを差し替えるため、仮想環境を書き換えます。

``static`` と ``quick`` は ``uv pip install`` を実行しないため、仮想環境は
``uv sync`` 直後の状態のまま保たれ、開発中に繰り返し実行できます。また、static
チェックが失敗した時点で停止し、テストには進みません。authoritative な検証入口は
引き続き ``full`` です。

8コア / 31GB の Dev Container で、``uv sync`` と ``npm ci`` が済んだ状態での実測値
（2026-09-11）:

``quick`` はテストを並列実行する（``-n auto``）ため、実行時間は使えるコア数に
依存します。

=====================  ================
プロファイル           実行時間
=====================  ================
``static``             約17秒
``quick``              約1.3〜1.7分
``full``               約12〜16分
=====================  ================

ライセンスとステータス
----------------------

MaatLog MVP は Sphinx ベースの静的ブログを対象とします。開発はまだ活発で安定して
おらず、パッケージは公開済みですが既知の利用者はいません。開発が安定するまで、
Theme API の更新は下位互換しない破壊的変更です。公開メタデータキー、設定名、
ロール、生成 docname 規則、診断コードは互換性管理の対象です。
