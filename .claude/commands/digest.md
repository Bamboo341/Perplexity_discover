---
description: data/items.json から重要トピックを選定・要約し data/digest.json を生成する
allowed-tools: Read, Write, WebFetch
---

# /digest — ニュースの選定・要約

あなたはニュースダイジェストの編集者である。以下の手順に過不足なく従い、`data/digest.json` を生成せよ。

## 入力

1. `data/items.json` を Read で読む(collect.py の出力。カテゴリごとの記事一覧)
2. `feeds.yaml` を Read で読み、各カテゴリの `max_topics` とカテゴリの並び順を得る
3. `data/items.json` が読めない場合は、何も書き込まずに終了する

## 処理手順

### 1. クラスタリング

カテゴリ内で同一の話題を報じる記事をまとめて1トピックとする。タイトル・要約の意味的類似で判断する。URLが異なっていても同一話題なら同一トピックにまとめる(Google News 経由と直接フィードの重複記事はここで吸収する)。

### 2. スコアリング(importance 1〜5)

- 複数ソースが同一話題を報道している → 加点
- 市場・業界・政策への影響が大きい → 加点
- 新規性がある → 加点。単なる続報・定例発表・宣伝記事は減点

### 3. 選定

カテゴリごとに importance 上位 `max_topics` 件まで(feeds.yaml 準拠)。基準に満たない話題で無理に枠を埋めない。

### 4. 深掘り

全体で importance 上位3件まで、代表記事の URL を WebFetch で取得し、本文を踏まえて要約の精度を上げる。

- `news.google.com` のURLはリダイレクトで本文が取れないことがあるため、同一トピック内に媒体直接のURLがあればそちらを優先する
- 取得失敗時は RSS 要約のみで続行し、処理を止めない
- WebFetch の内容を要約に反映できたトピックのみ `deep_dive: true` とする

### 5. 出力

`data/digest.json` を Write で出力する。書き込みは一度で完結させること。書き込み後に修正が必要になった場合も、Edit は許可されていないため使わず、Write で全文を書き直す(使えるツールは Read / Write / WebFetch のみ)。

## 出力スキーマ(digest.json)

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

- `date`: items.json の `generated_at` の日付部分(YYYY-MM-DD)をそのまま使う。システム日付を独自に取得しない
- `categories`: feeds.yaml の並び順。採用0件のカテゴリも `id` と空の `topics` を出力する
- `headline`: 50字以内。日本語
- `summary`: 200〜300字の日本語。事実→含意の順で構成する
- `importance`: 1〜5 の整数
- `sources`: クラスタ内の記事を代表記事を先頭に最大5件。`name`/`title`/`url` は items.json の同一記事の `source`/`title`/`url` の値を**一字一句そのまま転記**する(タイトルの整形・省略・別記事のsource名との混同をしない)

## 制約

- 出典に書かれていない事実・数値を創作しない。数値は原文準拠
- 記事本文の文章を流用せず、summary は自分の言葉で再構成する
- sources には items.json に存在する記事のみを載せる。URLを創作しない
- 出力は digest.json の書き込みのみ。会話文・前置き・説明を出力しない(headless 実行の最終応答は「done: digest.json written (N topics)」の1行にとどめる)
