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
* `docs/theme-api.rst` — Theme API 1.0 契約と公式テーマ
* `docs/builders.rst` — ビルダー行列と静的サイト制約

開発
----

リポジトリを clone し、lock 済みの開発環境を構築して共通検証を実行します::

    uv sync --locked --all-groups
    ./scripts/ci/verify.sh full

ライセンスとステータス
----------------------

MaatLog MVP は Sphinx ベースの静的ブログを対象とします。公開メタデータキー、
設定名、ロール、Theme API のメジャーバージョン、生成 docname 規則、診断コードは
互換性管理の対象です。
