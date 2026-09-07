# Agent notes

実装・改修・レビューの前に [`docs/DESIGN.md`](docs/DESIGN.md) を読む。設計とコードが矛盾したら、独断で片方を直さず確認する。

## このリポ

- GitHub は public（`PeRoHi/git-lanes`）。用途は自分のローカルセッション
- **セッション型**ローカル Web（ウィンドウ閉じ = サーバ停止）
- MVP は Git の **閲覧のみ**（clone / fetch は GitHub ログイン後の任意）
- `life/universal-development-prompts-v1.md` をこの Git にコピーしない

## やってよい

- 設計に書いてある Phase の実装
- 進捗ごとのローカル commit（秘密情報なし）
- テスト用の一時 Git フィクスチャ

## やらない

- Git Graph 拡張（`mhutchie.git-graph`）のソース流用
- checkout / merge / rebase などの書き込み UI（Phase 4 と明示 GO まで）
- `.bat` / `.ps1` の日本語リテラル
- ディスク全体スキャン（既知の作業フォルダとユーザーが選んだ親だけ）
- `0.0.0.0` bind（localhost のみ）

## ブランチ

日常レーンは `PeRo`。席あり直列はここに直接 commit。工場用の短期枝を量産しない。
