Theme API
=========

MaatLog のテーマは Sphinx の HTML テーマに小さな契約を加えたものです。すなわち、
マニフェスト、必須のテンプレートと Jinja ブロック、安定した ``maatlog`` コンテキスト
名前空間、セマンティックな CSS クラス、そして CSS カスタムプロパティです。

API バージョン
--------------

Theme API の現在のバージョンは **1.2** です。``api = "1.0"`` を宣言するテーマは
引き続き受理されます。

開発が安定するまでの間、Theme API の更新は下位互換しない破壊的変更です。
新しいコアは、以前の ``api`` を宣言するテーマを受理し続けることを約束しません。
パッケージは公開済みですが既知の利用者はいないため、破壊的更新を選びます。

* **メジャー** — 必須テンプレート、コンテキストキー、セマンティクス、必須クラスに
  対する非互換な変更
* **マイナー** — 任意のキー・ブロック・クラスの追加、および互換性のある拡張

コアはメジャー ``1`` を実装するテーマを受け入れます。テーマがコアの提供するマイナー
より高いバージョンを要求する場合、検証は失敗します。
現在の 1.1 コアは 1.0 テーマを受理しますが、次の Theme API 更新が同じ約束を
引き継ぐとは限りません。

1.0 から 1.1 で追加された任意の契約:

* **任意キー** — ``maatlog.site``（``SiteView``）、``maatlog.page_kind`` の
  ``"home"``、``PostView.taxonomies`` / ``PostCardView.taxonomies``
  （``PostTaxonomiesView``）、``ArchiveView.is_home``
* **任意テンプレート** — ``maatlog/home.html``、
  ``maatlog/components/post-grid.html``
* **任意ブロック** — ``maatlog_home_intro``
* **任意クラス** — ``.maatlog-taxonomy-link``、``.maatlog-home-intro``、
  ``.maatlog-home-archive-link``

1.1 から 1.2 で追加された任意の契約:

* **任意テンプレート** — ``maatlog/components/banner.html``、
  ``maatlog/components/nav-sidebar.html``、
  ``maatlog/components/toc-sidebar.html``
* **任意ブロック** — ``maatlog_banner``、``maatlog_nav``、``maatlog_toc``
* **任意クラス** — ``.maatlog-skip-link``、``.maatlog-banner``、
  ``.maatlog-banner-brand``、``.maatlog-banner-logo``、``.maatlog-banner-title``、
  ``.maatlog-banner-tagline``、``.maatlog-banner-search``、``.maatlog-layout``、
  ``.maatlog-layout-main``、``.maatlog-nav``、``.maatlog-nav-toctree``、
  ``.maatlog-toc``、``.maatlog-toc-headings``、``.maatlog-toc-posts``
* **任意 CSS カスタムプロパティ** — ``--maatlog-nav-width``、
  ``--maatlog-toc-width``、``--maatlog-banner-background``、
  ``--maatlog-banner-height``
* **保証の格上げ** — ``maatlog.taxonomies`` と ``maatlog.feeds`` は、投稿・
  アーカイブ・ホームだけでなく **すべての HTML ページ** で populated になります
* **投稿カードのアンカー** — 公式 ``post-grid.html`` が ``card_anchor`` を渡した
  カードは ``id="maatlog-post-<slug>"`` を持ちます
* **要素種別の変更** — ``.maatlog-sidebar`` のルート要素が ``<aside>`` から
  ``<div>`` に変わりました。ナビゲーションのランドマークは外側の
  ``<nav class="maatlog-nav">`` が担います。クラス名による契約は変わりませんが、
  ``aside.maatlog-sidebar`` を選択している CSS は当たらなくなります

必須テンプレートと必須ブロックは 1.0 から変わっていません。``api = "1.0"`` や
``api = "1.1"`` を宣言するテーマは引き続き検証を通ります。ただし
``implementation = "inherits-base"`` のテーマは、宣言する API に関わらず
``maatlog-base`` の新しいページ外枠を継承します。描画結果は 1.1 と同じにはならず、
下記「``maatlog_sidebar`` ブロックの位置」の移行が必要な場合があります。

マニフェスト
------------

*選択された* テーマのルートに ``maatlog-theme.toml`` が必要です::

    [maatlog]
    api = "1.0"
    implementation = "inherits-base"

``implementation`` の値:

* ``inherits-base`` — Sphinx の継承チェーンに ``maatlog-base`` を含む
* ``standalone`` — ``maatlog-base`` を継承せず、必須テンプレートをすべてテーマ自身が
  同梱する

``[maatlog]`` 配下の未知のキーは、前方互換性のために無視されます。``[maatlog]``、
``api``、``implementation`` は必須です。親テーマだけがマニフェストを持っていても
不十分で、最終的に選択されたテーマ自身が API 対応を宣言しなければなりません。

公式テーマ
----------

* ``maatlog-base`` — 契約の実装（Sphinx の ``basic`` を継承）
* ``maatlog-default`` — すぐに使えるテーマ（``maatlog-base`` を継承）

デフォルトテーマは次のように有効化します::

    html_theme = "maatlog-default"

サイトのタグライン
~~~~~~~~~~~~~~~~~~

サイトのタグラインは ``conf.py`` の ``maatlog_tagline`` で設定します。Theme API
の ``maatlog.site.tagline`` に渡されます::

    maatlog_tagline = "Notes on Sphinx"

``maatlog.archive.is_home`` が真のページで、サイト名の下に表示されます。未設定の
場合、要素は出力されません。

ページ外枠
----------

``maatlog-base`` は ``layout.html`` を同梱し、Sphinx ``basic`` テーマの
``header``、``content``、``relbar1``、``relbar2`` を上書きします。可視出力は
次の順序です。

#. ヘッダーバナー (``maatlog_banner`` ブロック)
#. 3 カラムのレイアウト — 左ナビ (``maatlog_nav``)、本文 (``body``)、
   右目次 (``maatlog_toc``)

``relbar1`` と ``relbar2`` はどちらも空にしてあり、Sphinx の関連リンク帯は
出力しません。可視ナビゲーションは MaatLog のバナー、サイドバー、投稿前後ナビ、
アーカイブページャが提供します。

``main.document > div.documentwrapper > div.bodywrapper > div.body`` の入れ子は
そのまま残しています。``basic.css`` や sphinx-copybutton、利用者の追加 CSS が
この構造に依存している為です。

``maatlog_sidebar`` ブロックの位置
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Theme API 1.2 から、``maatlog/components/sidebar.html`` の出力はレイアウトの左
カラムに移りました。``maatlog/post.html`` と ``maatlog/archive.html`` の
``maatlog_sidebar`` ブロックは必須ブロックとして残っていますが、中身は空です。
``implementation = "standalone"`` のテーマは自前の ``layout.html`` を持つので、
この変更の影響を受けません。

``implementation = "inherits-base"`` のテーマは、宣言する API が 1.0 / 1.1
でも継承先の新しいページ外枠を受け取ります。旧テーマが ``maatlog_sidebar``
ブロック内で ``maatlog/components/sidebar.html`` を描画している場合は、左カラムと
本文内で二重表示になるため、その include を削除してください。

``html_sidebars`` は使いません
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

左ナビは ``html_sidebars`` の設定を読みません。既定の ``localtoc.html`` が右
サイドバーと目次を二重に表示してしまう為です。左ナビを拡張するときは
``maatlog_nav`` ブロックを上書きしてください::

    {%- extends "maatlog-base/layout.html" -%}

    {%- block maatlog_nav -%}
    {{ super() }}
    <section class="my-extra-nav">...</section>
    {%- endblock maatlog_nav -%}

左ナビの文書一覧は Sphinx の可視 toctree に従い、``:hidden:`` の toctree は
表示しません。可視 toctree に明示した文書は MaatLog の公開状態では再フィルター
しないため、draft / scheduled 投稿を可視 toctree に入れるとタイトルも表示されます。

JavaScript は同梱しません
~~~~~~~~~~~~~~~~~~~~~~~~~

公式テーマは JavaScript を同梱しません。サイドバーの追従は CSS の
``position: sticky``、狭い画面での並べ替えは ``grid-template-areas`` だけで
行っています。

必須テンプレート
----------------

* ``maatlog/post.html``
* ``maatlog/archive.html``
* ``maatlog/components/post-card.html``
* ``maatlog/components/pagination.html``
* ``maatlog/components/sidebar.html``
* ``maatlog/components/feed-links.html``

``post.html`` と ``archive.html`` は完全なページテンプレートです（``layout.html``
を継承しても構いません）。コンポーネントは include / import 専用で、暗黙のグローバル
変更に依存してはいけません。

任意テンプレート
----------------

次のテンプレートは任意です。テーマが同梱しなくても検証は通ります。

* ``maatlog/home.html`` — ``maatlog_home_docname`` で指定されたページ。テーマが
  これを解決できないとき、MaatLog は ``maatlog.theme.home-template-missing`` を
  警告し、そのページを通常のページとして描画します。このときブログのトップは
  アーカイブルートの 1 ページ目が引き受け、その ``is_home`` が真になります
* ``maatlog/components/post-grid.html`` — featured グリッドと通常カード一覧。
  ``cards`` と任意の ``featured_count`` を受け取り、``maatlog`` 名前空間は読みません

必須の Jinja ブロック
---------------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - ブロック
     - 責務
   * - ``maatlog_head``
     - canonical URL、フィードディスカバリ、テーマ固有の head 追加要素
   * - ``maatlog_post_header``
     - タイトルと公開まわりの装飾
   * - ``maatlog_post_meta``
     - 日時、タクソノミー、著者、外部投稿バッジ
   * - ``maatlog_post_body``
     - Sphinx が描画した本文（または外部投稿の抜粋 + リンク）
   * - ``maatlog_post_navigation``
     - 新しい／古い投稿へのリンク
   * - ``maatlog_archive_header``
     - アーカイブの種別、ラベル、件数
   * - ``maatlog_archive_items``
     - 投稿カードの並び
   * - ``maatlog_pagination``
     - ページリンク
   * - ``maatlog_sidebar``
     - タクソノミーナビゲーションとフィード

``maatlog_archive_header`` と ``maatlog_archive_items`` は、
``maatlog.archive.is_home`` が真のページをブログのトップとして扱い、他のアーカイブ
とは異なる描画をしても構いません。公式テーマはこの条件で hero と featured 3 件を
出します。テーマがこの分岐を実装せず、すべてのアーカイブを同じ体裁で描画しても
検証は通ります。

ブロックの契約では ``maatlog`` コンテキスト名前空間のみを使います（場当たり的な
トップレベルのグローバル変数は使いません）。

任意の Jinja ブロック
---------------------

次のブロックは任意です。テーマが実装しなくても検証は通ります。

* ``maatlog_home_intro`` — ホームでユーザ本文 ``{{ body }}`` を出します

コンテキスト名前空間
--------------------

MaatLog のすべてのテンプレートは、トップレベルの ``maatlog`` マッピングを受け取り
ます。キーは常に存在し、使われない値は ``None`` または空のシーケンスになります。

::

    maatlog.api_version   # "1.2"
    maatlog.page_kind     # "post" | "archive" | "home" | "normal"
    maatlog.post          # PostView | None
    maatlog.posts         # tuple[PostCardView, ...]
    maatlog.archive       # ArchiveView | None
    maatlog.pagination    # PaginationView | None
    maatlog.navigation    # NavigationView
    maatlog.feeds         # tuple[FeedLinkView, ...]
    maatlog.taxonomies    # TaxonomyNavigationView
    maatlog.site          # SiteView

**SiteView** のフィールド: ``title``、``tagline``、``archive_url``。
``archive_url`` はそのページからアーカイブルート 1 ページ目への相対 URL です。

**PostView** のフィールド: ``title``、``slug``、``docname``、``page_url``、
``canonical_url``、``external_url``、``published_at``、``expires_at``、
``excerpt``、``image_url``、``tags``、``categories``、``authors``、
``body_html``、``taxonomies``（``PostTaxonomiesView``）。

**PostCardView** のフィールド: ``title``、``page_url``、``published_at``、
``excerpt``、``image_url``、``tags``、``categories``、``authors``、
``external_url``、``slug``、``taxonomies``（``PostTaxonomiesView``）。

**PostTaxonomiesView** のフィールドは ``tags``、``categories``、``authors``
で、各要素は **TaxonomyLinkView** （``id``、``label``、``url``）です。``url`` は
解決できないとき空文字になるので、テーマは ``{% if link.url %}`` で出し分けます。

**ArchiveView** のフィールド: ``kind``、``id``、``label``、``docname``、
``page_number``、``total_posts``、``is_home``。サイト全体のリストでは ``kind`` が
``all``、``id`` が ``None`` になります。``is_home`` はこのページをブログのトップ
として描画すべきかを示します。サイト内で真になるページはちょうど 1 つです。

**PaginationView** のフィールド: ``current``、``total_pages``、``previous_url``、
``next_url``、``pages``。``pages`` はページ番号と URL の組を順に並べたものです。

**NavigationView** のフィールド: ``newer_post``、``older_post``。いずれも
``PostCardView | None`` です。

セマンティッククラスとデータ属性
--------------------------------

必須クラスには ``.maatlog-post``、``.maatlog-post-header``、
``.maatlog-post-meta``、``.maatlog-post-body``、``.maatlog-post-navigation``、
``.maatlog-post-list``、``.maatlog-post-card``、``.maatlog-taxonomy``、
``.maatlog-archive``、``.maatlog-pagination``、``.maatlog-sidebar``、
``.maatlog-external-link``、``.maatlog-feed-link`` が含まれます。

コンポーネントのルート要素は
``data-maatlog-component="post|post-card|archive|pagination|sidebar|feed-links"``
を公開します。MaatLog のコアは必須の JavaScript を同梱しません。データ属性は
プログレッシブエンハンスメントのための安定したフックです。

公式テーマは、必須クラスに加えて次の任意クラスを使います。テーマがこれらを実装
しなくても検証は通ります。

* ``.maatlog-hero`` — ブログのトップ（``maatlog.archive.is_home``）の導入領域。
  ``.maatlog-archive-header`` と併記され、``data-maatlog-component="hero"`` を
  持ちます
* ``.maatlog-hero-title``、``.maatlog-hero-tagline``、``.maatlog-hero-meta``、
  ``.maatlog-hero-updated``
* ``.maatlog-post-featured`` — トップで先頭 3 件を並べるグリッド
* ``.maatlog-post-card-featured`` — featured として描画された投稿カード
* ``.maatlog-post-list-heading`` — featured の下に続く一覧の見出し
* ``.maatlog-pagination-more`` — 次ページへの文章による導線
* ``.maatlog-taxonomy-more``、``.maatlog-taxonomy-year`` — サイドバーの折り畳み
* ``.maatlog-taxonomy-link`` — 投稿・カードのタクソノミーリンク（または URL が
  空のときの ``span``）
* ``.maatlog-home-intro`` — ホームのユーザ本文
* ``.maatlog-home-archive-link`` — ホーム末尾からアーカイブルートへの導線

CSS カスタムプロパティ
----------------------

``maatlog-base`` は少なくとも次を定義します:

* ``--maatlog-content-width``
* ``--maatlog-sidebar-width``
* ``--maatlog-space-xs``、``--maatlog-space-sm``、``--maatlog-space-md``、
  ``--maatlog-space-lg``
* ``--maatlog-color-text``、``--maatlog-color-muted``、``--maatlog-color-link``、
  ``--maatlog-color-border``
* ``--maatlog-card-background``

テーマは使用箇所でフォールバックを用意するべきです。名前付きプロパティの意味は、
同一メジャー API バージョン内では変わりません。

検証
----

完全な HTML ビルダーでは、``builder-inited`` の時点で MaatLog が選択されたテーマを
検証します。検証対象は、マニフェストの有無とスキーマ、API のメジャー／マイナー、
``inherits-base`` の場合は継承関係、``standalone`` の場合は必須テンプレート、必須の
Jinja ブロック、そして ``static/maatlog.css`` が解決できることです。失敗は致命的な
診断になります（例: ``maatlog.theme.api-incompatible``）。
