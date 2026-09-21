======
用語集
======

.. glossary::


    MaatLog
         ブログを作成する Sphinx 拡張

    Pull Request
        GitHub 上でブランチの変更をレビューし取り込む単位である。
        本リポジトリでは ``origin/main`` への取り込みを :term:`merge commit` で行う

    merge commit
        2 つの履歴をマージコミットで結合する取り込み方である。
        squash や rebase merge とは異なり、 :term:`Pull Request` 側の commit が祖先として残る

    worktree
        同一 Git リポジトリを別ディレクトリへ展開した作業ツリーである。
        メインの作業ツリーを動かさずにブランチや detached HEAD を検証できる。
        ``$pr-review`` は :term:`Pull Request` ごとに使い捨て :term:`worktree` を作る

    Agent Skills
        AI エージェントに特定領域の手順と判断基準を与える、指示書の配布単位である。
        Claude Code ではプラグインとして導入し、対象の作業に入った時点で読み込まれる

    Playwright
        ブラウザを自動操作するフレームワークである。
        Chromium などを headless で起動し、生成したサイトのレンダリング結果を検証できる

    Core Web Vitals
        ページの体験品質を表す Google の指標群である。
        表示速度の LCP 、応答性の INP 、レイアウト安定性の CLS の 3 つで構成される

    WCAG
    Web Content Accessibility Guidelines
        W3C が策定した Web アクセシビリティのガイドラインである。
        達成基準は適合レベル A, AA, AAA に分類される

    Lighthouse
        Web ページの品質を監査する Google のツールである。
        性能・アクセシビリティ・SEO などを計測し、改善余地を報告する

    Chrome DevTools MCP
        Chrome DevTools の計測機能を MCP 経由でエージェントへ提供するサーバである。
        :term:`Lighthouse` の実行や性能トレースの取得を担うが、本リポジトリでは導入していない

    Pillow
        Python の画像処理ライブラリである。
        :term:`MaatLog` のレスポンシブ画像機能は ``images`` extra で導入する
        Pillow をバックエンドとして使い、JPEG / PNG / WebP の
        デコード・リサイズ・エンコードを行う

    EXIF
    Exchangeable Image File Format
        デジタルカメラなどが画像ファイルへ埋め込むメタデータの規格である。
        撮影日時や機種、位置情報、画像の表示方向を示す orientation が含まれる。
        :term:`MaatLog` は生成するバリアントに orientation を適用したうえで、
        EXIF そのものは出力へ残さない

    ICC
    ICC プロファイル
        画像の色を機器間で一貫して再現するための色情報である。
        :term:`MaatLog` はバリアントへ ICC プロファイルを保持し、
        パレット形式の画像は sRGB プロファイルへ変換する

    投稿
        ``maatlog-post: true`` を指定した Sphinx ドキュメントである。
        reStructuredText ではタイトル前の docinfo フィールドリスト、
        MyST Markdown では YAML front matter に記述する。
        1 つのソースファイルにつき投稿は最大 1 つで、それ以外のドキュメントは
        通常の Sphinx ページのままである
