MaatLog 入門
============

このページでは、MaatLog の概要から最初の投稿を作成して HTML をビルドするまでの
最短経路を説明します。
Sphinx の基礎知識がまだない場合は、先に :doc:`sphinx-basics` を読んでください

MaatLog とは
------------

MaatLog は、Sphinx のドキュメントプロジェクトを静的なブログへ変える拡張です。
``maatlog-post: true`` と宣言した文書だけが投稿として扱われ、タグやカテゴリ、著者、
公開日時などのメタデータをもとにアーカイブや Atom フィードを生成します

Sphinx との関係
---------------

MaatLog は Sphinx のドキュメントタイトルや toctree、検索インデックス、Pygments、
画像ノードなどを置き換えません。
通常の Sphinx ページと投稿は、同じプロジェクト内に混在できます。
ブログ機能一式(アーカイブ・Theme API・Atom フィード)を保証するのは ``html`` と
``dirhtml`` ビルダーに限られます。
詳細は :doc:`../builders` を参照してください

MaatLog の有効化
----------------

``conf.py`` の ``extensions`` に ``"maatlog"`` を追加します

.. code-block:: python

    extensions = [
        "maatlog",
    ]

MyST Markdown で投稿を書く場合は ``myst_parser`` も追加します

.. code-block:: python

    extensions = [
        "maatlog",
        "myst_parser",
    ]

最小構成の conf.py
------------------

MaatLog を有効化した最小構成の例です

.. code-block:: python

    project = "My Blog"
    html_baseurl = "https://example.com/"
    extensions = [
        "maatlog",
        "myst_parser",
    ]

    html_theme = "maatlog-default"
    maatlog_timezone = "Asia/Tokyo"

``html_baseurl`` はフィードを有効にした ``html`` / ``dirhtml`` ビルダーでは **必須** です。
全設定値の一覧は :doc:`../configuration` を参照してください

最初の投稿を書く
----------------

投稿になるのは ``maatlog-post`` が真偽値の ``true`` の文書だけです

reStructuredText の場合、タイトルの前にフィールドリストを置きます ::

    :maatlog-post: true
    :maatlog-published-at: 2026-08-01T09:00:00+09:00
    :maatlog-slug: first-post

    最初の投稿
    ==========

    本文…

MyST Markdown の場合、同じ名前のキーを YAML front matter に書きます ::

    ---
    maatlog-post: true
    maatlog-published-at: 2026-08-01T09:00:00+09:00
    maatlog-slug: first-post
    ---

    # 最初の投稿

    本文…

``maatlog-slug`` は投稿ごとに一意な文字列で、 ``[a-z0-9][a-z0-9._-]*`` という
パターンに従います。
その他のメタデータキー(タグ、カテゴリ、著者、抜粋、画像など)は :doc:`../authoring`
を参照してください
投稿を toctree に載せない場合は、reStructuredText では先頭に ``:orphan:`` を、MyST Markdown では front matter に ``orphan: true`` を付けます

通常ページと投稿の違い
----------------------

``maatlog-post: true`` を宣言していない文書は、通常の Sphinx ページのままです。
そのような文書のメタデータは扱わず、アーカイブにも掲載しません。
投稿でない文書に他の ``maatlog-*`` 投稿フィールドを書くとビルドエラーになります

公開状態
--------

MaatLog は、ビルド時刻と投稿のメタデータから公開状態を判定します

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - 状態
     - 判定条件
   * - draft
     - ``maatlog-published-at`` が未指定
   * - scheduled
     - ``maatlog-published-at`` がビルド時刻より後
   * - expired
     - ``maatlog-expires-at`` があり、ビルド時刻がそれ以降
   * - published
     - 上記のいずれにも当てはまらない

アーカイブや Atom フィードに現れるのは published の投稿だけです。
判定ロジックの詳細は :doc:`../authoring` を参照してください

タグ・カテゴリ・著者
--------------------

タグとカテゴリ、著者は ``conf.py`` 側で許可リストを定義し、投稿側でどれを使うかを
指定するという 2 段構成です

.. code-block:: python

    maatlog_tags = {"sphinx": "Sphinx", "python": "Python"}
    maatlog_categories = {"engineering": "Engineering"}
    maatlog_authors = {"alice": "Alice"}

投稿側では次のように指定します ::

    :maatlog-tags: sphinx, python
    :maatlog-categories: engineering
    :maatlog-authors: alice

``conf.py`` の許可リストに存在しない ID を投稿側で指定すると、ビルドエラーになります。
許可リストを省略した場合は投稿で使った ID がそのまま表示名になります。
設定側の詳細は :doc:`../configuration` 、投稿側のルールは :doc:`../authoring` を
参照してください

基本的な画像利用
----------------

投稿に代表画像を 1 枚設定するには、 ``maatlog-image`` フィールドに投稿
ファイルからの相対パスを指定します。
解決後のパスはソースディレクトリ内に
収まっている必要があります ::

    :maatlog-image: first-post.png

指定したパスの画像ファイルが存在しないとビルドが失敗するため、先に配置しておきます。
画像を ``_static/`` など別のディレクトリに置く場合、投稿がサブディレクトリにあれば
``../_static/images/first-post.png`` のようなパスを指定します。
レスポンシブ画像は :doc:`../configuration` 、トップ画像は :doc:`../authoring` を
参照してください

HTML のビルド
-------------

:doc:`sphinx-basics` で説明した ``sphinx-build`` コマンドでビルドします ::

    sphinx-build -M html docs docs/_build

（引数の意味は :doc:`sphinx-basics` を参照してください）。
ビルドが成功すると、 ``docs/_build/html`` に静的サイトが生成されます。
``docs/_build/html/index.html`` をブラウザで開いて確認してください。
投稿の一覧は ``blog`` というページに生成され、 ``html`` ビルダーでは ``docs/_build/html/blog.html`` になります

次に読むページ
--------------

設定を網羅的に知りたい場合は :doc:`../configuration` 、投稿のメタデータ全体を
確認したい場合は :doc:`../authoring` を参照してください
