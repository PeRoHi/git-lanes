# Handoff

最終更新: 2026-08-23

## いま

Phase 1 + 複数リポ発見 + どの PC でも起動するランチャ。日常レーン `PeRo`。

- 起動: `start.bat`（port 17920）。Python / Git / Edge は PATH 固定前提ではない
- リポ一覧: 起動時スキャン + **Find my repos** + Open folder（親フォルダも可）
- 設定: `%APPDATA%/git-lanes/`（PC ごと。コードに絶対パスを書かない）
- GitHub: `PeRoHi/git-lanes` 予定。`gh` 未ログインなら remote 無しでもローカルは動く

## 次

1. 別 PC（hidek など）で clone して `start.bat` が Python/Git 不足を MessageBox で言えるか
2. Phase 2 残り: Branches フィルタ、Find
3. `gh auth login` のあと private リポを作って push

## 触らない

- Git Graph 拡張のソース
- 書き込み UI（Phase 4）
- ディスク全体スキャン
- life リポへの実装混入
