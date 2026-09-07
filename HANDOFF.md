# Handoff

最終更新: 2026-09-07

## いま

Phase 1 + 複数リポ発見 + どの PC でも起動するランチャ。日常レーン `PeRo`。

- 起動: `start.bat`（port 17920）。Python / Git / Edge は PATH 固定前提ではない
- リポ一覧: 起動時スキャン + **Find my repos** + Open folder + 任意の **GitHub ログイン**（clone / fetch）
- 設定: `%APPDATA%/git-lanes/`（PC ごと。コードに絶対パスを書かない）
- GitHub: ログインは `gh`。未導入ならインストールページ。token は gh のストア。origin は `PeRoHi/git-lanes`（public）。起動でリポ直下に `Git Lanes.lnk`（`Git Lanes.ico`）

## 次

1. 別 PC で clone して `start.bat`
2. Phase 3: 2 コミット比較

## 触らない

- Git Graph 拡張のソース
- 書き込み UI（Phase 4）
- ディスク全体スキャン
- life リポへの実装混入
