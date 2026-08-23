# Git Lanes

IDE を開かずに、ローカル Git の枝の合流を見る専用ビューア。

設計の正: [`docs/DESIGN.md`](docs/DESIGN.md)

## 現状

**Phase 0（設計）まで。** 起動スクリプトとサーバはまだ無い。実装は設計への GO のあと。

## 何を解決するか

Cursor / VS Code の Git Graph と同じく、merge commit はレーンがトランクに戻り、squash は切れて見える。`gitk` は実機で見た目が足りなかった。GitHub の Network は未 push のローカル枝を出さない。

## 起動（未実装）

Phase 1 で `start.bat` を置く。仮 port は **17920**（`127.0.0.1`）。セッション型なので、ウィンドウを閉じるとサーバも止まる。

## 開発

ブランチ:

- `main` — 最終統合
- `PeRo` — 日常レーン（作業先）

テストとランチャは Phase 1 で追加する。未確認のインストール手順はここには書かない。
