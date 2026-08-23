# Git Lanes — 設計書（v0.1）

最終更新: 2026-08-23  
ステータス: **Phase 1 MVP 実装済み**  
閲覧者: **自分だけ**（他人配布なし）

---

## 0. 背景と動機

日常レーン（`PeRo`）への取り込みは **merge commit** を原則にしている。squash すると第2親が無いので、枝がトランクに戻らず切れて見える。その確認に使っていたのは Cursor / VS Code の **Git Graph** 拡張（`mhutchie.git-graph`）だった。

IDE を開かずに同じものを見たくて既存手段を当たった。

| 手段 | 結果 |
|---|---|
| Git Graph 拡張 | 欲しい見た目。ただし Cursor / VS Code が必要 |
| `gitk --all` | IDE 不要でグラフは出る。2026-08-23 に実機確認し **微妙**（古い Tk 見た目・情報密度が低い） |
| GitHub Network | ブラウザだけで見られるが、**未 push のローカル枝が無い** |
| Dev Remote Hub | Agent / PR の状況板。コミットグラフではない |
| GitKraken / Fork / SourceTree | この PC に入っていない。高機能 GUI を新規導入するほどではない |

このリポジトリは、**IDE を開かずに Git Graph 相当のレーン図を見る**専用ビューアにする。

関連（個人メモ。製品 Git にはコピーしない）:

| もの | 役割 |
|---|---|
| `life/universal-development-prompts-v1.md` §6・§14・§18 | セッション型起動・merge commit 方針 |
| Cursor / VS Code の Git Graph | 見た目の参照。**ソースはコピーしない**（GPL-3.0） |
| `life/projects.md` | 個人プロジェクト一覧のポインタ |

---

## 0.1 決定済み要件（2026-08-23）

会話と実機確認からここまでを正とする。実装前に覆すならこの表を先に直す。

| # | 項目 | 決定 |
|---|---|---|
| 1 | 置き場 | 専用リポ `git-lanes`（life には実装を置かない） |
| 2 | 名前 | **Git Lanes**（リポ名 `git-lanes`） |
| 3 | 寿命 | **セッション型**。起動ショートカットのみ。ウィンドウ閉じ / UI「終了」でサーバ停止 |
| 4 | UI | ローカル Web + Edge/Chrome `--app=`。gitk / Tk は使わない |
| 5 | 見た目の目標 | Git Graph の **左レーン + 行ごとの Description / Date / Author / Commit**。gitk の分割ペインには寄せない |
| 6 | データ源 | **レーン図はローカル `.git`**（未 push の枝を含む）。GitHub Network は使わない。任意で **GitHub CLI (`gh`) ログイン**し、自分の GitHub リポの一覧・clone・`fetch` だけ足す |
| 7 | 書き込み | グラフ操作は **閲覧のみ**（checkout / merge / rebase / push は出さない）。GitHub からの **clone / fetch** はログイン後に限って可 |
| 8 | 対象機 | Windows。当面 localhost のみ（スマホ / Tailscale は非目標） |
| 9 | 閲覧者 | 自分だけ |

---

## 1. プロダクト概要

| 項目 | 内容 |
|---|---|
| 名称 | **Git Lanes** |
| 一言 | IDE を開かずに、ローカル Git の枝の合流が見える専用ウィンドウ |
| 対象機 | Windows PC |
| 非目標 | Git 操作 GUI、GitKraken 代替、クラウド公開、スマホ常駐、Git Graph 拡張のフォーク |

### 一言フロー

```
start.bat
  → この PC の Python 3.10+ / Git / Edge を探す
  → 固定 port の health OK
  → 既知の作業フォルダをスキャンして自分のリポを登録
  → Edge --app= 専用ウィンドウ
  → 最後に開いたリポ（この PC に無い path は飛ばす）
  → レーン図（全枝）
  → コミットをクリックすると詳細
  → ウィンドウを閉じる / 「終了」→ サーバ停止
```

---

## 2. 用語

| 用語 | 意味 |
|---|---|
| **レーン** | グラフ左の縦の色線。1本が「いま並んでいる親の列」 |
| **頂点** | コミット（または Uncommitted）の丸 |
| **合流** | 第2親以上を持つ merge commit。線がトランクに戻って見える |
| **切断** | squash 取り込みのように第2親が無く、枝がトランクに戻らない見え方 |
| **参照** | branch / tag / HEAD / stash のラベル |
| **対象リポ** | いまグラフを描いている作業ツリー（`.git` があるフォルダ） |

---

## 3. UX 要件

### 3.1 画面（MVP）

Git Graph と同じ情報密度を目指す。上から下へ新しいコミット。

```
┌──────────────────────────────────────────────────────────────────┐
│ Git Lanes  [リポ v]  [Find my repos] [Open folder]  [更新] [終了] │
├────┬──────────────────────────────────┬──────────┬────────┬──────┤
│Graph│ Description                      │ Date     │ Author │Commit│
├────┼──────────────────────────────────┼──────────┼────────┼──────┤
│ *  │ (HEAD -> PeRo) merge feat into.. │ 2 hours  │ pero   │ a1b2 │
│ |\ │                                  │          │        │      │
│ | *│ (feat/cursor/foo) add viewer     │ 3 hours  │ cursor │ c3d4 │
│ |/ │                                  │          │        │      │
│ *  │ docs: design v0.1                │ yesterday│ pero   │ e5f6 │
└────┴──────────────────────────────────┴──────────┴────────┴──────┘
│ 詳細: 件名 / 本文 / 親ハッシュ / 参照一覧                         │
└──────────────────────────────────────────────────────────────────┘
```

必須:

- 左に **色付きレーン**。merge は線が合流し、squash は合流しない
- 各行に **参照ラベル**（`HEAD`、ローカル枝、remote 枝、tag）
- Description / Date / Author / 短縮ハッシュ
- 未コミット変更があるときは最上段に **Uncommitted** 行
- 初期は **全枝**（`git log --all` 相当）
- コミットクリックで下（または右）に詳細
- リポ切り替え（ドロップダウン）
- **Find my repos**（この PC の既知作業フォルダをスキャン）
- **Open folder**（1リポ、または親フォルダ配下の Git をまとめて登録）
- **GitHub**（任意。`gh` でログイン → リモート一覧、未 clone をこの PC に足す、今のリポを fetch）

### 3.2 操作（MVP）

| 操作 | 動作 |
|---|---|
| リポ選択 | 登録済み一覧から切替。新規はフォルダ選択 |
| Branches | All / 個別選択（Phase 1 は All だけでも可。フィルタは Phase 2） |
| 更新 | 同じリポを再読込（`git fetch` はしない） |
| コミットクリック | 詳細パネル |
| Ctrl+H | HEAD の行へスクロール |
| Ctrl+R | 更新 |
| Esc / 終了 | 詳細を閉じる / アプリ終了 |
| ウィンドウ閉じ | サーバ停止 |

### 3.3 出さないもの（MVP）

右クリックからの checkout / merge / rebase / cherry-pick / push / タグ作成は **出さない**。見る専用。誤操作で日常レーンを壊さないため。

書き込み操作が欲しくなったら Phase 4 以降で、そのときも破壊的操作は確認ダイアログ必須。

---

## 4. 非目標（混同防止）

| やらない | 理由 |
|---|---|
| `mhutchie.git-graph` のソース流用 | GPL-3.0。見た目の参照だけ |
| gitk のスキン | 実機で却下済み |
| GitHub Network のラッパ | ローカル未 push が見えない |
| Dev Remote Hub へのグラフ埋め込み | 寿命が違う（Hub は常駐、これはセッション） |
| ディスク全体の自動スキャン | 誤って巨大フォルダを食う。登録リスト + フォルダ選択 |
| スマホ / `0.0.0.0` bind | セッション型は localhost |

---

## 5. データとレーン計算

### 5.1 読む Git 情報

サーバは対象リポで **引数配列の git** だけを呼ぶ（シェル文字列連結禁止）。

MVP で使うコマンドの種類:

- `git rev-parse --is-inside-work-tree` / `--show-toplevel`
- `git status --porcelain=v1 -b`（Uncommitted と現在枝）
- `git log --all --date-order`（または `--topo-order`。既定は date-order で Git Graph に寄せる）
- pretty: ハッシュ、親、author、author time、subject、body
- `git for-each-ref`（heads / remotes / tags）
- `git stash list`（任意。Phase 1 では無くてもよい）

初期ロード件数: **300**。末尾まで来たら追加 300（Git Graph の Initial Load / Load More と同型）。

### 5.2 レーン割り当て（概念）

コミットを新しい順に並べ、各コミットに整数レーンを振る。

1. まだレーンが無いコミットは、空いている最小レーンを取る
2. 第1親は同じレーンを継承する（直線の履歴）
3. 第2親以降は別レーンから合流する（merge の斜線）
4. 子が居なくなったレーンは解放する

受け入れ条件（テストで固定する）:

| 履歴 | 見え方 |
|---|---|
| 直線（fast-forward 相当） | レーン 1 本 |
| `git merge --no-ff` | 枝レーンがトランクに **戻って合流**する |
| squash 取り込み | 枝レーンはトランクに戻らず **切れて見える** |

この 3 つが「日常レーンは merge commit」を目で確認する理由そのもの。

### 5.3 API（案）

固定 port **17920**。bind は `127.0.0.1`。

| 経路 | 役割 |
|---|---|
| `GET /api/health` | ready。起動スクリプトがブラウザを開く前に待つ |
| `GET /api/repos` | 登録リポ一覧 + last-opened |
| `POST /api/repos/open` | フォルダを登録して対象にする |
| `GET /api/graph?repo_id=&offset=&limit=` | レーン付きコミット配列 |
| `GET /api/commit?repo_id=&hash=` | 詳細（件名、本文、親、参照） |
| `POST /api/shutdown` | サーバ停止。ウィンドウ閉じと同じロック |

書き込み系 git は置かない。

グラフ JSON のイメージ:

```json
{
  "repo": {
    "id": "life",
    "path": "C:/Users/t230g/Desktop/個人用/program file/life",
    "head": "PeRo"
  },
  "commits": [
    {
      "hash": "abc...",
      "parents": ["def...", "ghi..."],
      "subject": "merge feat/cursor/foo into PeRo",
      "author": "pero",
      "author_at": 1755910000,
      "refs": ["HEAD", "PeRo"],
      "lane": 0,
      "edges": [
        {"from_lane": 0, "to_lane": 0, "kind": "parent1"},
        {"from_lane": 1, "to_lane": 0, "kind": "merge"}
      ]
    }
  ],
  "has_more": true
}
```

---

## 6. 設定と状態

コードにマシン固有の絶対パスを埋め込まない。t230g と hidek で Desktop の形が違っても、ホーム相対の候補と「このクローンの親フォルダ」だけを見る。

| 置き場 | 内容 |
|---|---|
| `%APPDATA%/git-lanes/config.json` | 登録リポ一覧（表示名 + path）と `scan_roots` |
| `%APPDATA%/git-lanes/state.json` | last-opened、ウィンドウサイズ（任意） |
| リポ内 `config.example.json` | キーの見本だけ。実 path は書かない |

設定は **PC ごと**（APPDATA）。他の PC の path を共有しない。この PC に存在しない登録はドロップダウンに出さない。

### 6.1 リポの見つけ方

ディスク全体は走査しない。

起動時と **Find my repos** は、存在する候補だけを深さ 4 まで見る。

- `%USERPROFILE%\Desktop\program`
- `%USERPROFILE%\Desktop\個人用\program file`
- `%USERPROFILE%\Desktop\life`
- `%USERPROFILE%\Documents\HDLSim`
- 上記の OneDrive Desktop 版（フォルダがあるときだけ）
- この `git-lanes` クローン自身と、その親フォルダ
- ユーザーが Open folder した親フォルダ（`scan_roots`）

`.git` のある作業ツリーだけ登録する。`node_modules` / `.venv` などには入らない。上限は訪問 1200 ディレクトリ・リポ 120・8 秒。

**Open folder** は次のどちらか。

- そのフォルダが Git 作業ツリー → 1件登録して開く
- そうでない → 配下をスキャンして見つかったリポを全部登録し、親を `scan_roots` に残す

### 6.2 どの PC でも起動する

依存は **Python 3.10+（stdlib のみ）・Git・Edge または Chrome**。venv は不要。GitHub ログインは **任意**（レーン図だけ見るなら不要）。

GitHub を使うときは同じ PC に **GitHub CLI (`gh`)** が入っていること。トークンは `gh` の資格情報ストアに置き、`config.json` には書かない。

`start.bat` は `scripts\find-python.cmd` で `pythonw.exe` を探す。見つからなければ MessageBox。

1. リポの `.venv\Scripts\pythonw.exe`（任意）
2. `py -3` が返す interpreter と同じフォルダの `pythonw.exe`
3. `%LocalAppData%\Programs\Python\Python3*\pythonw.exe`
4. pyenv-win の versions
5. PATH の `pythonw` / `python`（WindowsApps のストアスタブは使わない）

`py -3w` は環境によってはスクリプトを起動しないので使わない。

Git が PATH に無くても `Program Files\Git\cmd\git.exe` などを探す。Edge も Program Files / LOCALAPPDATA / PATH を見る。デスクトップショートカットが無ければ初回起動で作る。

新しい PC:

1. Python 3.10+ と Git for Windows を入れる（`py` ランチャーか PATH）
2. このリポを好きな場所に clone / コピーする（パスはマシンごとに違ってよい）
3. `start.bat` を実行する

他の PC にまだ clone が無い GitHub リポを足すなら、Git Lanes の **GitHub → Sign in**（`gh auth login --web`）。

### 6.3 初回

登録が空 → 既知ルートをスキャン → まだ空なら Find my repos / Open folder / GitHub sign in。

### 6.4 GitHub ログイン（任意）

グラフの正は今も **ローカル `.git`**。GitHub.com の Network 図は出さない（未 push の枝が無い）。

ログインが要るのは次だけ。

- GitHub 上の自分のリポ一覧
- この PC に無いリポを `gh repo clone` して登録
- 今開いているリポの `git fetch --all`（private の origin を含む）

流れ: UI の Sign in → `gh` がワンタイムコードを出し、Git Lanes に大きく表示 → システムのブラウザで `github.com/login/device` を開く。コンソール窓は出さない。Sign out は `gh auth logout`。

このツール自体を `PeRoHi/git-lanes` に載せる **push は UI に出さない**（Phase 4）。ログイン後に手元で `gh repo create` する。

---

## 7. 技術方針

### 7.1 採用

**ローカル Web（Python + ブラウザ `--app=`）** — Image Triage と同型。

- グラフ描画はブラウザ（Canvas または SVG）。Tk / Electron / 拡張ホストは使わない
- Git 操作は Python から `subprocess`（`shell=False`）
- UI は静的 HTML/CSS/JS。ビルド必須のフロントは MVP では避ける

### 7.2 起動規約（Windows）

- `.bat` / `.ps1` は ASCII のみ。日本語リテラル禁止。ユーザー向け説明は `docs/` と README
- 親 `start.bat` は子起動後すぐ exit
- Python は `scripts\find-python.cmd` が `pythonw.exe` を探す。PATH に `pythonw` が無くてもよい。`py -3w` は使わない
- `pythonw` なら logs / MessageBox / `start-debug.bat` の 3 点セット
- 固定 port **17920** の `/api/health` 成功まで待ってから `--app=`
- 既存 LISTENING なら先に回収し、空いてから起動
- ログは `logs/`（gitignore）

### 7.3 起動寿命（セッション型）

ユーザー導線は **`start.bat` のみ**。

- ウィンドウ閉じ / UI「終了」→ サーバ停止
- `stop.bat` は障害時の port 回収だけ（本線にしない）
- ランチャーは専用 `user-data-dir` 付き Edge/Chrome の **プロセス終了を待つ** → port 回収
- あわせて `pagehide` / 「終了」から `/api/shutdown`

### 7.4 キャッシュ

静的 UI は `Cache-Control: no-store`。HTML URL に bust を付けてよい。`--app=` の専用プロファイル Cache は起動時に捨てる（古い JS が残ってレーンが更新されないのを防ぐ）。

---

## 8. セキュリティ

- bind は `127.0.0.1` のみ
- 対象 path は登録リストか、ユーザーが選んだフォルダか、§6.1 の既知ルート。ディスク全体や任意の親辿りはしない
- git 引数は配列。ユーザー入力をコマンド列に埋め込まない
- 秘密情報は git-lanes のファイルに置かない。GitHub token は **`gh` のストアだけ**。API 応答にも載せない
- コミット本文の URL は `http:` / `https:` だけリンク化

---

## 9. テスト

フィクスチャは一時ディレクトリに最小 Git を作る。実製品リポは CI に使わない。

| ケース | 期待 |
|---|---|
| 直線 3 コミット | レーン 1、edge は parent1 のみ |
| feature を `--no-ff` で merge | merge 行に親 2 つ。枝レーンがトランクへ合流 |
| feature を squash | トランク側に第2親が無い。枝は切れて見える |
| 未コミット 1 ファイル | 最上段 Uncommitted |
| `.git` が無いフォルダ | グラフを描かずエラー |
| 既知ルート配下の Git | スキャンで登録される。`node_modules` 配下は対象外 |
| この PC に無い登録 path | ドロップダウンに出さず、last-opened も飛ばす |
| GitHub 未ログイン | `/api/github/status` は `logged_in: false`。clone はしない |

Phase 1 の受け入れは「テスト緑」+ 実機で `life` か本リポの `PeRo` を目視。

---

## 10. マイルストーン

### Phase 0 — 設計（本ファイル）

- [x] 動機（gitk 却下、IDE 無し、ローカル枝）
- [x] セッション型 + port **17920**
- [x] 閲覧のみ、レーン合流の受け入れ条件
- [x] この設計への人間 GO（2026-08-23「どんどん進めちゃって」）

### Phase 1 — MVP

- [x] `start.bat` / `start-debug.bat` / 障害用 `stop.bat`
- [x] health → `--app=` → 閉じたら停止
- [x] 1 リポのレーン図（All branches、初期 300）
- [x] merge / squash / 直線のユニットテスト
- [x] コミット詳細（件名・本文・親・参照）
- [x] フォルダを開いて対象リポにする

### Phase 2 — 使い勝手

- [x] 登録リポの切替（last-opened）
- [x] 既知作業フォルダのスキャンと、どの PC でも起動できるランチャ
- [x] GitHub CLI ログイン（一覧 / clone / fetch）。push は出さない
- [ ] Branches フィルタ
- [x] Load More / 末尾自動ロード
- [ ] Find（件名 / ハッシュ / 参照）
- [x] HEAD へスクロール（Ctrl+H）

### Phase 3 — 詳細の厚み（任意）

- [ ] 変更ファイル一覧（diff 本体は OS の既存ツールか後続）
- [ ] 2 コミット比較
- [ ] stash 行

### Phase 4 — 書き込み（明示 GO が無い限りやらない）

- [ ] checkout / create branch 等。破壊的操作は確認必須

---

## 11. ブランチ運用

| 層 | 枝 | 役割 |
|---|---|---|
| 最終統合 | `main` | 安定の正。バンバン上げない |
| 日常レーン | `PeRo` | 設計・実装の作業先 |
| 工場・並列 | `<種別>/<主体>/<対象>` | このチャット直列では切らない |

日常レーンへの取り込みは merge commit（`--no-ff`）。本ツールでその見え方を確認する。

---

## 12. 決定ジャーナル

| 日付 | 決定 | 理由 | 可逆? |
|---|---|---|---|
| 2026-08-23 | gitk を本線にしない | 実機で微妙 | 可逆（ショートカットを足すだけ） |
| 2026-08-23 | 専用リポ `git-lanes` | life に実装を混ぜない | 可逆 |
| 2026-08-23 | セッション型ローカル Web | Image Triage と同型。IDE 不要 | 可逆 |
| 2026-08-23 | MVP は閲覧のみ | 見るためだけに git を壊さない | 可逆（Phase 4） |
| 2026-08-23 | Git Graph ソースは使わない | GPL-3.0。レーン計算は自前 | 固定 |
| 2026-08-23 | GitHub リモートは `PeRoHi/git-lanes` 予定 | 他の個人ツールと同じ。この PC は `gh` 未ログインのため作成は後回し | 可逆 |
| 2026-08-23 | 既知ルートのスキャン + PATH 非依存の起動 | 自分の他リポを足す。t230g / hidek で Desktop 形が違ってもコードに絶対パスを書かない | 可逆 |
| 2026-08-23 | GitHub は `gh` ログイン任意。グラフはローカルのまま | リモートの自分のリポをこの PC に足す／fetch するため。token は gh 任せ。push UI は Phase 4 | 可逆 |
