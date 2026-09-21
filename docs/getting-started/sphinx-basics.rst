Sphinx 入門
===========

このページでは、MaatLog を使うために必要な範囲に限定して Sphinx の基礎を説明します。
Sphinx 自体の詳しい使い方は
`Sphinx 公式ドキュメント <https://www.sphinx-doc.org/>`__ を参照してください

Sphinx とは
-----------

`Sphinx <https://www.sphinx-doc.org/>`__ は、reStructuredText や MyST Markdown で書いた
文書から HTML などの成果物を生成するドキュメントビルダーです。
MaatLog は Sphinx の拡張として動作し、Sphinx が生成する文書の一部を投稿として扱います

プロジェクトの構成要素
----------------------

Sphinx プロジェクトは、主に次の 3 つの要素で構成されます

``conf.py``
    プロジェクトの設定を書く Python ファイルです。
    使用する拡張や出力の設定をここで指定します。
    MaatLog 固有の設定は :doc:`../configuration` を参照してください

``index.rst``
    ビルドの起点になる文書です。
    ``conf.py`` の ``root_doc`` という設定で指定します。
    既定値は ``"index"`` です

``toctree``
    文書どうしの階層と目次を定義するディレクティブです。
    どの toctree にも含まれない文書があると、Sphinx は警告
    （``toc.not_included``）を出します。
    ``:doc:`` などで他の文書から参照されていても、toctree に載っていなければ
    警告は消えません。
    toctree に載せない文書には、先頭へ ``:orphan:`` フィールドを付けて
    警告を防ぎます

reStructuredText と MyST Markdown
---------------------------------

Sphinx は reStructuredText(``.rst``)を標準の記法として使います。
``myst_parser`` 拡張を有効にすると、MyST Markdown(``.md``)でも文書を書けます。
MaatLog はどちらの形式にも対応しており、投稿のメタデータの書き方
(フィールドリストか YAML front matter か)が異なります。
詳細は :doc:`../authoring` を参照してください

directive と role の基本
------------------------

Sphinx には、文書内に構造化された要素を挿入する仕組みが 2 つあります

directive
    ``.. 名前::`` の形式で書く、ブロック単位の拡張構文です。
    以下は注記を挿入する ``note`` directive の例です ::

        .. note::

           これは注記です

role
    ``:名前:`テキスト``\` の形式で書く、インライン単位の拡張構文です。
    以下は他の文書への相互参照を挿入する ``doc`` role の例です ::

        :doc:`../configuration`

MaatLog は ``maatlog:post-list`` directive や ``:maatlog:post:`` role など、投稿を扱う
ための directive と role を追加します。
詳細は :doc:`../authoring` を参照してください

``sphinx-build`` とビルダーの基本
---------------------------------

Sphinx プロジェクトをビルドするコマンドを実行します ::

    sphinx-build -M html docs docs/_build

``-M html`` は ``html`` ビルダーでビルドするという指定です。
（1 つ目がソースディレクトリ、2 つ目が出力先です）。
ビルダーは出力形式を決める仕組みで、Sphinx には ``html`` ・ ``dirhtml`` ・ ``text`` など
複数のビルダーがあります。
MaatLog がアーカイブやフィードなどのブログ機能一式を保証するのは ``html`` と
``dirhtml`` ビルダーだけです。
ビルダーごとのサポート範囲は :doc:`../builders` を参照してください

次に読むページ
--------------

MaatLog 固有の使い方を知りたい場合は :doc:`maatlog-basics` へ進んでください
