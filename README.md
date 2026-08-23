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
- デスクトップショートカット: 初回起動で無ければ作る。手動なら `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\create-shortcut.ps1`

`start.bat` はマシンの PATH に `pythonw` が無くても、`py -3`・python.org のインストール・pyenv-win から `pythonw.exe` を探す。Git が PATH に無くても Git for Windows の定位置を探す。

## 新しい PC

コードにユーザー名や Desktop の絶対パスは入っていない。clone する場所はマシンごとに違ってよい。

1. Python 3.10 以上（インストール時に `py` ランチャーか PATH）
2. Git for Windows
3. Edge または Chrome（Windows 11 なら Edge あり）
4. このリポを置く（例: `Desktop\program\git-lanes` でも `Desktop\個人用\program file\git-lanes` でも可）
5. `start.bat`

GitHub ログインは **レーン図を見るだけなら不要**。GitHub 上のリポをこの PC に clone したり、private の origin を fetch したりするときだけ、画面の **GitHub → Sign in**（GitHub CLI `gh` が必要）。トークンは `gh` のストアに残り、Git Lanes を閉じても Sign out するまで入ったまま。git-lanes のファイルには token を書かない。一覧は行全体をクリックして開く／足す。

## 操作

| 操作 | 意味 |
|---|---|
| Find my repos | 既知の作業フォルダを再スキャンして、まだ無いリポを足す |
| Open folder | 1リポを開く。Git でない親フォルダなら配下のリポをまとめて登録 |
| GitHub | `gh` でログイン。GitHub 上の自分のリポを一覧し、未 clone なら Add、今のリポは Fetch |
| Repo ドロップダウン | この PC に実在する登録済みリポを切替 |
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
