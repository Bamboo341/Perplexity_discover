# discover-digest 仕様書

Perplexity Discover の個人版 — RSS × Claude Code × Discord webhook + GitHub による毎朝のニュースダイジェスト自動配信・蓄積システム。

- v1.2(2026-07-12): 設計確定を反映 — feeds.yaml 全カテゴリの確定値と Phase 0 疎通確認結果(§3)、重複除去・ソートの調整(§4)、date の単一情報源化(§5・§7)、前日分再配信の防止(§6・§7・§8)、README 全文生成化(§7)、bat 骨子修正: call claude / ロケール非依存日付 / UTF-8 / コミットガード(§8)、.env.example 追加(§2)
- v1.1(2026-07-12): 出力先に GitHub 兼用を追加(§7)。アーカイブ責務を send_discord.py から render_md.py へ移動(§6)
- 想定環境: Windows 11 / Python 3.11+ / Claude Code(サブスクリプションでログイン済み)/ Git for Windows
- 運用コスト: RSS(無料)+ Claude Code(プラン枠内)+ Discord(無料)+ GitHub 非公開リポ(無料)= **API従量課金ゼロ**

---

## 0. 完成像

毎朝 06:30、次の2系統に自動出力される。

- **Discord(フロー)**: 私設サーバのカテゴリ別チャンネルに、重要トピックがカード(embed)形式で投稿される。スマホの通知を開くだけで当日分を読める
- **GitHub(ストック)**: 非公開リポジトリに `digest/YYYY-MM-DD.md` が日次コミットされる。GitHubモバイルアプリ/Webでいつでも遡って閲覧・検索できる恒久アーカイブ

## 1. アーキテクチャ

```
[タスクスケジューラ 毎朝 06:30]
        │
   run_digest.bat
        │
 ① python collect.py       RSS巡回・正規化 → data/items.json   (決定的 / LLM不使用)
 ② claude -p "/digest"     読解・選定・要約 → data/digest.json  (判断 = Claude)
        │
        ├─ ③ python send_discord.py   embed組立・送信 → Discord   (sink A)
        └─ ④ python render_md.py + git push → GitHub非公開リポ    (sink B)
```

**分業原則**: 決定的な処理(収集・整形・送信・描画)は Python、判断が必要な処理(クラスタリング・選定・要約)のみ Claude が担う。

**sink独立原則**: ③と④はどちらも `data/digest.json` を読むだけの独立した出力先(sink)であり、片方の失敗がもう片方の実行を止めてはならない。①②の失敗時のみ全体を中止する(生成物が存在しないため)。

## 2. リポジトリ構成

このプロジェクトフォルダ自体を GitHub の**非公開リポジトリ**にする(origin = 非公開リポ)。

```
discover-digest/
├── CLAUDE.md                  # プロジェクト文脈(Claude Code用)
├── Digest_spec.md             # 本書
├── README.md                  # 最新ダイジェストへのリンク(render_md.pyが自動更新)
├── feeds.yaml                 # カテゴリ・RSS定義
├── collect.py
├── send_discord.py
├── render_md.py
├── run_digest.bat
├── requirements.txt           # feedparser, pyyaml, requests, python-dotenv
├── .env                       # webhook URL(コミット禁止)
├── .env.example               # .env の雛形(キー名のみ・コミット対象)
├── .gitignore
├── .claude/
│   └── commands/
│       └── digest.md          # /digest カスタムコマンド本体
├── digest/                    # 日次md(コミット対象 = ストック本体)
│   └── 2026-07-13.md
├── data/
│   ├── items.json             # ①の出力(transient・コミット対象外)
│   ├── digest.json            # ②の出力(transient・コミット対象外)
│   └── archive/               # 日次JSON退避(コミット対象 = /weekly等の将来入力)
└── logs/                      # コミット対象外
```

- .gitignore: `.env` / `logs/` / `venv/` / `data/items.json` / `data/digest.json`(transient のみ除外。`digest/` と `data/archive/` はコミットする)
- CLAUDE.md には最低限「プロジェクト目的 / 分業原則・sink独立原則(§1)/ Pythonは型ヒント必須・標準ライブラリ+requirements.txt記載のみ・ファイルI/Oは `encoding="utf-8"` 明示(Windows の cp932 既定対策)/ 各スクリプトの単体実行方法」を記載する

## 3. feeds.yaml

### スキーマと確定値(v1.2)

```yaml
categories:
  - id: ai_tech
    name: "AI・テック"
    webhook_env: DISCORD_WEBHOOK_AI    # .env 内のキー名
    color: 0x5865F2                    # embed の色
    max_topics: 4                      # ダイジェスト採用上限
    feeds:
      - { name: "Hacker News", url: "https://news.ycombinator.com/rss" }
      - { name: "Google News AI", url: "https://news.google.com/rss/search?q=AI&hl=ja&gl=JP&ceid=JP:ja" }
      - { name: "ITmedia AI+", url: "https://rss.itmedia.co.jp/rss/2.0/aiplus.xml" }
  - id: markets_macro
    name: "マーケット・経済"
    webhook_env: DISCORD_WEBHOOK_MARKETS
    color: 0x57F287
    max_topics: 3
    feeds:
      - { name: "Google News ビジネス", url: "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=ja&gl=JP&ceid=JP:ja" }
      - { name: "NHK 経済", url: "https://www3.nhk.or.jp/rss/news/cat5.xml" }
  - id: geopolitics
    name: "国際・地政学"
    webhook_env: DISCORD_WEBHOOK_GEO
    color: 0xED4245
    max_topics: 3
    feeds:
      - { name: "Google News 国際", url: "https://news.google.com/rss/headlines/section/topic/WORLD?hl=ja&gl=JP&ceid=JP:ja" }
      - { name: "NHK 国際", url: "https://www3.nhk.or.jp/rss/news/cat6.xml" }
```

max_topics は 4+3+3 = 全体10件(§5「全体で10前後」に整合)。

### 初期フィード案(実装フェーズの最初に疎通確認タスクを置くこと)

| カテゴリ | フィード | URL |
|---|---|---|
| ai_tech | Hacker News frontpage | https://news.ycombinator.com/rss |
| ai_tech | Google News「AI」検索(日本語) | https://news.google.com/rss/search?q=AI&hl=ja&gl=JP&ceid=JP:ja |
| ai_tech | ITmedia AI+ | https://rss.itmedia.co.jp/rss/2.0/aiplus.xml |
| markets_macro | Google News ビジネス | https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=ja&gl=JP&ceid=JP:ja |
| markets_macro | NHK 経済 | https://www3.nhk.or.jp/rss/news/cat5.xml |
| geopolitics | Google News 国際 | https://news.google.com/rss/headlines/section/topic/WORLD?hl=ja&gl=JP&ceid=JP:ja |
| geopolitics | NHK 国際 | https://www3.nhk.or.jp/rss/news/cat6.xml |

- 疎通不能・低品質なフィードは差し替える。公式RSSを廃止済みの媒体(Reuters等)は Google News の検索RSS(`rss/search?q=媒体名+キーワード`)で代替する。

### 疎通確認結果(Phase 0・2026-07-12 実施)

全7フィードが HTTP 200 で疎通し、全エントリが published を保持。上記の表をそのまま初期フィードとして採用する。品質注記:

- **Hacker News**: summary が「Comments」のみで実質空。タイトル+deep-dive(WebFetch)で補完する前提で採用
- **Google News 系**: 記事URLが `news.google.com/rss/articles/…` のリダイレクトURLのため、直接フィードとのURL重複除去は効かない(/digest のクラスタリングで吸収する)。summary はタイトル+関連見出しの連結で情報量が薄い
- summary に HTMLエンティティ(`&nbsp;` 等)が混入する → collect.py の正規化でアンエスケープする(§4)
- **NHK・ITmedia**: 週末は直近24時間の記事が0〜1件になる日があるが、フィード自体は健全(平日は十分な件数)

## 4. collect.py 仕様

- 入力: feeds.yaml
- 処理:
  1. 各フィードを feedparser で取得(タイムアウト10秒。失敗フィードは WARN ログのみ出して続行)
  2. `published_parsed` が直近24時間以内のエントリを採用(日時欠損のエントリは採用)
  3. 正規化: HTMLタグ除去・HTMLエンティティのアンエスケープ(`&nbsp;` 等)、summary は先頭400字で切り詰め
  4. 重複除去: URL からトラッキング系クエリパラメータ(`utm_*`・`fbclid`・`gclid` 等)のみを除いた文字列の SHA-1 **先頭12文字**を `id` とし、同一 id は先着優先。タイトル完全一致も除去(クエリで記事を識別するサイトを誤同一視しないため、クエリ全除去はしない)
  5. カテゴリごとに新しい順で**最大60件**に制限(Claude への入力トークン制御)。日時欠損のエントリは末尾に置く
- 出力: `data/items.json`

```json
{
  "generated_at": "2026-07-13T06:30:12+09:00",
  "categories": [
    {
      "id": "ai_tech",
      "items": [
        {
          "id": "a1b2c3d4e5f6",
          "title": "記事タイトル",
          "url": "https://example.com/article",
          "source": "Hacker News",
          "published": "2026-07-13T02:11:00+09:00",
          "summary": "RSS由来の概要文(400字以内)"
        }
      ]
    }
  ]
}
```

- 終了コード: 全カテゴリ0件のときのみ 1 を返し、後続ステップを中止させる

## 5. /digest コマンド仕様(.claude/commands/digest.md)

コマンド本文には以下を過不足なく記述する。

### 入力
- `data/items.json` を Read で読む

### 処理手順
1. **クラスタリング**: カテゴリ内で同一話題を報じる記事をまとめる(タイトル・要約の意味的類似で判断)
2. **スコアリング**(importance 1〜5):
   - 複数ソースが同一話題を報道 → 加点
   - 市場・業界・政策への影響が大きい → 加点
   - 新規性がある(単なる続報・定例発表は減点)
3. **選定**: カテゴリごとに上位 `max_topics` 件(feeds.yaml 準拠。全体で10前後)
4. **深掘り**: 全体で importance 上位3件まで、代表記事URLを WebFetch で取得して要約精度を上げる(取得失敗時は RSS 要約のみで続行し、処理を止めない)
5. `data/digest.json` を Write で出力。`date` は items.json の `generated_at` の日付部分(JST)をそのまま用いる(システム日付を独自に取得しない。日付の単一情報源は generated_at)

### 出力スキーマ(digest.json)

```json
{
  "date": "2026-07-13",
  "categories": [
    {
      "id": "ai_tech",
      "topics": [
        {
          "headline": "50字以内の見出し",
          "summary": "200〜300字。事実→含意の順で構成",
          "importance": 4,
          "deep_dive": true,
          "sources": [
            { "name": "媒体名", "title": "記事タイトル", "url": "https://..." }
          ]
        }
      ]
    }
  ]
}
```

### 制約(コマンド本文に明記すること)
- 出典に書かれていない事実・数値を創作しない。数値は原文準拠
- 記事本文の文章を流用せず、summary は自分の言葉で再構成する
- 出力は digest.json の書き込みのみ。会話文・前置き・説明を出力しない

### 実行コマンド(bat から呼ぶ形)

```
claude -p "/digest" --allowedTools "Read,Write,WebFetch"
```

- カスタムスラッシュコマンドは -p(headless)モードでもプロンプト文字列に含めれば展開される
- Bash は許可しない(送信・描画・git 操作は Claude の責務外)
- bat から呼ぶ際は `call claude …` とする(npm 版 CLI は claude.cmd のため、call なしでは制御が bat に戻らず後続行が実行されない)

## 6. send_discord.py 仕様(sink A)

- 入力: `data/digest.json` と .env の webhook URL 群(**読み取り専用。ファイルの移動・削除はしない**)
- **起動時検証(前日分再配信の防止)**: digest.json の `date` が実行日(JST)と一致しなければ前日分の残骸とみなし、**送信せずに exit 1**(②が digest.json を書かずに終了した場合への防御。§8 の transient 削除と二重の防御になる)
- embed 組み立て(トピック1件 = embed 1個):
  - `title`: 「★★★★☆ 」+ headline(importance を★で先頭付与、256字以内)
  - `description`: summary + 空行 + 出典リンク行(`[媒体名](url)` 形式、最大5本)
  - `url`: sources[0].url
  - `color`: feeds.yaml のカテゴリ色
  - `timestamp`: 生成日時
- 送信単位: カテゴリごとに1メッセージ。`content` に「📰 2026-07-13 ダイジェスト — AI・テック」等の見出しを付ける
- **Discord API 制限への対応**:
  - embed はメッセージあたり最大10個 → 超過時はメッセージ分割
  - 1メッセージ内の embed 合計6000字制限 → 超過見込み時は summary を削らず**メッセージ分割**で対応
  - HTTP 429 は `Retry-After` 秒待機して1回だけ再送。その他の 4xx/5xx は exit 1
  - 複数メッセージを送る場合(カテゴリ間・分割時)はメッセージごとに1秒待機して 429 を予防する
- webhook URL は秘匿情報(漏洩すると第三者がチャンネルに投稿可能)。.env はコミットしない

## 7. render_md.py + GitHub 公開仕様(sink B)

### render_md.py
- 入力: `data/digest.json`
- **起動時検証(前日分再配信の防止)**: digest.json の `date` が実行日(JST)と一致しなければ描画せずに exit 1(§6 と同一の防御)
- 出力1: `digest/YYYY-MM-DD.md` — Discord カードと同等の内容を md で描画。ファイル名の日付は digest.json の `date` を用いる(bat の %TODAY% はログ名・コミットメッセージ専用)

```markdown
# 📰 2026-07-13 ダイジェスト

## AI・テック

### ★★★★☆ 見出し
要約本文(200〜300字)…

出典: [媒体A](url) / [媒体B](url)
```

- 出力2: `README.md` の更新 — 「最新: [2026-07-13](digest/2026-07-13.md)」+ 直近7日分のリンク一覧。**README.md は全文を render_md.py の生成物とする**(手書きセクションは持たない。直近7日分は `digest/` ディレクトリの一覧から機械的に導出)
- 出力3: `data/digest.json` を `data/archive/YYYY-MM-DD.json` へ**コピー**(移動ではない。transient 側は次回実行で上書きされる)

### git push(bat 側で実行)
- render_md.py 成功時のみ: `git add digest data/archive README.md` → `git commit -m "digest: YYYY-MM-DD"` → `git push`
- git 操作を Python に持ち込まない(bat の3行で足りる決定的処理のため)

### 認証・閲覧
- origin は GitHub の非公開リポジトリ。md は GitHub モバイルアプリ/Web でそのまま整形表示されるため、無料・非公開のままスマホ閲覧できる
- 初回に一度手動で `git push` し、Git Credential Manager(Git for Windows 標準)に資格情報を記憶させる。以後タスクスケジューラの非対話実行でも再利用される。SSH 鍵運用でも可

## 8. run_digest.bat / タスクスケジューラ

### 初回セットアップ

```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy .env.example .env   → webhook URL を記入
git remote に非公開リポを設定し、手動で一度 push(資格情報の記憶)
claude を対話モードで一度起動し、サブスクリプションでログイン済みであることを確認
```

### bat 骨子

```bat
@echo off
cd /d %~dp0
rem Python の標準入出力・ファイルI/O事故防止(cp932対策)
set PYTHONUTF8=1

rem 日付はロケール非依存で取得(%date% は書式が実行アカウントの地域設定に依存するため使わない)
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%i
set LOG=logs\%TODAY%.log

call venv\Scripts\activate

rem 前回の transient を削除(②が生成物を書かず終了した場合に前日分を再配信しないため)
del /q data\items.json data\digest.json 2>nul

rem ①② 失敗したら全体中止(生成物が無いため)
python collect.py >> %LOG% 2>&1 || goto :fail
call claude -p "/digest" --allowedTools "Read,Write,WebFetch" >> %LOG% 2>&1 || goto :fail

rem ③④ sink は独立実行。片方の失敗で他方を止めない
set ERR=0
python send_discord.py >> %LOG% 2>&1 || set ERR=1

python render_md.py >> %LOG% 2>&1
if %errorlevel%==0 (
  git add digest data\archive README.md >> %LOG% 2>&1
  git diff --cached --quiet || git commit -m "digest: %TODAY%" >> %LOG% 2>&1
  git push >> %LOG% 2>&1 || set ERR=1
) else (
  set ERR=1
)

exit /b %ERR%

:fail
echo [ERROR] pipeline aborted >> %LOG%
exit /b 1
```

- `claude` は必ず `call` 経由で呼ぶ(§5)。`git diff --cached --quiet ||` は「差分ゼロの再実行でコミットが exit 1 になり偽エラー扱いされる」ことへのガード

### タスクスケジューラ設定
- トリガー: 毎日 06:30
- 「タスクを実行するためにスリープを解除する」を有効化(電源設定と整合を取る)
- 「開始(オプション)」にリポジトリルートを指定

### ⚠ 課金事故防止(重要)
- 実行ユーザの環境変数に **ANTHROPIC_API_KEY を設定しないこと**。設定されていると Claude Code はサブスクリプションではなく API キー(従量課金)を優先して動作する
- 不安なら初回に `claude -p "/digest" --output-format json` で実行し、出力の課金情報を目視確認する

## 9. 受け入れ基準

- [ ] feeds.yaml の全フィードが疎通し、items.json に3カテゴリぶんの記事が入る
- [ ] `claude -p "/digest"` 単体実行で、スキーマ準拠の digest.json が生成される
- [ ] digest.json の summary が出典と矛盾しない(サンプル3件を人手確認)
- [ ] send_discord.py 単体実行で、3チャンネルにカードが投稿される
- [ ] embed 11個以上・合計6000字超のダミーデータで分割送信が機能する
- [ ] render_md.py 単体実行で digest/YYYY-MM-DD.md・README.md・archive コピーの3出力が揃う
- [ ] push 後、GitHub モバイルアプリで当日 md が整形表示される
- [ ] **独立性テスト**: webhook URL を故意に無効化しても、GitHub への push は成功する(逆も同様)
- [ ] **再配信防止テスト**: `date` が前日の digest.json を置いた状態で、send_discord.py / render_md.py がどちらも送信・描画せずに exit 1 する
- [ ] run_digest.bat の一気通貫が成功する
- [ ] タスクスケジューラからの自動実行が翌朝成功する

## 10. スコープ外(将来拡張メモ)

- GitHub Pages によるカード型 HTML フィード(公開リポ化、または Pages を非公開で使える有料プランが必要)
- Discord リアクションによる重要度学習(webhook では受信不可、bot 化が必要)
- 週次まとめ: data/archive/ を入力とする /weekly コマンド
- `/dig <topic>`: 特定トピックだけ対話的に深掘りするコマンド
- 既報管理: digest/ の直近数日分を /digest の入力に加え、続報の重複配信を抑制
