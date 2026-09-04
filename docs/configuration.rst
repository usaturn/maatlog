設定
====

すべての設定は MaatLog が登録する Sphinx ``conf.py`` の値です。
不正な値は
``config-inited`` の時点で ``maatlog.config.invalid`` としてビルドを失敗させます

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
   * -  ``maatlog_categories``
     - ``dict[str, str] | None``
     - ``None``
     - ``env``
   * -  ``maatlog_authors``
     - ``dict[str, str] | None``
     - ``None``
     - ``env``
   * - ``maatlog_author_profiles``
     - ``dict[str, dict] | None``
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
   * - ``maatlog_tagline``
     - ``str | None``
     - ``None``
     - ``html``
   * - ``maatlog_home_docname``
     - 相対 docname の ``str | None``
     - ``None``
     - ``html``
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
   * - ``maatlog_palette``
     - パレット名の ``str | None``
     - ``None``
     - ``html``

関連する Sphinx の設定
----------------------

* ``html_baseurl`` — サイトの絶対ベース URL。
  完全な HTML ビルダー（``html`` /
  ``dirhtml``）でフィードを有効にする場合は **必須** です。
  Atom の ``link`` /
  ``id`` の値と、HTML のフィードディスカバリに使われます。
* ``html_theme`` — 同梱テーマを使う場合は ``"maatlog-default"`` を、あるいは
  Theme API 互換のサードパーティテーマを指定します。
* ``html_search_language`` をはじめとする Sphinx の検索関連設定には手を加えません。
  MaatLog は独自の検索インデックスをインストールしません

ヘッダーバナー
--------------

公式テーマのヘッダーバナーは、既存の設定だけで組み立てられます。
バナー専用の
設定はありません

* ``html_logo`` — バナー左端のロゴ。
  未設定ならロゴは出力されません
* ``project`` — サイト名 (``maatlog.site.title``)
* ``maatlog_tagline`` — サイト名の下のタグライン。
  未設定なら出力されません

検索フォームは Sphinx の ``searchbox.html`` をそのまま使います

配色パレット
------------

``maatlog_palette`` で、選択中のテーマが提供する配色から 1 つを選びます::

    maatlog_palette = "neon"

``conf.py`` で Sphinx の ``pygments_style`` を明示した場合、シンタックスハイライトは
そちらが勝ち、MaatLog はパレット由来のスタイルを当てません。
コードブロックの背景・境界・
地の文字色はこの場合もパレットに従います

``None`` （未設定）はそのテーマの既定パレットを意味します。
``"indigo"`` のような
リテラルを既定にしないのは、既定名の異なる第三者テーマと食い違うためです

公式テーマ（ ``maatlog-base`` / ``maatlog-default``）が提供するのは ``indigo`` （既定）、
``github``、 ``solarized``、 ``nord``、 ``neon`` の 5 種です。
読者に見えるのは従来どおり
ライト／ダークのトグルだけで、パレットはビルド時に固定されます

テーマが提供しない名前や、パレット非対応のテーマへの指定はビルドを失敗させ、
利用できる名前を列挙します。
パレットの契約は :doc:`theme-api` を参照してください

タクソノミー辞書
----------------

``maatlog_tags``、 ``maatlog_categories``、 ``maatlog_authors`` が ``None`` の場合、
投稿で使われた ID は自動登録され、表示名は ID と同じになります。
マッピングを指定した
場合は、そのキーのみが許可され、未定義の ID は ``maatlog.taxonomy.undefined`` を
発生させます

キーは ``[a-z0-9][a-z0-9._-]*`` に一致する必要があります。
値は空でない表示名で
なければなりません。
設定済みでも公開済み投稿に使われていない ID は、アーカイブページも
インベントリオブジェクトも生成しません

著者プロフィール
----------------

``maatlog_author_profiles`` は著者の外部リンクを保持する設定です。
キーは著者 ID で、 ``maatlog_authors`` と同じ ``[a-z0-9][a-z0-9._-]*`` に一致する必要があります。
値は ``links`` キーだけを持つ辞書です。
表示名は ``maatlog_authors`` を唯一の情報源とするため、こちらには置きません

``links`` の各要素は次のキーを持ちます

:``type``: 必須。
    リンク種別。
    受け取り時に小文字へ正規化されます
:``url``: 必須。
    ``http`` または ``https`` の絶対 URL
:``label``: 任意。
    省略した場合は ``type`` から既定ラベルを生成します

``type`` は ``github``、 ``x``、 ``bluesky``、 ``linkedin``、 ``website``、 ``rss`` を標準で扱います。
これ以外の値はエラーにせず、汎用アイコンへフォールバックします

アイコンは MaatLog がインライン SVG として出力します。
外部 CDN も追加の静的アセットも必要としません。
``linkedin`` はブランドロゴを同梱せず、汎用アイコンとテキストラベルで表示します（理由はリポジトリの ``NOTICE`` を参照してください）

``type`` または ``url`` の欠落、および ``http`` / ``https`` 以外の URL は ``maatlog.author.link-invalid`` としてビルドを失敗させます

``maatlog_authors`` との相互参照は検証しません。
``maatlog_authors`` が ``None`` のとき ID は投稿から自動登録されるため、対応する表示名が無くても不正ではありません

アーカイブのルート
------------------

``maatlog_archive_docname`` は生成ページのルート docname です（デフォルトは
``blog``）。
先頭・末尾のスラッシュ、空のセグメント、 ``.``、 ``..`` を含まない相対的な
Sphinx ドキュメント名でなければなりません

生成されるパス（ルートが ``blog`` の場合）:

* 全投稿: ``blog``、 ``blog/page/<n>``
* タグ: ``blog/tag/<id>``、 ``blog/tag/<id>/page/<n>``
* カテゴリ: ``blog/category/<id>``、…
* 著者: ``blog/author/<id>``、…
* 月: ``blog/month/YYYY-MM``、…
* サイト Atom フィード: ``blog/atom.xml``
* タクソノミーフィード: ``blog/<axis>/<id>/atom.xml``

ブログのホーム
--------------

``maatlog_home_docname`` に既存の docname（例: ``"index"``）を指定すると、そのページが
ブログのホームになります。
ユーザは導入文をそのドキュメントに書き、その下にテーマが
投稿一覧を描画します

* ホームに並ぶ件数は ``maatlog_page_size`` と同じです。
* ホームはページ送りを持たず、末尾の「All posts」からアーカイブルートへ送ります。
* ホームが有効なとき、アーカイブルート 1 ページ目の hero は出ません。
* 指定した docname が存在しないときは ``maatlog.home.docname-unknown`` を警告して
  ホーム化を無効にします。
* テーマが ``maatlog/home.html`` を持たないときは
  ``maatlog.theme.home-template-missing`` を警告し、通常のページとして描画します

フィード
--------

``maatlog_generate_feeds`` が ``True`` で、かつビルダーが完全な HTML の場合:

* ``html_baseurl`` の設定が必須です
* ビルド成功後にサイトフィードとタクソノミーフィードが書き出されます
* ``maatlog_feed_taxonomies`` でフィードを生成する軸を選択します（``tag``、
  ``category``、 ``author``、 ``month``）
* ``maatlog_feed_limit`` はフィードあたりのエントリ数の上限です

``maatlog_generate_feeds = False`` を設定すると、フィード生成とディスカバリリンクを
スキップします

タイムゾーンとビルド時刻
------------------------

* オフセットのない投稿日時は ``maatlog_timezone`` で解釈されます。
* 公開月アーカイブは、UTC の日付ではなく、設定されたタイムゾーンの暦月（``YYYY-MM``）
  を使います。
* ``SOURCE_DATE_EPOCH`` はビルド時刻を固定し、CI ホスト間で公開・非公開の境界を
  再現可能にします

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
    maatlog_author_profiles = {
        "alice": {
            "links": [
                {"type": "github", "url": "https://github.com/alice"},
                {"type": "x", "url": "https://x.com/alice", "label": "@alice"},
            ],
        },
    }
    maatlog_archive_docname = "blog"
    maatlog_page_size = 10
    maatlog_generate_feeds = True
    maatlog_feed_taxonomies = ("tag", "category", "author", "month")
    maatlog_feed_limit = 20
