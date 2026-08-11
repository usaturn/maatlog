設定
====

すべての設定は MaatLog が登録する Sphinx ``conf.py`` の値です。不正な値は
``config-inited`` の時点で ``maatlog.config.invalid`` としてビルドを失敗させます。

設定値
------

.. list-table::
   :header-rows: 1
   :widths: 28 22 28 12

   * - 名前
     - 型
     - デフォルト
     - 再ビルド
   * - ``maatlog_timezone``
     - IANA タイムゾーンの ``str``
     - ``"UTC"``
     - ``env``
   * - ``maatlog_tags``
     - ``dict[str, str] | None``
     - ``None``
     - ``env``
   * - ``maatlog_categories``
     - ``dict[str, str] | None``
     - ``None``
     - ``env``
   * - ``maatlog_authors``
     - ``dict[str, str] | None``
     - ``None``
     - ``env``
   * - ``maatlog_archive_docname``
     - 相対 docname の ``str``
     - ``"blog"``
     - ``env``
   * - ``maatlog_page_size``
     - 正の ``int``
     - ``10``
     - ``env``
   * - ``maatlog_generate_feeds``
     - ``bool``
     - ``True``
     - ``html``
   * - ``maatlog_feed_taxonomies``
     - 軸名のシーケンス
     - ``("tag", "category", "author", "month")``
     - ``html``
   * - ``maatlog_feed_limit``
     - 正の ``int``
     - ``20``
     - ``html``

関連する Sphinx の設定
----------------------

* ``html_baseurl`` — サイトの絶対ベース URL。完全な HTML ビルダー（``html`` /
  ``dirhtml``）でフィードを有効にする場合は **必須** です。Atom の ``link`` /
  ``id`` の値と、HTML のフィードディスカバリに使われます。
* ``html_theme`` — 同梱テーマを使う場合は ``"maatlog-default"`` を、あるいは
  Theme API 互換のサードパーティテーマを指定します。
* ``html_search_language`` をはじめとする Sphinx の検索関連設定には手を加えません。
  MaatLog は独自の検索インデックスをインストールしません。

タクソノミー辞書
----------------

``maatlog_tags``、``maatlog_categories``、``maatlog_authors`` が ``None`` の場合、
投稿で使われた ID は自動登録され、表示名は ID と同じになります。マッピングを指定した
場合は、そのキーのみが許可され、未定義の ID は ``maatlog.taxonomy.undefined`` を
発生させます。

キーは ``[a-z0-9][a-z0-9._-]*`` に一致する必要があります。値は空でない表示名で
なければなりません。設定済みでも公開済み投稿に使われていない ID は、アーカイブページも
インベントリオブジェクトも生成しません。

アーカイブのルート
------------------

``maatlog_archive_docname`` は生成ページのルート docname です（デフォルトは
``blog``）。先頭・末尾のスラッシュ、空のセグメント、``.``、``..`` を含まない相対的な
Sphinx ドキュメント名でなければなりません。

生成されるパス（ルートが ``blog`` の場合）:

* 全投稿: ``blog``、``blog/page/<n>``
* タグ: ``blog/tag/<id>``、``blog/tag/<id>/page/<n>``
* カテゴリ: ``blog/category/<id>``、…
* 著者: ``blog/author/<id>``、…
* 月: ``blog/month/YYYY-MM``、…
* サイト Atom フィード: ``blog/atom.xml``
* タクソノミーフィード: ``blog/<axis>/<id>/atom.xml``

フィード
--------

``maatlog_generate_feeds`` が ``True`` で、かつビルダーが完全な HTML の場合:

* ``html_baseurl`` の設定が必須です
* ビルド成功後にサイトフィードとタクソノミーフィードが書き出されます
* ``maatlog_feed_taxonomies`` でフィードを生成する軸を選択します（``tag``、
  ``category``、``author``、``month``）
* ``maatlog_feed_limit`` はフィードあたりのエントリ数の上限です

``maatlog_generate_feeds = False`` を設定すると、フィード生成とディスカバリリンクを
スキップします。

タイムゾーンとビルド時刻
------------------------

* オフセットのない投稿日時は ``maatlog_timezone`` で解釈されます。
* 公開月アーカイブは、UTC の日付ではなく、設定されたタイムゾーンの暦月（``YYYY-MM``）
  を使います。
* ``SOURCE_DATE_EPOCH`` はビルド時刻を固定し、CI ホスト間で公開・非公開の境界を
  再現可能にします。

例
--

::

    extensions = ["maatlog"]

    html_theme = "maatlog-default"
    html_baseurl = "https://example.com/docs/"

    maatlog_timezone = "Asia/Tokyo"
    maatlog_tags = {
        "sphinx": "Sphinx",
        "python": "Python",
    }
    maatlog_categories = {
        "engineering": "Engineering",
    }
    maatlog_authors = {
        "alice": "Alice",
    }
    maatlog_archive_docname = "blog"
    maatlog_page_size = 10
    maatlog_generate_feeds = True
    maatlog_feed_taxonomies = ("tag", "category", "author", "month")
    maatlog_feed_limit = 20
