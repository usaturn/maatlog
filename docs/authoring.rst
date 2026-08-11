投稿の執筆
==========

ドキュメントが MaatLog の投稿になるのは、``maatlog-post`` が真偽値の ``true`` の
ときだけです。それ以外のドキュメントは通常の Sphinx ページのままです。1 つのソース
ファイルにつき投稿は最大 1 つで、本文中で追加の投稿を宣言するディレクティブは
ありません。

タイトル
--------

タイトルの唯一の情報源は Sphinx/Docutils のドキュメントタイトルです。MaatLog は
タイトルを上書きするメタデータキーを提供しません。

reStructuredText
----------------

docinfo がフィールドを収集できるよう、Docutils のフィールドリストをタイトルの前
（または直後）に置きます::

    :maatlog-post: true
    :maatlog-published-at: 2026-08-01T09:00:00+09:00
    :maatlog-expires-at: 2027-01-01T00:00:00+09:00
    :maatlog-slug: sphinx-extension
    :maatlog-tags: sphinx, python
    :maatlog-categories: engineering
    :maatlog-authors: alice
    :maatlog-excerpt: Design notes for a Sphinx extension.
    :maatlog-image: _static/images/sphinx-extension.png
    :maatlog-canonical-url: https://example.com/blog/sphinx-extension/
    :maatlog-external-url: https://publisher.example/articles/42

    Sphinx extension design
    =======================

    Body…

カンマ区切りの複数値フィールドは前後の空白を除去し、空の要素を拒否します。

MyST Markdown
-------------

同じ名前のキーをトップレベルの YAML front matter に記述します。複数値フィールドには
YAML のシーケンスが推奨されますが、カンマ区切りのスカラーも受け付けます::

    ---
    maatlog-post: true
    maatlog-published-at: 2026-08-01T09:00:00+09:00
    maatlog-slug: sphinx-extension
    maatlog-tags: [sphinx, python]
    maatlog-categories: [engineering]
    maatlog-authors: [alice]
    maatlog-excerpt: Design notes for a Sphinx extension.
    maatlog-image: _static/images/sphinx-extension.png
    ---

    # Sphinx extension design

    Body…

MyST の front matter は YAML の暗黙の型付けに従います。MaatLog は YAML の真偽値・
数値・日付オブジェクトを文字列へ戻す変換を行いません。曖昧なタクソノミー ID は
クォートし、日時には時刻とオフセットの両方を含めてください。例::

    maatlog-tags: ["on", "1.2"]
    maatlog-published-at: "2026-07-01T00:00:00Z"

``2026-07-01`` のような日付のみの値は、MaatLog の日時文字列ではありません。

メタデータスキーマ
------------------

.. list-table::
   :header-rows: 1
   :widths: 22 18 12 48

   * - キー
     - 正規化後の型
     - 必須
     - ルール
   * - ``maatlog-post``
     - ``bool``
     - マーカー
     - ``true`` のときだけ投稿になります。``false`` または未指定なら通常のページです。
   * - ``maatlog-published-at``
     - aware な ``datetime`` または ``None``
     - 任意
     - 未指定 → ドラフト。オフセットのない値は ``maatlog_timezone`` を使います。
   * - ``maatlog-expires-at``
     - aware な ``datetime`` または ``None``
     - 任意
     - ``maatlog-published-at`` が必要で、それより厳密に後でなければなりません。
   * - ``maatlog-slug``
     - ``str``
     - 投稿では必須
     - パターンは ``[a-z0-9][a-z0-9._-]*`` で大文字は不可。全投稿で一意。
   * - ``maatlog-tags``
     - ``tuple[str, ...]``
     - 任意
     - タクソノミー ID。重複を除去し、初出順を保ちます。
   * - ``maatlog-categories``
     - ``tuple[str, ...]``
     - 任意
     - ID のルールはタグと同じです。
   * - ``maatlog-authors``
     - ``tuple[str, ...]``
     - 任意
     - ID のルールはタグと同じです。
   * - ``maatlog-excerpt``
     - ``str`` または ``None``
     - 任意\*
     - プレーンテキスト。前後の空白は除去され、空文字列は禁止です。
       \*``maatlog-external-url`` を設定した場合は必須です。
   * - ``maatlog-image``
     - ソース相対の URI または ``None``
     - 任意
     - ローカルファイルのみ。フラグメント・クエリ・絶対 URL は不可。
   * - ``maatlog-canonical-url``
     - 絶対 URL または ``None``
     - 任意
     - ``http`` / ``https`` のみ。userinfo とフラグメントは不可。
   * - ``maatlog-external-url``
     - 絶対 URL または ``None``
     - 任意
     - URL のルールは canonical と同じ。空でない ``maatlog-excerpt`` が必要です。

タクソノミー ID とスラッグは ``[a-z0-9][a-z0-9._-]*`` という同じ文字パターンを
共有します。未知の ``maatlog-*`` キーはエラー（``maatlog.metadata.unknown``）です。
投稿でないドキュメントは、他の ``maatlog-*`` 投稿フィールドを持ってはいけません
（``maatlog.metadata.without-post``）。

公開ステータス
--------------

ビルド時刻はビルドごとに 1 度だけ固定されます（``SOURCE_DATE_EPOCH`` が設定されて
いればその値、なければ UTC のシステムクロック）:

* ``maatlog-published-at`` がない → **draft**
* ``published_at`` がビルド時刻より後 → **scheduled**
* ``expires_at`` があり、ビルド時刻 ≥ 失効時刻 → **expired**
* それ以外 → **published**

アーカイブ、``maatlog:post-list``、サイドバーの件数、新しい／古い投稿へのナビゲー
ション、Atom フィードに現れるのは **published** の投稿だけです。draft・scheduled・
expired の投稿でも、``:maatlog:post:`` のリンクはそのソースページへ解決されます。

ロールと埋め込みリスト
----------------------

相互参照ロール（ドメイン ``maatlog``）:

* ``:maatlog:post:`` — スラッグで指定した投稿
* ``:maatlog:tag:`` — ID で指定したタグアーカイブ
* ``:maatlog:category:`` — ID で指定したカテゴリアーカイブ
* ``:maatlog:author:`` — ID で指定した著者アーカイブ
* ``:maatlog:month:`` — ``YYYY-MM`` で指定した月アーカイブ

例::

    See :maatlog:post:`sphinx-extension` and :maatlog:tag:`Sphinx <sphinx>`.

埋め込みリストディレクティブ
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``.. maatlog:post-list::`` は、**published** な投稿を絞り込んだリストを埋め込みます。
ページネーションは行いません。フィルタはサイト全体の公開順に対して適用され、
``limit`` は先頭 *N* 件を保持します。

.. list-table::
   :header-rows: 1
   :widths: 18 28 54

   * - オプション
     - 型
     - ルール
   * - ``tags``
     - カンマ区切りの ID
     - 同一軸内は OR。列挙したいずれかのタグを持つ投稿が一致します。
   * - ``categories``
     - カンマ区切りの ID
     - カテゴリについて同一軸内は OR。
   * - ``authors``
     - カンマ区切りの ID
     - 著者について同一軸内は OR。
   * - ``month``
     - 単一の ``YYYY-MM``
     - 公開日のローカル月がこの値と一致する投稿。
   * - ``limit``
     - 正の整数
     - 絞り込み後の上限。すべて対象にする場合は省略します。

ID は対応する conf.py の許可リストに存在しなければなりません。未知のオプション、
空のリスト、不正な ID、許可リストに未定義の ID、不正な月、0 以下の limit は、
ディレクティブの位置でビルドエラーになります。軸どうしは AND で結合されます
（設定されている場合、タグ **かつ** カテゴリ **かつ** 著者 **かつ** 月）。

例::

    .. maatlog:post-list::
       :tags: sphinx, python
       :categories: engineering
       :authors: alice
       :month: 2026-08
       :limit: 5

MyST では ``maatlog:post-list`` に標準のフェンス付きディレクティブ形式を使えます。
