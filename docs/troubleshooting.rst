======================
トラブルシューティング
======================

このページは、ビルドの警告やエラーメッセージの一部を手がかりに検索し、
該当する症状の節で原因と対処を確認する逆引きページです。
診断コードは
``maatlog.`` から始まる形式で表示されます

このページの例は、ソース位置を ``<プロジェクト>/`` で始まるプレースホルダで
示しています。
実際のビルド出力では、ソース位置を持つ診断はプロジェクトの絶対パスで表示され、
Sphinx のログ位置と診断本文の位置が二重に現れます ::

    <プロジェクト>/posts/example.rst.rst:1: ERROR: <プロジェクト>/posts/example.rst:1: ERROR: [maatlog.metadata.required] ...

先頭の ``example.rst.rst`` は、Sphinx がログ位置に ``source_suffix``
の先頭の拡張子（既定では ``.rst``）をもう一度付けた表記であり、
実在するファイル名ではありません。
``.md`` ソースでは ``example.md.rst`` のように表示されます

``maatlog.slug.duplicate`` や ``maatlog.feed.baseurl-required`` のように
ソース位置を持たない診断は、位置情報なしで表示されます

必須メタデータが不足している
============================

``maatlog-post: true`` を指定した投稿で、ドキュメントの見出しまたは
``maatlog-slug`` のいずれかが無いと、ビルドはエラーで停止します ::

    <プロジェクト>/posts/example.rst:1: ERROR: [maatlog.metadata.required] A post requires a document title; field=title; expected=a non-empty Sphinx document title
    <プロジェクト>/posts/example.rst:1: ERROR: [maatlog.metadata.required] A post requires a slug; field=maatlog-slug; expected=[a-z0-9][a-z0-9._-]*

診断コードはどちらも ``maatlog.metadata.required`` です。
対処は、ドキュメント本文の先頭に見出しを追加するか、 ``maatlog-slug``
フィールドを追加することです。
メタデータフィールドの一覧は
:doc:`authoring` の「メタデータスキーマ」節を参照してください

maatlog-slug が不正
===================

``maatlog-slug`` に大文字・空白・許可されていない記号を含めると、ビルドは
エラーで停止します ::

    <プロジェクト>/posts/example.rst:2: ERROR: [maatlog.slug.invalid] Invalid post slug; field=maatlog-slug; value='My Post!'; expected=[a-z0-9][a-z0-9._-]*

``maatlog-slug`` に文字列以外の値を指定した場合は、診断コードが
``maatlog.metadata.type`` になります。
対処は、小文字の英数字と ``.`` ・ ``_`` ・ ``-`` だけを使い、先頭を英数字に
することです。
スラッグの規則は :doc:`authoring` の「メタデータスキーマ」節を
参照してください

slug が重複している
===================

複数のドキュメントで同じ ``maatlog-slug`` を指定すると、ビルドはエラーで
停止します。
メッセージには重複しているファイルのパスがすべて列挙されます ::

    ERROR: [maatlog.slug.duplicate] Duplicate slug 'sphinx-extension' found in <プロジェクト>/posts/a.rst, <プロジェクト>/posts/b.rst; field=maatlog-slug; value='sphinx-extension'; expected=a unique slug across all posts

診断コードは ``maatlog.slug.duplicate`` です。
対処は、列挙されたファイルのいずれかの ``maatlog-slug`` を、他と重ならない
値に変更することです

未定義のタグ・カテゴリ・著者を指定している
==========================================

``maatlog-tags`` ・ ``maatlog-categories`` ・ ``maatlog-authors`` に、
``conf.py`` 側のタクソノミー辞書へ登録されていない ID を指定すると、
ビルドはエラーで停止します ::

    <プロジェクト>/posts/example.md:4: ERROR: [maatlog.taxonomy.undefined] Taxonomy ID is not configured; field=maatlog-tags; value='unknown-tag'; expected=an ID present in the corresponding MaatLog taxonomy config

診断コードは ``maatlog.taxonomy.undefined`` です。
ID 自体が ``[a-z0-9][a-z0-9._-]*`` のパターンに一致しない場合は、診断コードが
``maatlog.taxonomy-id.invalid`` になります。
対応するタクソノミー辞書(``maatlog_tags`` ・ ``maatlog_categories`` ・
``maatlog_authors``)が ``conf.py`` で ``None`` のままだと、未定義 ID の
所属チェックだけが行われず、使われた ID は自動登録されます。
ID の文字種チェック(``maatlog.taxonomy-id.invalid``)は、辞書の有無に
かかわらず行われます。
意図せず未定義 ID のチェックが効いていない場合は、まずこの3つの
設定値を確認してください。
タクソノミー辞書の設定方法は :doc:`configuration`
の「タクソノミー辞書」節を参照してください

MyST front matter の値が意図しない型になる
==========================================

MyST の front matter は YAML の暗黙の型付けに従うため、クォートしていない
値が意図しない型として解釈されることがあります。
詳しい規則は
:doc:`authoring` の「MyST Markdown」節を参照してください。
代表的な例は
次のとおりです

- ``maatlog-tags: [on, 1.2]`` のように書くと、 ``on`` は真偽値、 ``1.2`` は
  数値として解釈され、いずれも文字列ではなくなります
- ``maatlog-published-at: 2026-07-01`` のように時刻を省略すると、YAML の
  日付型として解釈され、MaatLog が受け付ける日時文字列にはなりません

どちらの場合も、診断コードは ``maatlog.metadata.type`` です。
シーケンス内の非文字列要素ごとに1件ずつ診断が出力されるため、
``maatlog-tags: [on, 1.2]`` の例では同じ診断が2件出力されます ::

    <プロジェクト>/posts/example.md:4: ERROR: [maatlog.metadata.type] Invalid metadata type; field=maatlog-tags; value=[True, 1.2]; expected=a string or sequence of strings
    <プロジェクト>/posts/example.md:4: ERROR: [maatlog.metadata.type] Invalid metadata type; field=maatlog-tags; value=[True, 1.2]; expected=a string or sequence of strings

対処は、曖昧になりうる値をクォートで囲むことと、日時には時刻とタイムゾーンの
オフセットを両方含めることです

公開日時の指定が不正
====================

``maatlog-published-at`` または ``maatlog-expires-at`` が ISO 8601 形式の
日時文字列として解釈できない場合や、オフセットを省略したローカル時刻が
夏時間の切り替えなどで一意に定まらない場合、ビルドはエラーで停止します ::

    <プロジェクト>/posts/example.rst:3: ERROR: [maatlog.datetime.invalid] Invalid datetime; field=maatlog-published-at; value='2026/07/01'; expected=an ISO 8601 datetime

診断コードは ``maatlog.datetime.invalid`` です。
``maatlog-expires-at`` が ``maatlog-published-at`` と同時刻か、それより前の
場合は、診断コードが ``maatlog.datetime.order`` になります。
``maatlog-published-at`` を指定せずに ``maatlog-expires-at`` だけを指定した
場合は、診断コードが ``maatlog.metadata.combination`` になります。
対処は、日時をタイムゾーンのオフセット付きの ISO 8601 形式で記述し、
``maatlog-expires-at`` を ``maatlog-published-at`` より後の時刻にすることです。
公開ステータスの判定条件は :doc:`authoring` の「公開ステータス」節を
参照してください

html_baseurl と Feed の設定
===========================

``maatlog_generate_feeds`` が既定値の ``True`` のまま、完全な HTML を出力する
ビルダーで ``html_baseurl`` を設定していないか、絶対 HTTP/HTTPS URL として
不正な値を設定していると、ビルドはエラーで停止します ::

    ERROR: [maatlog.feed.baseurl-required] html_baseurl is required for feed generation; field=html_baseurl; value=; expected=an absolute HTTP or HTTPS URL with a host and without userinfo, query, or fragment

診断コードは ``maatlog.feed.baseurl-required`` です。
対処は、 ``conf.py`` に絶対 URL の ``html_baseurl`` を設定するか、Atom Feed
が不要であれば ``maatlog_generate_feeds = False`` を設定することです。
Feed の設定は :doc:`configuration` の「フィード」節を参照してください

診断コードの読み方
==================

診断メッセージの共通フォーマットと、ビルドを失敗させる診断コードと
ビルドを継続する警告の違いは、 :doc:`builders` の「診断」節にまとまって
います。
上記のセクションで扱わなかった機能領域の診断コードは、次の各節を
参照してください

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 機能領域
     - 参照先
   * - メタデータキー全般
     - :doc:`authoring` の「メタデータスキーマ」節
   * - 著者プロフィール
     - :doc:`configuration` の「著者プロフィール」節にある「診断」小節
   * - ブログのホーム
     - :doc:`configuration` の「ブログのホーム」節にある「診断」小節
   * - レスポンシブ画像
     - :doc:`configuration` の「レスポンシブ画像」節にある「診断」小節
   * - Theme API 全般
     - :doc:`theme-api` の「検証」節
