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

``maatlog_author_profiles`` は著者プロフィールページ用のリッチデータを保持する設定です。
キーは著者 ID で、 ``maatlog_authors`` と同じ ``[a-z0-9][a-z0-9._-]*`` に一致する必要があります。
値は次の 7 キーのみを持つ辞書です（すべて任意）。
表示名は ``maatlog_authors`` が唯一の情報源であり、こちらには置きません

.. list-table::
   :header-rows: 1
   :widths: 22 18 12 48

   * - キー
     - 型
     - 既定
     - 意味
   * - ``role``
     - 空でない ``str``
     - 省略
     - 肩書き・役割
   * - ``avatar``
     - srcdir 相対 URI の ``str``
     - 省略
     - プロフィールのアバター画像。
       記事の ``maatlog-image`` と同じ安全性検査（symlink 不可・srcdir 脱出不可・実在必須）を通ります
   * - ``bio_short``
     - 空でない ``str``
     - 省略
     - ヘッダ直下に出す短い自己紹介
   * - ``interests``
     - 空でない文字列のシーケンス
     - ``()`` 
     - 興味・専門分野の一覧
   * - ``links``
     - リンク辞書のシーケンス
     - ``()`` 
     - 外部リンク（下記）
   * - ``featured_posts``
     - 空でない文字列のシーケンス
     - ``()`` 
     - その著者の **published** 投稿の slug。
       順序どおりプロフィールに並びます
   * - ``about_docname``
     - 相対 docname の ``str``
     - 省略
     - About 文書（通常の Sphinx ページ）の docname。
       toctree に載せなくて構いません

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

プロフィールを設定した著者のアーカイブ 1 ページ目（``blog/author/<id>`` など）は
``maatlog/profile.html`` で描画されます。
2 ページ目以降は従来どおり ``maatlog/archive.html`` です。
``maatlog_authors`` が ``None`` のとき ID は投稿から自動登録されるため、
``maatlog_authors`` を設定している場合だけ、プロフィールの著者 ID がその辞書に存在するかを検証します

診断
~~~~

設定の形が不正なときは ``maatlog.config.invalid`` です。
相互参照とアバターは ``env-updated`` の時点で検証し、問題があればビルドを失敗させます

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - コード
     - 条件
   * - ``maatlog.author.profile-unknown``
     - ``maatlog_authors`` を設定しているのに、プロフィールの著者 ID がその辞書に無い
   * - ``maatlog.author.featured-unknown``
     - ``featured_posts`` の slug が published 投稿として存在しない
   * - ``maatlog.author.featured-foreign``
     - ``featured_posts`` の slug が、その著者の published 投稿ではない
   * - ``maatlog.author.about-unknown``
     - ``about_docname`` が存在しない Sphinx 文書を指している
   * - ``maatlog.image.invalid``
     - ``avatar`` の URI が記事代表画像と同じ理由で拒否された（絶対 URL・srcdir 外・クエリ付きなど）
   * - ``maatlog.image.missing``
     - ``avatar`` が指すファイルが srcdir 内に存在しない

例
~~

::

    maatlog_authors = {
        "alice": "Alice",
    }
    maatlog_author_profiles = {
        "alice": {
            "role": "Editor & Developer",
            "avatar": "authors/alice.png",
            "bio_short": "Python / Cloud / Sphinx developer.",
            "interests": ["Python", "Cloud", "Sphinx"],
            "links": [
                {"type": "github", "url": "https://github.com/example"},
                {"type": "website", "url": "https://example.com/"},
            ],
            "about_docname": "authors/alice",
        },
    }

既定著者
--------

``maatlog_default_author``
~~~~~~~~~~~~~~~~~~~~~~~~~~

著者を特定できないページ（トップページ、タグ・カテゴリ・アーカイブ・検索結果など）で
右ペインに表示する著者の ID です。既定値は ``None`` で、未設定のときはそれらのページに
Author Summary を表示しません。

.. code-block:: python

   maatlog_default_author = "alice"

``maatlog_authors`` を設定している場合、そこに無い ID を指定するとビルドが
``maatlog.config.invalid`` で失敗します。``maatlog_authors`` を設定していない場合、
著者 ID は記事から動的に登録されるため、この照合は行いません。

``maatlog_authors`` の先頭要素が暗黙に選ばれることはありません。

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

本文の幅
--------

``maatlog_content_width`` は、記事本文（段落・リスト・引用・見出し）と通常ページの
prose（段落・リスト・引用。見出しは対象外）の最大行幅を指定します。
値は CSS の ``max-width`` として使える宣言値です

* 既定は ``None`` です。このときテーマの既定値
  ``clamp(42rem, 24rem + 16vw, 60rem)`` をそのまま使います
* ``"100%"`` を指定すると、本文が中央列いっぱいまで広がります。
  ウルトラワイドや 4K で本文の右端と右目次の間に空白が残るのを解消できます
* ``"72rem"`` のような固定値、 ``"clamp(42rem, 70vw, 90rem)"`` のような
  CSS 関数も指定できます
* ``maatlog-default`` ではコードブロック・表・画像はこの制限の対象外であり、
  設定に関わらず中央列の幅を使えます。
  ``maatlog-base`` を直接使う場合は ``article`` 全体がこの幅で抑えられるため、
  コードブロック等も連動して広がります

::

    maatlog_content_width = "100%"

値はテーマの ``<style>`` へそのまま埋め込まれるため、
宣言や要素の外へ出られる文字（ ``<``、 ``>``、 ``{``、 ``}``、 ``;``、
``\``、 ``/*`` ）を含む値はビルド時に
``maatlog.config.invalid`` で拒否します。
空文字と文字列以外の値も同様に拒否します。
値が幅として意味を成すかどうかまでは検査しません。
CSS として無効な値を指定したときの挙動はブラウザに依存し、
テーマの既定値へ戻るとは限りません。
カスタムプロパティはほぼ任意の値を受け取るため、 ``max-width`` が計算値時に無効となり、
幅の制限そのものが外れることがあります

この設定は ``maatlog-base`` を継承したテーマで有効です。
継承しないテーマは ``maatlog_config_style`` ブロックを実装した場合にだけ
反映します。 :doc:`theme-api` を参照してください

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
            "role": "Editor & Developer",
            "avatar": "authors/alice.png",
            "bio_short": "Python / Cloud / Sphinx developer.",
            "interests": ["Python", "Cloud", "Sphinx"],
            "links": [
                {"type": "github", "url": "https://github.com/alice"},
                {"type": "x", "url": "https://x.com/alice", "label": "@alice"},
            ],
            "about_docname": "authors/alice",
        },
    }
    maatlog_archive_docname = "blog"
    maatlog_page_size = 10
    maatlog_generate_feeds = True
    maatlog_feed_taxonomies = ("tag", "category", "author", "month")
    maatlog_feed_limit = 20
    maatlog_content_width = None
