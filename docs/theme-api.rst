Theme API
=========

MaatLog のテーマは Sphinx の HTML テーマに小さな契約を加えたものです。
すなわち、
マニフェスト、必須のテンプレートと Jinja ブロック、安定した  ``maatlog`` コンテキスト
名前空間、セマンティックな CSS クラス、そして CSS カスタムプロパティです

API バージョン
--------------

Theme API の現在のバージョンは **1.5** です。
``api = "1.0"`` を宣言するテーマは
引き続き受理されます

開発が安定するまでの間、Theme API の更新は下位互換しない破壊的変更です。
新しいコアは、以前の ``api`` を宣言するテーマを受理し続けることを約束しません。
パッケージは公開済みですが既知の利用者はいないため、破壊的更新を選びます

* **メジャー** — 必須テンプレート、コンテキストキー、セマンティクス、必須クラスに
  対する非互換な変更
* **マイナー** — 任意のキー・ブロック・クラスの追加、および互換性のある拡張

コアはメジャー ``1`` を実装するテーマを受け入れます。
テーマがコアの提供するマイナー
より高いバージョンを要求する場合、検証は失敗します。
現在の 1.5 コアは 1.0 / 1.1 / 1.2 / 1.3 / 1.4 テーマを受理しますが、次の Theme API 更新が
同じ約束を引き継ぐとは限りません

1.0 から 1.1 で追加された任意の契約:

* **任意キー** — ``maatlog.site`` （``SiteView``）、 ``maatlog.page_kind`` の
  ``"home"``、 ``PostView.taxonomies`` / ``PostCardView.taxonomies``
  （``PostTaxonomiesView``）、 ``ArchiveView.is_home``
* **任意テンプレート** — ``maatlog/home.html``、
  ``maatlog/components/post-grid.html``
* **任意ブロック** — ``maatlog_home_intro``
* **任意クラス** — ``.maatlog-taxonomy-link``、 ``.maatlog-home-intro``、
  ``.maatlog-home-archive-link``

1.1 から 1.2 で追加された任意の契約:

* **任意テンプレート** — ``maatlog/components/banner.html``、
  ``maatlog/components/nav-sidebar.html``、
  ``maatlog/components/toc-sidebar.html``
* **任意ブロック** — ``maatlog_banner``、 ``maatlog_nav``、 ``maatlog_toc``
* **任意クラス** — ``.maatlog-skip-link``、 ``.maatlog-banner``、
  ``.maatlog-banner-brand``、 ``.maatlog-banner-logo``、 ``.maatlog-banner-title``、
  ``.maatlog-banner-tagline``、 ``.maatlog-banner-search``、 ``.maatlog-layout``、
  ``.maatlog-layout-has-toc``、 ``.maatlog-layout-page-normal``、 ``.maatlog-layout-page-home``、
  ``.maatlog-layout-page-archive``、 ``.maatlog-layout-page-post``、
  ``.maatlog-layout-main``、 ``.maatlog-nav``、
  ``.maatlog-nav-toctree``、 ``.maatlog-toc``、 ``.maatlog-toc-headings``、
  ``.maatlog-toc-posts``
* **任意 CSS カスタムプロパティ** — ``--maatlog-main-width``、
  ``--maatlog-nav-width``、
  ``--maatlog-toc-width``、 ``--maatlog-banner-background``、
  ``--maatlog-banner-height``
* **保証の格上げ** — ``maatlog.taxonomies`` と ``maatlog.feeds`` は、投稿・
  アーカイブ・ホームだけでなく **すべての HTML ページ** で populated になります
* **投稿カードのアンカー** — 公式 ``post-grid.html`` が ``card_anchor`` を渡した
  カードは ``id="maatlog-post-<slug>"`` を持ちます
* **要素種別の変更** —  ``.maatlog-sidebar`` のルート要素が ``<aside>`` から
  ``<div>`` に変わりました。
  ナビゲーションのランドマークは外側の
  ``<nav class="maatlog-nav">`` が担います。
  クラス名による契約は変わりませんが、
  ``aside.maatlog-sidebar`` を選択している CSS は当たらなくなります
* **レイアウト状態クラス** —  ``.maatlog-layout`` は、そのページが実際に
  ``<aside class="maatlog-toc">`` を出力するときだけ ``maatlog-layout-has-toc`` を
  併せ持ちます。
  判定は ``layout.html`` の ``maatlog_has_toc`` が一度だけ行います。
  派生テンプレートが root-level で ``maatlog_has_toc`` を定義していれば、親レイアウト
  はその値を尊重します。
  未定義のときだけ標準条件を計算します。
   ``maatlog_toc`` ブロックを上書きして標準と異なる条件で TOC を出力するときは、
  同じテンプレートの root-level で ``maatlog_has_toc`` を明示してください。
  手順は下記「 ``maatlog_toc`` を上書きする」を参照してください。
   ``maatlog.page_kind`` は、同じ要素に ``maatlog-layout-page-normal``、
  ``maatlog-layout-page-home``、 ``maatlog-layout-page-archive``、
  ``maatlog-layout-page-post`` のいずれかとして出力されます。
  ページ種別クラスと
  ``maatlog-layout-has-toc`` は独立した状態であり、同時に付く場合があります

1.2 から 1.3 で追加された任意の契約:

* ライト／ダークの配色トークンと ``<html data-theme="light|dark">`` （後述）
* テーマ JavaScript の目印 ``<html class="maatlog-js">`` （後述）
* 任意コンポーネント ``maatlog/components/theme-toggle.html`` （後述）
* テンプレートコンテキスト ``maatlog.version``

1.3 から 1.4 で追加された任意の契約:

* **任意キー** — ``TaxonomyItemView.is_current``。
  そのページが当該分類の
  アーカイブ（ページ送りを含む）のとき ``True`` になります
* **任意テンプレート** —  ``maatlog/components/search.html``
* **任意クラス** — ``.maatlog-search``、 ``.maatlog-search-input``、
  ``.maatlog-taxonomy-list``、 ``.maatlog-taxonomy-item``、
   ``.maatlog-taxonomy-label``、 ``.maatlog-taxonomy-count``
* **任意 CSS カスタムプロパティ** — ``--maatlog-sticky-top``
  （``calc(var(--maatlog-banner-height) + var(--maatlog-space-md))``。sticky なヘッダの
  下端であり、 ``.maatlog-nav`` と  ``.maatlog-toc`` の ``top`` と ``max-height``
  はこの値から計算します）
* **挙動の変更** — ``maatlog/components/banner.html`` は Sphinx の
  ``searchbox.html`` を include しなくなり、 ``maatlog/components/search.html``
  を include します。
  ``.maatlog-banner-search`` ラッパは残るため、クラス名に
  よる契約は変わりません。
  ``<h3 id="searchlabel">`` と送信ボタンと
  ``#searchbox`` のインライン script は出力されなくなります
* **挙動の変更** —  ``.maatlog-banner`` は ``position: sticky`` になります
* **テーマ JavaScript** —  ``.maatlog-toc-headings`` 内のページ内リンクのうち、
  読者が見ている見出しに対応するものへ ``aria-current="true"`` を付け替えます。
  ``IntersectionObserver`` が無い環境では何もしません
* **任意ブロック** — ``maatlog_post_eyebrow``、 ``maatlog_post_tagline``、
  ``maatlog_post_hero``。
  いずれも  ``maatlog/post.html`` の
  ``maatlog_post_header`` の内側にあり、上書きすれば差し替えられます
* **任意クラス** — ``.maatlog-post-eyebrow``、 ``.maatlog-post-tagline``、
  ``.maatlog-post-hero-image``、 ``.maatlog-post-grid``
* **挙動の変更** — ``maatlog_post_header`` が
  ``<header class="maatlog-post-header">`` の内側に、eyebrow（カテゴリ）、
  ``<h1>``、tagline（抜粋）、 ``maatlog_post_meta``、hero image をこの順で
  出力します。
  ``maatlog_post_meta`` は必須ブロックのままであり、ブロック名も
  ``.maatlog-post-meta`` 以下の入れ子も変わりません
* **挙動の変更** — カテゴリは  ``maatlog_post_meta`` から
  ``maatlog_post_eyebrow`` へ移りました。
  日時・著者・タグ・外部投稿バッジは
   ``maatlog_post_meta`` に残ります
* **挙動の変更** — 外部投稿の本文から ``<p class="maatlog-post-excerpt">`` が
  無くなりました。
  抜粋は tagline が出します
* **挙動の変更** — ``maatlog/components/post-grid.html`` は、featured 以外の
  カードを ``<div class="maatlog-post-grid">`` で包みます

1.4 から 1.5 で追加された任意の契約:

* **任意マニフェストキー** — ``palettes`` （``default_palette``）（後述「パレット」）
* **任意設定** — ``maatlog_palette`` （ :doc:`configuration` を参照）
* **任意 CSS ファイル** — ``static/palettes/<name>.css``
* **契約の明文化** — 装飾トークンにはコントラスト比の下限を課さない（後述
  「パレット」）

.. warning::

    ``maatlog_post_meta`` が ``<header class="maatlog-post-header">`` の
   **内側** に移りました。ブロック名・クラス名・その下の入れ子は変わりませんが、
   ``.maatlog-post-header + .maatlog-post-meta`` のような兄弟セレクタを書いて
   いる CSS は当たらなくなります。

必須テンプレートと必須ブロックは 1.0 から変わっていません。
``api = "1.0"``、
``api = "1.1"``、 ``api = "1.2"``、 ``api = "1.3"``、 ``api = "1.4"`` を宣言するテーマは引き続き検証を通ります。
ただし
``implementation = "inherits-base"`` のテーマは、宣言する API に関わらず
 ``maatlog-base`` の新しいページ外枠・配色トークン・テーマ JavaScript を継承します。
描画結果は以前のマイナーと同じにはならず、下記「``maatlog_sidebar`` ブロックの位置」の
移行が必要な場合があります

マニフェスト
------------

*選択された* テーマのルートに ``maatlog-theme.toml`` が必要です::

    [maatlog]
    api = "1.0"
    implementation = "inherits-base"

 ``implementation`` の値:

* ``inherits-base`` — Sphinx の継承チェーンに  ``maatlog-base`` を含む
*  ``standalone`` —  ``maatlog-base`` を継承せず、必須テンプレートをすべてテーマ自身が
  同梱する

 ``[maatlog]`` 配下の未知のキーは、前方互換性のために無視されます。
 ``[maatlog]``、
``api``、 ``implementation`` は必須です。
親テーマだけがマニフェストを持っていても
不十分で、最終的に選択されたテーマ自身が API 対応を宣言しなければなりません

公式テーマ
----------

*  ``maatlog-base`` — 契約の実装（Sphinx の ``basic`` を継承）
* ``maatlog-default`` — すぐに使えるテーマ（ ``maatlog-base`` を継承）

デフォルトテーマは次のように有効化します::

    html_theme = "maatlog-default"

サイトのタグライン
~~~~~~~~~~~~~~~~~~

サイトのタグラインは ``conf.py`` の ``maatlog_tagline`` で設定します。
Theme API
の ``maatlog.site.tagline`` に渡されます::

    maatlog_tagline = "Notes on Sphinx"

``maatlog.archive.is_home`` が真のページで、サイト名の下に表示されます。
未設定の
場合、要素は出力されません

ページ外枠
----------

 ``maatlog-base`` は ``layout.html`` を同梱し、Sphinx ``basic`` テーマの
``header``、 ``content``、 ``relbar1``、 ``relbar2`` を上書きします。
可視出力は
次の順序です

#. ヘッダーバナー (``maatlog_banner`` ブロック)
#. ページレイアウト — 基本は左ナビ ( ``maatlog_nav``) と本文 (``body``) の
   2 カラム。
   右目次 ( ``maatlog_toc``) を出力するページだけ、右目次を加えた
   3 カラム

 ``relbar1`` と  ``relbar2`` はどちらも空にしてあり、Sphinx の関連リンク帯は
出力しません。
可視ナビゲーションは MaatLog のバナー、サイドバー、投稿前後ナビ、
アーカイブページャが提供します

``main.document > div.documentwrapper > div.bodywrapper > div.body`` の入れ子は
そのまま残しています。
``basic.css`` や sphinx-copybutton、利用者の追加 CSS が
この構造に依存している為です

``--maatlog-content-width`` と ``--maatlog-main-width`` は派生テーマが行長や中央列の
上限を置くための任意プロパティです。
公式 default の wide layout は中央列を ``1fr``
にし、余剰の viewport 幅を main へ渡します。
投稿・アーカイブ外枠、カード一覧、
通常ページ本文、投稿本文はいずれも main 幅を使います。
左右 nav/TOC の最大幅は
従来どおり ``--maatlog-nav-width`` / ``--maatlog-toc-width`` が担います

``maatlog_sidebar`` ブロックの位置
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Theme API 1.2 から、 ``maatlog/components/sidebar.html`` の出力はレイアウトの左
カラムに移りました。
``maatlog/post.html`` と ``maatlog/archive.html`` の
``maatlog_sidebar`` ブロックは必須ブロックとして残っていますが、中身は空です。
``implementation = "standalone"`` のテーマは自前の ``layout.html`` を持つので、
この変更の影響を受けません

``implementation = "inherits-base"`` のテーマは、宣言する API が 1.0 / 1.1
でも継承先の新しいページ外枠を受け取ります。
旧テーマが ``maatlog_sidebar``
ブロック内で  ``maatlog/components/sidebar.html`` を描画している場合は、左カラムと
本文内で二重表示になるため、その include を削除してください

``html_sidebars`` は使いません
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

左ナビは ``html_sidebars`` の設定を読みません。
既定の ``localtoc.html`` が右
サイドバーと目次を二重に表示してしまう為です。
左ナビを拡張するときは
 ``maatlog_nav`` ブロックを上書きしてください::

    {%- extends "maatlog-base/layout.html" -%}

    {%- block maatlog_nav -%}
    {{ super() }}
    <section class="my-extra-nav">...</section>
    {%- endblock maatlog_nav -%}

左ナビの文書一覧は Sphinx の可視 toctree に従い、 ``:hidden:`` の toctree は
表示しません。
可視 toctree に明示した文書は MaatLog の公開状態では再フィルター
しないため、draft / scheduled 投稿を可視 toctree に入れるとタイトルも表示されます

 ``maatlog_toc`` を上書きする
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

右目次を標準と異なる条件で出すときは、同じ ``layout.html`` の root-level で
``maatlog_has_toc`` を明示します。
親レイアウトは定義済みの値を尊重します。
未定義のときだけ標準条件を計算します::

    {%- extends "maatlog-base/layout.html" -%}
    {%- set maatlog_has_toc = True -%}

    {%- block maatlog_toc -%}
    <aside class="maatlog-toc" data-maatlog-component="toc">
      <p>On this page</p>
    </aside>
    {%- endblock maatlog_toc -%}

``maatlog_has_toc`` を ``False`` にした場合も、親はその値を上書きしません

ページ外枠は JavaScript に依存しません
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

公式テーマのページ外枠（サイドバーの追従、狭い画面での並べ替え）は JavaScript を
使いません。
サイドバーの追従は CSS の ``position: sticky``、狭い画面での並べ替えは
``grid-template-areas`` だけで行っています。
ライト／ダークの初期適用は、後述の
テーマ JavaScript が担当します

必須テンプレート
----------------

*  ``maatlog/post.html``
* ``maatlog/archive.html``
* ``maatlog/components/post-card.html``
* ``maatlog/components/pagination.html``
*  ``maatlog/components/sidebar.html``
* ``maatlog/components/feed-links.html``

``post.html`` と ``archive.html`` は完全なページテンプレートです（``layout.html``
を継承しても構いません）。
コンポーネントは include / import 専用で、暗黙のグローバル
変更に依存してはいけません

任意テンプレート
----------------

次のテンプレートは任意です。
テーマが同梱しなくても検証は通ります

* ``maatlog/home.html`` — ``maatlog_home_docname`` で指定されたページ。
  テーマが
  これを解決できないとき、MaatLog は ``maatlog.theme.home-template-missing`` を
  警告し、そのページを通常のページとして描画します。
  このときブログのトップは
  アーカイブルートの 1 ページ目が引き受け、その  ``is_home`` が真になります
* ``maatlog/components/post-grid.html`` — featured グリッドと通常カード一覧。
  ``cards`` と任意の ``featured_count`` を受け取り、 ``maatlog`` 名前空間は読みません
*  ``maatlog/components/search.html`` — 検索フォーム。
   ``banner.html`` から
  ``include`` されます
* ``maatlog/components/theme-toggle.html`` — バナーのテーマ切替ボタン。
   ``banner.html`` から ``include`` されます。
   差し替えるテーマは、自身の
  テンプレートディレクトリに同名ファイルを置いてください

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
     - カテゴリ、タイトル、タグライン、 ``maatlog_post_meta``、hero image
   * -  ``maatlog_post_meta``
     - 日時、著者、タグ、外部投稿バッジ
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
とは異なる描画をしても構いません。
公式テーマはこの条件で hero と featured 3 件を
出します。
テーマがこの分岐を実装せず、すべてのアーカイブを同じ体裁で描画しても
検証は通ります

ブロックの契約では  ``maatlog`` コンテキスト名前空間のみを使います（場当たり的な
トップレベルのグローバル変数は使いません）

任意の Jinja ブロック
---------------------

次のブロックは任意です。
テーマが実装しなくても検証は通ります

* ``maatlog_home_intro`` — ホームでユーザ本文 ``{{ body }}`` を出します

コンテキスト名前空間
--------------------

MaatLog のすべてのテンプレートは、トップレベルの  ``maatlog`` マッピングを受け取り
ます。
キーは常に存在し、使われない値は ``None`` または空のシーケンスになります

::

    maatlog.api_version   # "1.5"
    maatlog.version       # MaatLog ディストリビューションのバージョン（例 "0.1.0"）
    maatlog.page_kind     # "post" | "archive" | "home" | "normal"
    maatlog.post          # PostView | None
    maatlog.posts         # tuple[PostCardView, ...]
    maatlog.archive       # ArchiveView | None
    maatlog.pagination    # PaginationView | None
    maatlog.navigation    # NavigationView
    maatlog.feeds         # tuple[FeedLinkView, ...]
    maatlog.taxonomies    # TaxonomyNavigationView
    maatlog.site          # SiteView

**SiteView** のフィールド: ``title``、 ``tagline``、 ``archive_url``。
 ``archive_url`` はそのページからアーカイブルート 1 ページ目への相対 URL です

**PostView** のフィールド: ``title``、 ``slug``、 ``docname``、 ``page_url``、
``canonical_url``、 ``external_url``、 ``published_at``、 ``expires_at``、
``excerpt``、 ``image_url``、 ``tags``、 ``categories``、 ``authors``、
``body_html``、 ``taxonomies`` （``PostTaxonomiesView``）

**PostCardView** のフィールド: ``title``、 ``page_url``、 ``published_at``、
``excerpt``、 ``image_url``、 ``tags``、 ``categories``、 ``authors``、
 ``external_url``、 ``slug``、 ``taxonomies`` （``PostTaxonomiesView``）

**PostTaxonomiesView** のフィールドは  ``tags``、 ``categories``、 ``authors``
で、各要素は **TaxonomyLinkView** （ ``id``、 ``label``、 ``url``）です。
``url`` は
解決できないとき空文字になるので、テーマは ``{% if link.url %}`` で出し分けます

**TaxonomyNavigationView** のフィールドは  ``tags``、 ``categories``、 ``authors``
で、各要素は **TaxonomyView** （ ``id``、 ``label``、 ``items``）です。
``items`` の
各要素は **TaxonomyItemView** （ ``id``、 ``label``、 ``url``、 ``count``、 ``is_current``）
です。
``is_current`` はそのページが当該分類のアーカイブ（ページ送りを含む）のとき
``True`` になります

**ArchiveView** のフィールド: ``kind``、 ``id``、 ``label``、 ``docname``、
``page_number``、 ``total_posts``、 ``is_home``。
サイト全体のリストでは ``kind`` が
``all``、 ``id`` が ``None`` になります。
``is_home`` はこのページをブログのトップ
として描画すべきかを示します。
サイト内で真になるページはちょうど 1 つです

**PaginationView** のフィールド: ``current``、 ``total_pages``、 ``previous_url``、
``next_url``、 ``pages``。
``pages`` はページ番号と URL の組を順に並べたものです

**NavigationView** のフィールド: ``newer_post``、 ``older_post``。
いずれも
``PostCardView | None`` です

セマンティッククラスとデータ属性
--------------------------------

必須クラスには ``.maatlog-post``、 ``.maatlog-post-header``、
``.maatlog-post-meta``、 ``.maatlog-post-body``、 ``.maatlog-post-navigation``、
``.maatlog-post-list``、 ``.maatlog-post-card``、 ``.maatlog-taxonomy``、
``.maatlog-archive``、 ``.maatlog-pagination``、 ``.maatlog-sidebar``、
``.maatlog-external-link``、 ``.maatlog-feed-link`` が含まれます

記事コンテナは ``<article class="maatlog-post">``、アーカイブコンテナは
``<section class="maatlog-archive">`` として出力します。
公式テーマの CSS は
要素型を含めてセレクタを書いており、これは  ``maatlog`` ドメインのロールが出す
インライン ``<code class="xref maatlog maatlog-post">`` と区別するためです。
カスタムテーマが別の要素で出した場合、公式テーマのレイアウト規則は適用されません

コンポーネントのルート要素は
``data-maatlog-component="post|post-card|archive|pagination|sidebar|feed-links"``
を公開します。
MaatLog のコアは必須の JavaScript を同梱しません。
データ属性は
プログレッシブエンハンスメントのための安定したフックです

公式テーマは、必須クラスに加えて次の任意クラスを使います。
テーマがこれらを実装
しなくても検証は通ります

* ``.maatlog-hero`` — ブログのトップ（``maatlog.archive.is_home``）の導入領域。
  ``.maatlog-archive-header`` と併記され、 ``data-maatlog-component="hero"`` を
  持ちます
* ``.maatlog-hero-title``、 ``.maatlog-hero-tagline``、 ``.maatlog-hero-meta``、
  ``.maatlog-hero-updated``
* ``.maatlog-post-featured`` — トップで先頭 3 件を並べるグリッド
* ``.maatlog-post-card-featured`` — featured として描画された投稿カード
* ``.maatlog-post-list-heading`` — featured の下に続く一覧の見出し
*  ``.maatlog-post-grid`` — featured 以外のカードを並べるグリッド
* ``.maatlog-post-eyebrow`` — タイトルの上に出るカテゴリ
*  ``.maatlog-post-tagline`` — タイトルの下に出る抜粋
* ``.maatlog-post-hero-image`` — 記事ヘッダ末尾の装飾画像（``alt=""``）
* ``.maatlog-pagination-more`` — 次ページへの文章による導線
* ``.maatlog-taxonomy-more``、 ``.maatlog-taxonomy-year`` — サイドバーの折り畳み
* ``.maatlog-taxonomy-list``、 ``.maatlog-taxonomy-item``、 ``.maatlog-taxonomy-label``、
   ``.maatlog-taxonomy-count`` — サイドバーのタクソノミー一覧と項目
* ``.maatlog-taxonomy-link`` — 投稿・カードのタクソノミーリンク（または URL が
  空のときの ``span``）
* ``.maatlog-search``、 ``.maatlog-search-input`` — 検索フォームと検索入力欄
*  ``.maatlog-home-intro`` — ホームのユーザ本文
* ``.maatlog-home-archive-link`` — ホーム末尾からアーカイブルートへの導線
* ``.maatlog-banner-actions`` — バナー右側の操作領域（検索欄とテーマ切替）
* ``.maatlog-theme-toggle`` — テーマ切替ボタン。
  ``data-maatlog-component="theme-toggle"``、
  ``type="button"``、状態は ``aria-pressed``  で表します
* ``.maatlog-theme-toggle-icon-light`` / ``.maatlog-theme-toggle-icon-dark`` —
  現在のテーマを示す装飾アイコン（``aria-hidden="true"``）
* ``.maatlog-theme-toggle-label`` — 支援技術向けの可視テキスト（視覚的には隠されます）

テーマ JavaScript
~~~~~~~~~~~~~~~~~

Theme API 1.3 から、 ``maatlog-base`` は ``static/maatlog.js`` を同梱し、
``layout.html`` の ``scripts`` ブロックから **head 内で同期読み込み** します
（``defer`` や ``type="module"`` を付けると初期描画前に間に合いません）

このスクリプトは次を行います

* ``<html>`` に ``class="maatlog-js"`` を付ける（JavaScript が動いている目印）
*  ``localStorage`` の ``maatlog-theme`` （``"light"`` / ``"dark"``）を読み、
  値があれば ``<html data-theme=...>`` を設定する
* Sphinx が出力する ``<link id="pygments_dark_css">`` の ``media`` を、
  明示選択に合わせて ``"all"`` / ``"not all"`` に書き換える

``DOMContentLoaded`` の時点で ``.maatlog-theme-toggle`` を探し、見つかれば次を配線します。
テーマがトグルを同梱しない場合は何もせず、他の動作はそのまま働きます

* 現在の実効テーマを ``aria-pressed`` （ダークで ``"true"``）として反映する
* クリックで実効テーマを反転し、 ``data-theme`` の更新・ ``localStorage`` への保存・
  ``aria-pressed``  の同期を行う（ページの再読み込みは発生しません）
* 保存済みの選択が無い間だけ、OS 設定の変更に追従して ``aria-pressed``  を更新する

 ``localStorage`` が利用できない環境（プライベートウィンドウ等）では未設定として扱い、
 ``prefers-color-scheme`` による表示にフォールバックします。
 書き込みに失敗した場合も
そのページ内での切替は動作し、選択が次のページへ引き継がれないだけです

CSS カスタムプロパティ
----------------------

 ``maatlog-base`` は少なくとも次を定義します:

* ``--maatlog-content-width``
* ``--maatlog-sidebar-width``
* ``--maatlog-space-xs``、 ``--maatlog-space-sm``、 ``--maatlog-space-md``、
  ``--maatlog-space-lg``
* ``--maatlog-color-background``、 ``--maatlog-color-surface``
* ``--maatlog-color-text``、 ``--maatlog-color-muted``、 ``--maatlog-color-link``、
  ``--maatlog-color-accent``、 ``--maatlog-color-border``、
  ``--maatlog-color-control-border``
* ``--maatlog-code-background``、 ``--maatlog-code-text``、 ``--maatlog-code-border``
* ``--maatlog-card-background``、 ``--maatlog-banner-background``
* ``--maatlog-sticky-top``

テーマは使用箇所でフォールバックを用意するべきです。
名前付きプロパティの意味は、
同一メジャー API バージョン内では変わりません

ライトとダーク
~~~~~~~~~~~~~~

Theme API 1.3 から、公式テーマは配色トークンを 3 つのブロックで定義します

.. code-block:: css

   :root { /* ライト */ }

   @media (prefers-color-scheme: dark) {
     :root:not([data-theme="light"]) { /* ダーク */ }
   }

   :root[data-theme="dark"] { /* ダーク */ }

``<html>`` の  ``data-theme`` が未設定のときは OS の  ``prefers-color-scheme`` に従い、
``"light"`` / ``"dark"`` が設定されているときはそちらが優先されます。
JavaScript が
無効な環境では  ``data-theme`` が付かないため、 ``prefers-color-scheme`` のみで決まります

3 つのブロックはいずれも ``color-scheme`` （ライトで ``light``、ダークで ``dark``）を
宣言します。
これが無いと、検索フォームやスクロールバーなどブラウザが描く部品だけが
常にライトのまま残ります

リンク色はセマンティッククラスの付いた要素だけでなく ``a`` 全体に
 ``--maatlog-color-link`` を適用します。
 Sphinx 自身が出力する toctree・サイドバー・
本文リンクにユーザーエージェント既定の青／訪問済み紫が残ると、ダーク地では
コントラスト比を満たせないためです

コードブロックは Sphinx の ``pygments_style`` / ``pygments_dark_style`` （``theme.conf``）で
ライト・ダークの 2 種類を出力します。
地色と枠はテーマ側が
``--maatlog-code-background`` /  ``--maatlog-code-border`` で上書きします

パレット
~~~~~~~~

Theme API 1.5 から、テーマは複数の配色を提供できます。
差し替わるのは 17 個の
カラートークンだけで、余白・角丸・フォント・モーションは全パレット共通です。
読者ではなくサイト作者がビルド時に固定します

テーマは提供するパレットと既定を ``maatlog-theme.toml`` で宣言します::

    [maatlog]
    api = "1.5"
    implementation = "standalone"
    default_palette = "indigo"
    palettes = ["indigo", "github", "solarized", "nord", "neon"]

* ``palettes`` は提供するパレット名の一覧、 ``default_palette`` はそのうちの 1 つ
  でなければなりません。
  名前は ``[a-z0-9][a-z0-9-]*`` に限ります。
* ``palettes`` を宣言しないテーマはパレット非対応として扱われます。
  ``api = "1.0"``
  から ``"1.4"`` の既存テーマはすべてこれに当たり、何もしなければ従来どおり動きます。
* 宣言を持たないテーマは、Sphinx の継承チェーンを辿って最初に見つかった宣言を
  使います。
  ``maatlog-default`` は自分では宣言せず、 ``maatlog-base`` の宣言を
  継承します

既定パレットの値は、テーマ自身の ``static/maatlog.css`` の 3 ブロックがそのまま
持ちます。
追加パレットは ``static/palettes/<name>.css`` に、同じ 3 ブロック構成で
17 個のカラートークンだけを書きます

.. code-block:: css

   :root { /* ライト */ }

   @media (prefers-color-scheme: dark) {
     :root:not([data-theme="light"]) { /* ダーク */ }
   }

   :root[data-theme="dark"] { /* ダーク */ }

2 つのダークブロックは同一内容でなければなりません。
``color-scheme`` はテーマの
``maatlog.css`` が宣言済みのため、パレットファイルには書きません

パレットファイルは、選ばれたときだけ ``maatlog.css`` の **後に** 読み込まれます。
既定パレットが選ばれているとき（ ``maatlog_palette`` 未設定を含む）は読み込まれません。
既定の値をパレットファイルにも書くと二重管理になるためです

``palettes`` に宣言した名前に対応する ``static/palettes/<name>.css`` が継承チェーン上に
無い場合、既定パレットを除いてビルドは
``maatlog.theme.palette-stylesheet-missing`` で失敗します

コントラスト
^^^^^^^^^^^^

パレットは 17 トークンすべてを 3 ブロックで定義する義務を負います。
欠けたトークンは
テーマの既定値にフォールバックし、2 つのパレットが混ざった配色になります

文字とその背景の組み合わせには WCAG 2.2 の AA（4.5:1）を、操作できる部品の境界である
 ``--maatlog-color-control-border`` には 3:1 を課します

装飾トークンには最低コントラスト比を課しません。
対象は ``--maatlog-color-border``、
``--maatlog-code-border``、および面としての ``--maatlog-inline-code-background`` です。
これらは WCAG 1.4.11 が求める「UI コンポーネントの識別に必要な視覚情報」に当たりません
（カードは余白と ``surface`` の差で判別できます）。
3:1 を課すと、すべてのパレットが
強いグレー線の外観に固定されてしまいます

公式テーマのパレット
^^^^^^^^^^^^^^^^^^^^

``maatlog-base`` と ``maatlog-default`` は次の 5 種を提供します

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - 名前
     - 説明
   * - ``indigo``
     - 既定。青紫のリンクに青緑のアクセント
   * - ``github``
     - GitHub Primer から着想した派生。青のリンクに紫のアクセント
   * - ``solarized``
     - Solarized（Ethan Schoonover, MIT）から着想した派生。ベージュの地に低彩度の青と黄
   * - ``nord``
     - Nord（Arctic Ice Studio, MIT）から着想した派生。寒色の灰青に落ち着いた青緑
   * - ``neon``
     - MaatLog 独自。黒地にビビッドなピンク

``github`` / ``solarized`` / ``nord`` は既存の配色から着想を得た派生であり、公式配色
そのものではありません。
``neon`` は MaatLog 独自の配色で、出典を持ちません

シンタックスハイライトはパレットに追従しません。
コードブロックの枠（背景・境界・
文字色）はパレットのトークンに従いますが、Pygments のスタイルは ``theme.conf`` の
 ``pygments_style`` / ``pygments_dark_style`` が決めます

検証
----

完全な HTML ビルダーでは、 ``builder-inited`` の時点で MaatLog が選択されたテーマを
検証します。
検証対象は、マニフェストの有無とスキーマ、API のメジャー／マイナー、
``inherits-base`` の場合は継承関係、 ``standalone`` の場合は必須テンプレート、必須の
Jinja ブロック、そして ``static/maatlog.css`` が解決できることです。
失敗は致命的な
診断になります（例: ``maatlog.theme.api-incompatible``）

パレットも同じ経路で検証されます。
宣言されたパレットの CSS が継承チェーン上に無い
場合は ``maatlog.theme.palette-stylesheet-missing``、パレット非対応のテーマに既定以外の
``maatlog_palette`` を指定した場合は ``maatlog.theme.palette-unsupported``、テーマが
提供しない名前を指定した場合は ``maatlog.theme.palette-unknown`` で失敗し、いずれも
そのテーマで利用できるパレット名を示します
