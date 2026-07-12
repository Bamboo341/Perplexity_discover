# discover-digest

Perplexity Discover の個人版。RSS を収集し、Claude Code が選定・要約したニュースダイジェストを毎朝 Discord(フロー)と GitHub 非公開リポ(ストック)に配信・蓄積する。仕様の正本は `Digest_spec.md`。

## 原則(Digest_spec.md §1)

- **分業原則**: 決定的な処理(収集・整形・送信・描画)は Python が担い、判断が必要な処理(クラスタリング・選定・要約)のみ Claude(/digest コマンド)が担う
- **sink独立原則**: send_discord.py(sink A)と render_md.py(sink B)はどちらも `data/digest.json` を読むだけの独立した出力先であり、片方の失敗がもう片方の実行を止めてはならない。collect.py と /digest の失敗時のみ全体を中止する(生成物が存在しないため)

## Python コーディング規約

- 型ヒント必須
- 依存は標準ライブラリ + requirements.txt 記載のもののみ
- ファイル I/O は `encoding="utf-8"` を明示する(Windows の cp932 既定対策)

## 各スクリプトの単体実行方法

venv 有効化後、リポジトリルートで実行する。

| ステップ | コマンド | 入力 → 出力 |
|---|---|---|
| ① 収集 | `python collect.py` | feeds.yaml → data/items.json |
| ② 選定・要約 | `claude -p "/digest" --allowedTools "Read,Write,WebFetch"` | data/items.json → data/digest.json |
| ③ Discord送信 | `python send_discord.py` | data/digest.json + .env → Discord |
| ④ md描画 | `python render_md.py` | data/digest.json → digest/YYYY-MM-DD.md, README.md, data/archive/ |
| 一気通貫 | `run_digest.bat` | ①〜④ + git push |

②〜④は digest.json の `date` が当日(JST)でない場合 exit 1 する(前日分の再配信防止)。
