Theme API
=========

MaatLog のテーマは Sphinx の HTML テーマに小さな契約を加えたものです。すなわち、
マニフェスト、必須のテンプレートと Jinja ブロック、安定した ``maatlog`` コンテキスト
名前空間、セマンティックな CSS クラス、そして CSS カスタムプロパティです。

API バージョン
--------------

Theme API の初期バージョンは **1.0** です。

* **メジャー** — 必須テンプレート、コンテキストキー、セマンティクス、必須クラスに
  対する非互換な変更
* **マイナー** — 任意のキー・ブロック・クラスの追加、および互換性のある拡張

コアはメジャー ``1`` を実装するテーマを受け入れます。テーマがコアの提供するマイナー
より高いバージョンを要求する場合、検証は失敗します。

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

ブロックの契約では ``maatlog`` コンテキスト名前空間のみを使います（場当たり的な
トップレベルのグローバル変数は使いません）。

コンテキスト名前空間
--------------------

MaatLog のすべてのテンプレートは、トップレベルの ``maatlog`` マッピングを受け取り
ます。キーは常に存在し、使われない値は ``None`` または空のシーケンスになります。

::

    maatlog.api_version   # "1.0"
    maatlog.page_kind     # "post" | "archive" | "normal"
    maatlog.post          # PostView | None
    maatlog.posts         # tuple[PostCardView, ...]
    maatlog.archive       # ArchiveView | None
    maatlog.pagination    # PaginationView | None
    maatlog.navigation    # NavigationView
    maatlog.feeds         # tuple[FeedLinkView, ...]
    maatlog.taxonomies    # TaxonomyNavigationView

**PostView** のフィールド: ``title``、``slug``、``docname``、``page_url``、
``canonical_url``、``external_url``、``published_at``、``expires_at``、
``excerpt``、``image_url``、``tags``、``categories``、``authors``、
``body_html``。

**PostCardView** のフィールド: ``title``、``page_url``、``published_at``、
``excerpt``、``image_url``、``tags``、``categories``、``authors``、
``external_url``。

**ArchiveView** のフィールド: ``kind``、``id``、``label``、``docname``、
``page_number``、``total_posts``。サイト全体のリストでは ``kind`` が ``all``、
``id`` が ``None`` になります。

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
