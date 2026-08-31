:orphan:

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
