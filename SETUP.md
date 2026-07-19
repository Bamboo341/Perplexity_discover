# SETUP — 初回セットアップと受け入れ試験

Windows 実機での初回セットアップ手順と、受け入れ基準(Digest_spec.md §9)の消化状況・残り項目の実施手順。

## 1. 前提

- Windows 11 / Python 3.11+ / Git for Windows / Claude Code(サブスクリプションでログイン済み)
- Discord サーバの管理権限(webhook 作成のため)

## 2. 初回セットアップ

リポジトリルートの cmd で順に実行する。

```bat
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python -m unittest discover -s tests
```

テストが全件 OK であることを確認したら:

1. **Discord webhook を3本作成**: 各チャンネルの「チャンネルの編集 → 連携サービス → ウェブフック → 新しいウェブフック → URLをコピー」
2. `copy .env.example .env` して3キーに webhook URL を記入(`.env` はコミット禁止。漏洩すると第三者が投稿可能)
3. **git 資格情報の記憶**: 適当な変更なしで一度 `git push` を手動実行し、Git Credential Manager の認証を通す
4. **Claude Code のログイン確認**: `claude` を対話モードで起動し、サブスクリプションでログイン済みであることを確認
5. **課金事故防止(重要)**: `echo %ANTHROPIC_API_KEY%` が「環境変数が定義されていません」相当になることを確認。定義されていると API 従量課金が優先される。不安なら初回に `claude -p "/digest" --output-format json` で課金情報を目視確認

## 3. 受け入れ試験チェックリスト(§9 対応)

### 開発環境で検証済みの項目

| § 9項目 | 状況 |
|---|---|
| 1. 全フィード疎通・3カテゴリの items.json | ✅ 2026-07-12 / 07-15 の2回実施(141件・176件収集) |
| 2. `claude -p "/digest"` でスキーマ準拠 digest.json | ✅ 2回実施。date・件数上限・文字数・出典転記・URL非創作を機械検証 |
| 3. summary が出典と矛盾しない | ⚠ AI 事前チェック済み(上位3件で矛盾なし)。**最終の人手確認は下記** |
| 5. embed 11個以上・6000字超の分割送信 | ✅ ユニットテストで 10+1 分割・summary 無傷の分割を実証 |
| 6. render_md の3出力 | ✅ 実データで digest/2026-07-15.md・README.md・archive コピーを確認 |
| 再配信防止(v1.2 追加) | ✅ 両 sink が前日 date の digest.json を拒否(exit 1)することを実地確認 |

### 実機で実施する項目

**基準3(人手確認)**: `digest/2026-07-15.md`(コミット済みサンプル)の任意の3トピックについて出典リンクを開き、summary の数値・固有名詞・因果関係が記事と矛盾しないことを確認する。

**基準4(Discord 実投稿)**: venv 有効化後に単体実行で確認する。

```bat
python collect.py
call claude -p "/digest" --allowedTools "Read,Write,WebFetch"
python send_discord.py
```

期待: 3チャンネルそれぞれに「📰 日付 ダイジェスト — カテゴリ名」+ ★付きカード(要約・出典リンク・カテゴリ色)が届く。

**基準7(GitHub モバイル表示)**: GitHub モバイルアプリでこのリポジトリの `digest/2026-07-15.md` を開き、見出し・リンクが整形表示されることを確認する。

**基準8(独立性テスト)**:

1. `.env` の `DISCORD_WEBHOOK_AI` の末尾1文字を削って無効化 → `run_digest.bat` 実行 → **期待: Discord 側はエラーになるが GitHub への push は成功**(当日 md がリポジトリに上がる)。bat の終了コードは 1(`echo %errorlevel%`)
2. `.env` を戻し、`git remote set-url origin https://invalid.example/x.git` で push を無効化 → 実行 → **期待: Discord には届き、push 失敗が ERR に記録される**
3. 終わったら remote を元の URL に戻す

**基準9(bat 一気通貫)**: `run_digest.bat` を実行し、`echo %errorlevel%` が 0、`logs\日付.log` に ①→②→③④ の順のログ、Discord と GitHub の両方に当日分が出ることを確認する。

**基準10(タスクスケジューラ)**:

1. タスクスケジューラ →「基本タスクの作成」→ トリガー: 毎日 06:30
2. 操作:「プログラムの開始」→ プログラム: `run_digest.bat` のフルパス、**「開始(オプション)」: リポジトリルートのフルパス**
3. 作成後、プロパティで「タスクを実行するためにスリープを解除する」を有効化(電源設定と整合を取る)
4. 翌朝、Discord 通知と GitHub の当日コミット(`digest: YYYY-MM-DD`)を確認する

## 4. トラブルシューティング

| 症状 | 原因と対処 |
|---|---|
| ②で従量課金が発生した | 環境変数 `ANTHROPIC_API_KEY` を削除する(設定されているとサブスクリプションより優先される) |
| ③④が「digest date ... is not today」で exit 1 | **正常動作**(前日分の再配信防止)。①②からやり直す |
| bat から claude が見つからない | npm グローバルの PATH がタスクスケジューラの実行環境に無い。タスクは対話ログインと同じユーザーで実行する |
| push が失敗する | 資格情報切れ。手動で `git push` して Credential Manager に再記憶させる |
| ログや Discord が文字化けする | bat が `PYTHONUTF8=1` を設定済み。独自にスクリプトを直接実行する場合も UTF-8 前提(各スクリプトは encoding="utf-8" 明示) |
| HTTP 429 が頻発する | フィード・カテゴリを増やした場合は send_discord.py の `MESSAGE_INTERVAL_SECONDS` を延ばす |
| フィードが 0 件になる | 週末・祝日は NHK/ITmedia の記事が少ないのは正常。継続するなら feeds.yaml のフィードを差し替える(Digest_spec.md §3) |
