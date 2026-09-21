.. _first-blog:

============================
MaatLog で最初のブログを作る
============================

概要
====

Sphinx と :term:`MaatLog` を使って、最初のブログ記事を公開できる状態まで進めます。
所要時間の目安は 15 分です

前提条件
========

- Python 3.14 以上と ``pip`` が使えること
- コマンドラインの基本操作ができること
- Sphinx の知識は不要です。
  必要な範囲は本文中で説明します

手順の流れ
==========

#. 新規 Sphinx プロジェクトを作成する
#. :term:`MaatLog` を導入する
#. 最初の記事を書く
#. HTML をビルドする
#. ブラウザで確認する

手順
====

新規 Sphinx プロジェクトを作成する
----------------------------------

#. 作業ディレクトリを作成して移動する ::

    mkdir my-maatlog-blog
    cd my-maatlog-blog

#. 記事を置くディレクトリを作成する ::

    mkdir posts

#. Python の仮想環境を作成して有効化する ::

    python3 -m venv .venv && source .venv/bin/activate

   Windows（PowerShell）では ``py -m venv .venv`` で作成し、 ``.venv\Scripts\Activate.ps1`` で有効化する。
   ``&&`` でつないだコマンドは 1 行ずつ分けて実行する。
   bash / zsh と PowerShell 以外のシェルでは ``.venv/bin/`` （Windows は ``.venv\Scripts\`` ）内の対応する activate スクリプトで有効化する。
   Debian / Ubuntu で ``ensurepip`` が無いために失敗する場合は ``sudo apt install python3.14-venv`` で導入して同じコマンドを再実行するか、
   ``uv venv --seed --clear .venv && source .venv/bin/activate`` を使ってください。

#. プロジェクト直下に ``conf.py`` を作成する ::

    project = "My Blog"
    copyright = "2026, Example Author"
    author = "Example Author"
    language = "ja"
    exclude_patterns = ["_build", ".venv"]

#. トップページ ``index.rst`` を作成する ::

    =======
    My Blog
    =======

    Sphinx で作った最初のブログです。

MaatLog を導入する
------------------

#. :term:`MaatLog` をインストールする ::

    pip install maatlog

   ``uv`` を使う場合は ``uv pip install maatlog`` でも構いません。

#. ``conf.py`` の末尾に :term:`MaatLog` の設定を追記する ::

    extensions = [
        "maatlog",
    ]

    html_theme = "maatlog-default"
    html_baseurl = "https://example.com/"

    maatlog_timezone = "Asia/Tokyo"

   :term:`MaatLog` は既定で Atom フィードを生成するため、 ``html_baseurl`` の設定が
   必要です。設定項目の一覧は :doc:`/configuration` を参照してください。

最初の記事を書く
----------------

#. ``posts/hello-maatlog.rst`` を作成する ::

    :orphan:
    :maatlog-post: true
    :maatlog-published-at: 2026-09-19T09:00:00+09:00
    :maatlog-slug: hello-maatlog
    :maatlog-tags: sphinx, python
    :maatlog-categories: engineering
    :maatlog-authors: alice
    :maatlog-excerpt: MaatLog で書いた最初の記事です。

    Hello, MaatLog
    ==============

    これが MaatLog で書いた最初の記事です。

   先頭の ``maatlog-post: true`` を含むドキュメントが :term:`MaatLog` の :term:`投稿` に
   なります。
   :term:`投稿` は既定でどの toctree にも含めません。
   先頭の ``:orphan:`` フィールドが、Sphinx の「toctree に含まれていません」という
   警告を防ぎます。
   一覧は :term:`MaatLog` が自動生成するアーカイブページに表示されます。

   MyST Markdown で書く場合は、同じキーを YAML front matter に記述します。
   メタデータの全項目は :doc:`/authoring` を参照してください。

HTML をビルドする
-----------------

#. HTML をビルドする ::

    sphinx-build -M html . _build

#. ``build succeeded`` と表示され、警告が出ていないことを確認する

ブラウザで確認する
------------------

#. ブラウザで ``_build/html/blog.html`` を開き、「Hello, MaatLog」が投稿一覧に
   表示されていることを確認する

   ファイルをブラウザで開くコマンドの例です

   * macOS: ``open _build/html/blog.html``
   * Linux: ``xdg-open _build/html/blog.html``
   * Windows（PowerShell）: ``start _build/html/blog.html``

#. 一覧のカードをクリックし、 ``_build/html/posts/hello-maatlog.html`` に記事本文が
   表示されることを確認する

以上
