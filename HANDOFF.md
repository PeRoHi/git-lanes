# Handoff

最終更新: 2026-08-23

## いま

Phase 1 + 複数リポ発見 + どの PC でも起動するランチャ。日常レーン `PeRo`。

- 起動: `start.bat`（port 17920）。Python / Git / Edge は PATH 固定前提ではない
- リポ一覧: 起動時スキャン + **Find my repos** + Open folder + 任意の **GitHub ログイン**（clone / fetch）
- 設定: `%APPDATA%/git-lanes/`（PC ごと。コードに絶対パスを書かない）
- GitHub: ログインは `gh`。token は gh のストア。このリポの GitHub 掲載（push）はまだ UI に出さない

## 次

1. Git Lanes の GitHub → Sign in でこの PC の `gh` を通す
2. 別 PC で clone して `start.bat`
3. Phase 2 残り: Branches フィルタ、Find
4. ログイン後、必要なら手元で `PeRoHi/git-lanes` を `gh repo create` して push

## 触らない

- Git Graph 拡張のソース
- 書き込み UI（Phase 4）
- ディスク全体スキャン
- life リポへの実装混入
