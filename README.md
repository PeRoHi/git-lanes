# Git Lanes

IDE を開かずに、ローカル Git の枝の合流を見る専用ビューア。

設計の正: [`docs/DESIGN.md`](docs/DESIGN.md)

## 起動（Windows）

```bat
start.bat
```

ウィンドウを閉じるとサーバも止まる（セッション型）。障害で port が残ったときだけ `stop.bat`。

- デバッグ（コンソール表示）: `start-debug.bat`
- URL: `http://127.0.0.1:17920/`（Edge `--app=`）
- デスクトップショートカット: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\create-shortcut.ps1`

初回は **Open folder** で `.git` のあるフォルダを選ぶ。以後は last-opened を開く。

## 操作

| 操作 | 意味 |
|---|---|
| Open folder | ローカルリポを登録して表示 |
| Repo ドロップダウン | 登録済みリポを切替 |
| 行クリック | 件名 / 本文 / 親 / 参照 |
| Refresh / Ctrl+R | 再読込（fetch しない） |
| Ctrl+H | HEAD へスクロール |
| Esc | 詳細を閉じる |
| Quit / ウィンドウ閉じ | サーバ停止 |

閲覧のみ。checkout や merge は出さない。

## 開発

日常レーンは `PeRo`。

```bat
set PYTHONPATH=src
python -m unittest discover -s tests -v
```

サーバだけ（ブラウザは手動）:

```bat
set PYTHONPATH=src
python -m git_lanes
```
